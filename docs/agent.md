# Agent döngüsü: sözleşme

Bu belge, operatörün sorusunu modele verip modelin istediği tool'ları çalıştıran ve sonunda tek bir sonuç döndüren agent döngüsünün sözleşmesidir. Döngü `backend/tools/` giriş noktalarını (`run_tool`, `tool_definitions`; `docs/tools.md` › Giriş noktaları) kullanır; tool sonuçları `docs/zarf.md`'deki zarfla modele gider. `experiments/function_calling/loop_envelope.py` bu döngünün deney sürümüdür; bu belge ürün sürümünü tanımlar. Sözleşme testleri koddan önce yazılır ve gevşetilmez.

**Döngü hesap yapmaz, karar vermez.** Hangi tool'un hangi argümanla çağrılacağına model karar verir; sayıları tool'lar hesaplar. Döngünün tek işi çağrıları taşımak, sınırları uygulamak ve nasıl bittiğini (`status`) doğru bildirmektir.

## Girdi

Döngü tek bir fonksiyondur: `backend.agent.run_agent(question, client=None, instruction_version=None) -> AgentResult`. Senkron çalışır.

| Alan | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `question` | metin | evet | Operatörün sorusu, olduğu gibi. Kırpılmaz, yeniden yazılmaz; modele ilk `user` mesajı olarak gider. |
| `client` | senkron Anthropic istemcisi | hayır | Model çağrıları `client.messages.create(**istek)` ile yapılır. Verilmezse `backend.llm.client` kullanılır. Testler buraya sahte istemci verir. |
| `instruction_version` | metin | hayır | System talimatının sürüm dosyası adı (`backend/instructions/<ad>.md`; `docs/system-talimat.md` › Versiyonlama). Verilmezse `backend.instructions.default_version()`: ortamdaki `COPILOT_INSTRUCTION`, boşsa `v3`. Ortam, `backend.llm` `.env`'yi yükledikten sonra okunur. |

- Boş ya da yalnızca boşluktan oluşan soru reddedilir: `ValueError` fırlar, döngü başlamaz, API çağrısı yapılmaz.
- Kayıtlı olmayan sürüm (`backend.instructions.VERSIONS`'ta yok) reddedilir: `"Bilinmeyen talimat sürümü"` ile başlayan `ValueError` fırlar, API çağrısı yapılmaz. Sürüm parametreyle verildiyse `backend.llm` de yüklenmez; ortamdan geldiyse hata `.env` yüklendikten sonra, ilk model çağrısından önce fırlar. Parametre ortamın önüne geçer.
- Her çağrı sıfırdan başlar; konuşma geçmişi girdi değildir (bkz. Kapsam dışı).
- Modele giden istek: `model=backend.llm.MODEL`, `system=backend.instructions.load(instruction_version)` (varsayılanda `backend.prompts.SYSTEM_INSTRUCTIONS` ile aynı metin), `tools=tool_definitions()`, `max_tokens=16000`. Sıcaklık gönderilmez.

## Sonuç

`AgentResult` beş alanlı bir pydantic modelidir; `model_dump()` aşağıdaki biçimi verir. Alan adları İngilizce, `status` değerleri ve `reason` metni Türkçedir.

| Alan | Tür | Açıklama |
|---|---|---|
| `status` (durum) | metin | Döngünün nasıl bittiği. Beş değerden biri; bkz. Durumlar. |
| `reason` (neden) | metin ya da `null` | `status` `tamam` ise `null`; diğerlerinde neden durduğunu anlatan kısa, genel Türkçe metin (ör. `"Aynı tool çağrısı 3. kez istendi: get_flight_summary."`). Exception metni, API yanıtı, request id içermez. |
| `text` (metin) | metin | **Son** model yanıtındaki `type == "text"` blokların birleşimi, olduğu gibi. Thinking blokları ve `tool_use` blokları girmez. Boş olabilir. |
| `turns` (turlar) | liste | Her model çağrısı için bir kayıt, çağrı sırasıyla. En az 1, en fazla 8 öğe. |
| `instruction` (talimat) | nesne | Modele giden system talimatı. Beş bitiş durumunun hepsinde bulunur. |

`instruction` öğesi:

| Alan | Tür | Açıklama |
|---|---|---|
| `name` | metin | Kullanılan sürüm dosyasının adı: `instruction_version` ya da ortamdan gelen değer (ör. `"v1"`). |
| `version` | metin | Tam sürüm, `backend.instructions.VERSIONS[name]` (ör. `"1.0.0"`). |
| `summary` | metin | Modele giden metnin SHA-256 özeti (UTF-8 byte'ları, 64 karakter küçük harf hex; `backend.instructions.summary`). Metin değişip sürüm artırılmadıysa bu alandan anlaşılır. |

`turns` öğesi:

| Alan | Tür | Açıklama |
|---|---|---|
| `index` | tamsayı | 1'den başlayan tur numarası. |
| `stop_reason` | metin | Model yanıtının `stop_reason`'ı, olduğu gibi (tanınmayan değer de). |
| `tool_calls` | liste | Yanıttaki `tool_use` blokları, yanıttaki sırayla. `tool_use` yoksa `[]`. |

`tool_calls` öğesi:

| Alan | Tür | Açıklama |
|---|---|---|
| `id` | metin | `tool_use` bloğunun `id`'si. |
| `name` | metin | İstenen tool adı, olduğu gibi (kayıtlı olmayan ad da). |
| `input` | nesne | Modelin verdiği argümanlar, olduğu gibi. |
| `executed` | mantıksal | Tool çalıştırıldıysa `true`. Hangi durumda çalıştığı Durumlar tablosundadır. |
| `envelope` | nesne ya da `null` | `executed` `true` ise `run_tool`'un döndürdüğü zarf birebir (sekiz alan); `false` ise `null`. |

- `text` yalnızca `status` `tamam` iken operatöre nihai cevap olarak sunulabilir. Diğer durumlarda çağıran `reason`'ı gösterir; `text` varsa yarım/kesik bir cevap olduğu belirtilmeden gösterilmez.
- `turns` denetim izidir: hangi sayının hangi zarftan geldiği buradan izlenir. Döngü zarfları özetlemez, kısaltmaz.

## Durumlar

Her model yanıtından sonra döngü yanıtı aşağıdaki sırayla değerlendirir; ilk eşleşen satır geçerlidir. Tablo kapalıdır: beşi dışında `status` yoktur.

| Sıra | `status` | Ne zaman | Bu turdaki tool'lar çalışır mı | `text` | `reason` |
|---|---|---|---|---|---|
| 1 | `tamam` | `stop_reason == "end_turn"`. Tur numarası önemsizdir; 8. turda da `tamam` olur. | Bu turda `tool_use` yoktur; önceki turlardakiler çalışmıştır. | Son yanıtın metni, nihai cevap. | `null` |
| 2 | `max_tokens` | `stop_reason == "max_tokens"`. | **Hayır.** Kesik yanıttaki `tool_use` blokları (varsa) `executed: false`. | Kesik metin; nihai cevap değildir. | `"Yanıt uzunluk sınırına ulaştı."` |
| 3 | `durduruldu` | `stop_reason` `refusal` ya da tanınmayan bir değer (`end_turn`, `max_tokens`, `tool_use` dışında her şey; ör. `pause_turn`, `stop_sequence`). | **Hayır.** Yanıttaki `tool_use` blokları (varsa) `executed: false`. | Yanıttaki metin (boş olabilir); nihai cevap değildir. | Refusal'da `"Model yanıt vermeyi reddetti."`; diğerlerinde `"Beklenmeyen durma nedeni."` |
| 4 | `tekrar_siniri` | `stop_reason == "tool_use"` ve bu turdaki çağrılardan en az biri, aynı ad + aynı argümanla tüm döngüde **3. kez** isteniyor (bkz. Sınırlar). | **Hayır, hiçbiri.** Tekrar olmayan çağrılar da dahil bu turun tüm çağrıları `executed: false`. | Yanıttaki metin (boş olabilir); nihai cevap değildir. | `"Aynı tool çağrısı 3. kez istendi: <ad>."` (ilk tekrar eden çağrının adı) |
| 5 | `iterasyon_siniri` | `stop_reason == "tool_use"`, tekrar sınırı aşılmamış ve bu, 8. tur. | **Hayır, hiçbiri.** Tüm çağrılar `executed: false`. | Yanıttaki metin (boş olabilir); nihai cevap değildir. | `"Tur sınırına (8) ulaşıldı."` |
| — | (döngü sürer) | `stop_reason == "tool_use"`, tekrar sınırı aşılmamış, tur 8'den küçük. | **Evet, hepsi**, yanıttaki sırayla. Sonuçlar bir sonraki turun girdisi olur. | — | — |

Özet: tool **yalnızca döngü sürerken** çalışır. Beş bitiş durumunun hiçbirinde son yanıttaki `tool_use` blokları çalıştırılmaz; böylece sonucu modele hiç gitmeyecek bir tool çağrısı yapılmaz.

## Sınırlar

| Sınır | Değer | Neyi sayar | Aşılınca |
|---|---|---|---|
| Tur | 8 | Model (API) çağrısı sayısı. Bir tur = bir `messages.create`. Tool çalıştırmak tur sayılmaz. En fazla 7 turda tool çalışır. | `iterasyon_siniri` |
| Tekrar | 3 | Aynı `(ad, argüman)` çiftinin döngü boyunca kaç kez **istendiği**. Argümanlar anahtarları sıralı kanonik JSON'a çevrilerek karşılaştırılır (`{"a":1,"b":2}` ile `{"b":2,"a":1}` aynıdır). Aynı turda iki kez istenen çift iki sayılır. Çalıştırılmamış istekler de sayılır. | 3. istekte `tekrar_siniri` |
| Yanıt uzunluğu | `max_tokens=16000` | Tek model yanıtının çıktı token'ı (thinking dahil). | `max_tokens` |

- Sınır değerleri kodda adlandırılmış sabittir (`MAX_TURNS = 8`, `MAX_REPEATS = 3`); döngüye argüman olarak verilmez.
- Farklı argümanla aynı tool tekrar sayılmaz: `get_flight_summary` `{"direction": "all"}` ve `{"direction": "arrival"}` iki ayrı çifttir. Böylece `docs/tools.md` › Kenar durumlar'daki "enum'daki değerle bir kez yeniden çağırır" davranışı sınıra takılmaz.
- Hata dönen çağrı da sayılır: `{"direction": "ALL"}` üç kez istenirse 3. istek `tekrar_siniri`'dir.

## Kurallar

- **Tool yalnızca `run_tool` ile çalışır.** Döngü tool fonksiyonlarını doğrudan çağırmaz, argümanı doğrulamaz, düzeltmez ya da varsayılan eklemez; `name` ve `input` `run_tool(name, input)`'a olduğu gibi gider. Kayıtlı olmayan ad da `run_tool`'a gider ve `CAPABILITY_NOT_IN_SCOPE` zarfı döner.
- **Zarf birebir modele gider.** Her `tool_result`'ın içeriği (`content`) zarfın tamamıdır, `ensure_ascii=False` JSON metni; `is_error` her `tool_result`'ta açıkça yazılır. Döngü zarftan alan çıkarmaz, `error.message`'ı yeniden yazmaz.
- **`is_error` yalnızca `SCHEMA_VALIDATION_FAILED`'da `true`.** `NOT_FOUND`, `AMBIGUOUS_ENTITY`, `CAPABILITY_NOT_IN_SCOPE`, `STALE_DATA` geçerli tool sonuçlarıdır; `is_error: false` ile gider (`loop_envelope.py` ile aynı).
- **Bir turun sonuçları tek mesajda gider.** Turdaki tüm `tool_result`'lar, `tool_use` sırasıyla ve aynı `id`'lerle tek bir `user` mesajına konur.
- **Asistan turu olduğu gibi geri gönderilir.** Geçmişe `response.content` eklenir; yalnızca metin değil, thinking blokları da (CLAUDE.md › Kurallar).
- **Döngü hesap yapmaz, cevap yazmaz.** `text` modelin metnidir; döngü sayı eklemez, metni zarflarla birleştirmez, `status` `tamam` değilken kendi cevabını üretmez.
- **Saat ve veri okunmaz.** Döngü sistem saatini okumaz (`as_of` zarftan gelir; `docs/zarf.md` › Saat tek yerden okunur), `COPILOT_DATA`'yı açmaz.
- **Model adı gömülmez.** Model `backend.llm.MODEL`'den alınır; döngü `backend.llm`'i ilk çağrıda yükler, modül düzeyinde import etmez (`/health` anahtarsız çalışmaya devam eder).
- **API ve ayar hataları durum değildir.** `ConfigError` ya da Anthropic API hatası (ağ, 4xx/5xx, geçersiz model) yakalanmaz, çağırana fırlar; o ana kadarki turlar sonuç olarak dönmez. Çağıran istemciye yalnızca genel Türkçe mesaj verir, ayrıntıyı `logger.exception` ile loglar (CLAUDE.md › Yasaklar).
- **Belirlenimcilik testte sahte istemciyle sağlanır.** Sözleşme testleri gerçek API çağırmaz; model yanıtlarını sırayla döndüren bir sahte istemci kullanır, `COPILOT_DATA` ve `COPILOT_NOW` sabitlenir.

## Örnek

Değerler `data/referans/seed42-2026-10-20.json`'dan; `COPILOT_NOW=2026-10-20T16:22:00+03:00`. Model metni örnektir.

`run_agent("Bugün kaç uçuş var?")`:

```json
{
  "status": "tamam",
  "reason": null,
  "text": "Bugün 600 uçuş var; 4'ü iptal, 115'i gecikmeli. Kaynak: data/referans/seed42-2026-10-20.json, 16:22 itibarıyla.",
  "turns": [
    {
      "index": 1,
      "stop_reason": "tool_use",
      "tool_calls": [
        {
          "id": "toolu_01",
          "name": "get_flight_summary",
          "input": {"direction": "all"},
          "executed": true,
          "envelope": {
            "value": {"date": "2026-10-20", "direction": "all", "total": 600, "cancelled": 4, "delayed": 115},
            "source": "data/referans/seed42-2026-10-20.json",
            "as_of": "2026-10-20T16:22:00+03:00",
            "filters": {"direction": "all"},
            "stale": false,
            "tool_version": "1.0.0",
            "error": null,
            "author": "tool"
          }
        }
      ]
    },
    {"index": 2, "stop_reason": "end_turn", "tool_calls": []}
  ],
  "instruction": {
    "name": "v1",
    "version": "1.0.0",
    "summary": "050490f448180e4658f96a55d9b3d9e002d90e3645bc0172acf8956e6bf527e5"
  }
}
```

`summary` `backend/instructions/v3.md`'nin şu anki metnine aittir; metin değişince değişir (testler beklenen değeri dosyadan hesaplar).

Aynı soruda model `{"direction": "ALL"}`'u üç kez isterse: 1. ve 2. turda çağrı çalışır ve `SCHEMA_VALIDATION_FAILED` (`is_error: true`) döner; 3. turda istek çalıştırılmaz, sonuç `status: "tekrar_siniri"`, `reason: "Aynı tool çağrısı 3. kez istendi: get_flight_summary."`, `turns` 3 öğe, 3. öğede `executed: false`, `envelope: null`.

## Kapsam dışı

- `/chat` entegrasyonu ve SSE olayları: sonucun akışa nasıl yansıyacağı `docs/chat.md`'dedir. `/chat` döngüyü `run_agent` ile, model çağrılarını saran bir istemci vererek kullanır; döngünün kendisi bu belgedeki gibidir.
- Akış (streaming): döngü her turda tam yanıtı bekler; ara metin parçaları dışarı verilmez.
- Konuşma geçmişi ve çok turlu sohbet: her `run_agent` tek sorudur, durum tutmaz.
- Dış iptal (istemcinin bağlantıyı kesmesi, zaman aşımı): `durduruldu` yalnızca modelin `stop_reason`'ından doğar.
- Sistem talimatı değişikliği: `SYSTEM_INSTRUCTIONS` şu an "canlı veriye erişimin yok" der; tool'larla uyumlu hale getirilmesi ayrı iştir.
- Paralel tool çalıştırma: aynı turdaki çağrılar sırayla çalışır.
- Yeniden deneme: API hatasında, `max_tokens`'ta ya da `durduruldu`'da döngü kendiliğinden yeniden denemez.
- Sınırların istek başına ayarlanması, sıcaklık, model seçimi.
- Kod: bu belge yalnızca sözleşmedir. Sözleşme testleri `tests/test_agent.py`'dedir.
