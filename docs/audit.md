# Audit kaydı ve geri bildirim

`/chat`'e gelen her soru için tek satırlık audit kaydının ve operatörün yanlış cevabı işaretlediği olumsuz geri bildirimin (thumbs down) sözleşmesi. Akış `docs/chat.md`, döngü ve `AgentResult` `docs/agent.md`, zarf `docs/zarf.md`.

Amaç, yanlış bulunan bir cevabın hangi soruya, hangi talimat sürümüyle, hangi tool çağrılarıyla ve hangi kaynak/veri zamanıyla üretildiğini sonradan izleyebilmektir. Kayıt bir denetim izidir; cevabı yeniden üretmek için değil, nereden geldiğini göstermek içindir.

## Dosya

| Konu | Kural |
|---|---|
| Klasör | `COPILOT_AUDIT_DIR`; boşsa repo köküne göre `logs/audit`. Klasör yoksa ilk yazımda oluşturulur. `logs/` `.gitignore`'dadır, kayıtlar commit edilmez. |
| Dosya adı | `YYYY-MM-DD.jsonl`; tarih satırın `ts` alanının (`+03:00`) tarihidir. Gün dönümünde yeni dosya açılır, eski dosya değişmez. |
| Biçim | JSON Lines: her satır tek bir JSON nesnesi, sonunda `\n` (`newline="\n"`). UTF-8, `ensure_ascii=False`; Türkçe karakterler kaçışsız. Satır içinde satır sonu yoktur (JSON tek satır yazılır). |
| Yazım | Yalnızca sona ekleme (append-only). Yazılmış satır değiştirilmez, silinmez, yeniden sıralanmaz. Her satır tek `write` ile yazılır ve hemen `flush` edilir. Aynı süreçteki eşzamanlı istekler bir kilitle sıraya girer; satırlar iç içe geçmez. |
| Satır türleri | İki tür vardır: `question` (her soru için bir) ve `feedback` (her thumbs down için bir). Tablo kapalıdır. |
| Saat | `ts` `backend/clock.py` › `now()`'dan alınır (`COPILOT_NOW` doluysa o an); `datetime.now()` çağrılmaz (`tests/test_clock.py`). |

`COPILOT_AUDIT_DIR` süreç ortamından okunur; `.env`'deki değer `load_llm()`'den sonra görünür (CLAUDE.md › Kurallar). Testler klasörü `tmp_path`'e yönlendirir.

## Alanlar

### `question` satırı

Alan sırası tablodaki gibidir. Bütün alanlar her satırda bulunur; anlamı olmayan alan `null` olur, atlanmaz.

| Alan | Tür | Açıklama |
|---|---|---|
| `type` | `"question"` | Satır türü. |
| `audit_id` | metin | Bu sorunun kimliği: 32 karakter küçük harf hex (`uuid4().hex`). Geri bildirim bu kimlikle bağlanır. |
| `ts` | ISO 8601, `+03:00` | Satırın yazıldığı an (döngü bittikten sonra). |
| `question` | metin | Operatörün sorusu, `/chat` gövdesindeki `message`, olduğu gibi. Kırpılmaz, kısaltılmaz. |
| `status` | metin | `AgentResult.status` (beş değerden biri; `docs/agent.md` › Durumlar) ya da model çağrısı / beklenmeyen hata için `model_error`. |
| `reason` | metin ya da `null` | `AgentResult.reason`. `tamam`'da `null`; `model_error`'da `ERROR_MESSAGE` (`backend/main.py`). |
| `answer` | metin ya da `null` | Yalnızca `status` `tamam` iken `AgentResult.text` (operatöre giden `text_delta`'ların birleşimi). Diğer durumlarda `null`; kesik/ara metin kayda girmez (`docs/chat.md` › Kod garantileri 8). |
| `model` | metin ya da `null` | `backend.llm.MODEL`. Kodda sabit yazılmaz. |
| `instruction` | nesne ya da `null` | `AgentResult.instruction` (`name`, `version`, `summary`) olduğu gibi. `model_error`'da sonuç olmadığından `name` ve `version` istekte çözülen sürümden, `summary` yüklenen metinden doldurulur. |
| `turns` | tamsayı ya da `null` | `len(AgentResult.turns)`. `model_error`'da `null` (turlar döngüyle birlikte kaybolur; `docs/agent.md` › Kurallar). |
| `tool_calls` | liste | Aşağıdaki öğelerden oluşur; `AgentResult.turns[].tool_calls[]` sırasıyla, `executed: false` olanlar dahil. Tool çağrısı yoksa ya da `model_error`'da `[]`. |

`tool_calls` öğesi:

| Alan | Tür | Kaynak |
|---|---|---|
| `turn` | tamsayı | Çağrının bulunduğu turun `index`'i. |
| `name` | metin | `tool_calls[].name`, olduğu gibi (kayıtlı olmayan ad da). |
| `input` | nesne | `tool_calls[].input`, modelin verdiği argümanlar, olduğu gibi. |
| `executed` | mantıksal | `tool_calls[].executed`. |
| `source` | metin ya da `null` | Zarfın `source`'u. `executed: false` ise `null`. |
| `as_of` | metin ya da `null` | Zarfın `as_of`'u. `executed: false` ise `null`. |
| `stale` | mantıksal ya da `null` | Zarfın `stale`'i. `executed: false` ise `null`. |
| `tool_version` | metin ya da `null` | Zarfın `tool_version`'ı. `executed: false` ise `null`. |
| `author` | `"tool"`, `"layer"` ya da `null` | Zarfın `author`'u. `executed: false` ise `null`. |
| `error_code` | metin ya da `null` | Zarfın `error.code`'u (beş koddan biri); başarıda ve `executed: false` ise `null`. `error.message` kayda girmez. |

### `feedback` satırı

| Alan | Tür | Açıklama |
|---|---|---|
| `type` | `"feedback"` | Satır türü. |
| `audit_id` | metin | Geri bildirimin ait olduğu `question` satırının kimliği. |
| `ts` | ISO 8601, `+03:00` | Geri bildirimin yazıldığı an. Dosya bu ana göre seçilir; dünkü bir soruya bugün verilen geri bildirim bugünün dosyasına yazılır. |
| `rating` | `"down"` | Tek değer: cevap yanlış. Olumlu değerlendirme yoktur. |

Serbest metin (not, açıklama) alanı yoktur.

## Uçlar

### `/chat` değişikliği

- `done` olayının `data`'sına `audit_id` eklenir: `{"status": ..., "reason": ..., "turns": ..., "instruction": {...}, "audit_id": "..."}`. `docs/chat.md` › Olay tipleri bu iş yapılırken birlikte güncellenir; `chat.ts` doğrulaması da.
- `question` satırı döngü bittikten sonra, `done` (ya da `model_error`'daki son `error`) olayı yazılmadan **önce** yazılır. Böylece istemci kimliği aldığında satır dosyadadır.
- Kayıt yazılamazsa (izin, disk) hata `logger.exception` ile loglanır, akış etkilenmez; `done`'da `audit_id: null` gider ve arayüz thumbs down göstermez.
- `model_error`'da `done` olmadığından `audit_id` istemciye gitmez; satır yine yazılır.
- Akış başlamadan reddedilen istekler (`422`, `503`; `docs/chat.md` › Uç) kayıt üretmez: soru döngüye hiç girmemiştir.

### `POST /feedback`

Gövde `{"audit_id": "..."}`; ek alan reddedilir.

| Durum | Kod | Gövde |
|---|---|---|
| Satır yazıldı | `204` | boş |
| `audit_id` yok, 32 karakter küçük harf hex değil ya da ek alan var | `422` | FastAPI doğrulama gövdesi |
| Satır yazılamadı | `503` | `{"detail": "Geri bildirim kaydedilemedi. Lütfen daha sonra tekrar deneyin."}`; ayrıntı yalnızca sunucu logunda |

- Sunucu `audit_id`'nin bir `question` satırına karşılık geldiğini dosyaları tarayarak doğrulamaz; eşleştirme analizde yapılır, eşleşmeyen `feedback` satırı yetim sayılır.
- Aynı `audit_id` için ikinci geri bildirim de yazılır (append-only); analiz `audit_id` başına tek sayar.
- `/feedback` `backend.llm`'i yüklemez; API anahtarı olmadan çalışır.
- `frontend/vite.config.ts` proxy listesine `/feedback` eklenir (backend'de CORS yok).

## Kurallar

1. **Tool `value`'su kayda girmez.** Zarfın yalnızca `source`, `as_of`, `stale`, `tool_version`, `author` ve `error.code` alanları taşınır. `value`, `filters`, `error.message` ve `selection_card` adayları (`value` dizisidir) yazılmaz. Operatif değerin kendisi kaynakta ve cevap metnindedir; kayıt yalnızca nereden geldiğini gösterir.
2. **Bir soru, bir satır.** Her `/chat` isteği (akış başladıysa) tam olarak bir `question` satırı üretir; beş bitiş durumunda ve `model_error`'da. Geri bildirim bu satırı değiştirmez, ayrı satırdır.
3. **Kayıt yorumlamaz.** Alanlar `AgentResult`'tan ve zarftan olduğu gibi taşınır; hesap, özet, kısaltma, saat dönüşümü yoktur.
4. **Hata ayrıntısı girmez.** Exception metni, yığın izi, API yanıtı, request id ve API anahtarı hiçbir satıra yazılmaz (CLAUDE.md › Yasaklar). `model_error`'da `reason` genel `ERROR_MESSAGE`'dır.
5. **Kayıt akışı bozmaz.** Audit yazımı olay sırasını ve içeriğini değiştirmez; tek fark `done`'daki `audit_id` alanıdır. Yazım hatası akışı kesmez.
6. **Model ve saat gömülmez.** `model` `backend.llm.MODEL`'den, `ts` `clock.now()`'dan gelir.
7. **Testler sahte modelle ve geçici klasörle koşar.** `COPILOT_AUDIT_DIR` `tmp_path`'e, `COPILOT_NOW` sabit ana ayarlanır; testler satırı okuyup `value` anahtarının hiçbir düzeyde bulunmadığını da assert eder.

## Arayüz kuralları

1. Thumbs down ikonu yalnızca `done.status` `tamam` ve `audit_id` `null` değilken, cevabın altında gösterilir. `error` ile biten akışta gösterilmez.
2. Tek tıkla `POST /feedback` gönderilir; not ya da açıklama istenmez.
3. Gönderim sonrası ikon devre dışı kalır ve "Geri bildiriminiz alındı." gösterilir; geri alma yoktur. Başarısızsa "Geri bildirim gönderilemedi." gösterilir, ikon yeniden tıklanabilir.
4. Olumlu (thumbs up) geri bildirim yoktur.

## Örnek

`COPILOT_NOW=2026-10-20T16:22:00+03:00`, `docs/agent.md` › Örnek'teki koşu (`get_flight_summary`, `value` `{"total": 600, ...}`), dosya `logs/audit/2026-10-20.jsonl`. Satırlar okunabilirlik için bölünmüştür; dosyada her biri tek satırdır. `audit_id` ve `model` örnektir.

```text
{"type": "question", "audit_id": "3f9c2a7e4b1d4c8e9a0f6b2d7e5c1a3b", "ts": "2026-10-20T16:22:00+03:00",
 "question": "Bugün kaç uçuş var?", "status": "tamam", "reason": null,
 "answer": "Bugün 600 uçuş var; 4'ü iptal, 115'i gecikmeli.", "model": "<backend.llm.MODEL>",
 "instruction": {"name": "v1", "version": "1.0.0", "summary": "050490f4…27e5"}, "turns": 2,
 "tool_calls": [{"turn": 1, "name": "get_flight_summary", "input": {"direction": "all"}, "executed": true,
   "source": "data/referans/seed42-2026-10-20.json", "as_of": "2026-10-20T16:22:00+03:00", "stale": false,
   "tool_version": "1.0.0", "author": "tool", "error_code": null}]}
{"type": "feedback", "audit_id": "3f9c2a7e4b1d4c8e9a0f6b2d7e5c1a3b", "ts": "2026-10-20T16:23:10+03:00", "rating": "down"}
```

Satırda `600`, `4`, `115` yalnızca modelin cevap metninde (`answer`) geçer; zarfın `value`'su yoktur.

## Kapsam dışı

- Kullanıcı kimliği ve oturum: uygulamada kimlik doğrulama yoktur; satırda kullanıcı alanı bulunmaz.
- Saklama süresi, dosya döndürme/silme, sıkıştırma.
- Çok süreçli yazım (birden çok uvicorn worker): kilit süreç içidir; tek süreç varsayılır.
- Docker'da kalıcı klasör (volume) bağlama.
- Token sayısı ve süre ölçümü (`docs/chat.md` › Kapsam dışı).
- Olumlu geri bildirim, geri bildirimin geri alınması, serbest metin not.
- Kayıtları okuyan analiz/rapor aracı.
