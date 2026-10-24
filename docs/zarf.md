# Tool çıktı zarfı: sözleşme

Her tool çıktısı, başarılı da olsa hatalı da olsa, aynı zarfla döner. Amaç, agent'ın sayıyı kaynağı ve veri zamanıyla vermesini (`docs/spec.md` §1) ve eksik, eski ya da belirsiz veride sayı/durum uydurmamasını (`docs/bozulma.md`) tek bir yapı üzerinden sağlamaktır. Zarfı `backend/envelope.py` kurar, saati `backend/clock.py` verir; sözleşme testleri `tests/test_envelope.py` ve `tests/test_clock.py`'dedir.

## Alanlar

Makinece okunur hali `docs/zarf.schema.json`'dır (JSON Schema). Şema `backend/envelope.py` › `Envelope` modelinden `python -m backend.envelope` ile üretilir, elle düzeltilmez; model değişip şema yeniden üretilmezse `tests/test_envelope.py` kırmızıya döner. `stale` ile `STALE_DATA`'nın birlikte gitmesi kuralı şemada yalnızca açıklama olarak yer alır; modelde doğrulanır.

Zarf tam olarak aşağıdaki sekiz alandan oluşur. **Alanlar değişmez:** alan eklenmez, çıkarılmaz, yeniden adlandırılmaz. Sekiz alan her yanıtta bulunur; anlamı olmayan alan `null` olur, atlanmaz.

| Alan | Tip | Anlamı |
|---|---|---|
| `value` | nesne, dizi ya da `null` | Tool'un döndürdüğü veri. Hesap serviste yapılmıştır; agent bu değeri yorumlar, yeniden hesaplamaz. |
| `source` | metin ya da `null` | Verinin geldiği kaynak (dosya yolu, tablo). Agent yanıtında kaynağı buradan gösterir. Katman hatasında `null`. |
| `as_of` | ISO 8601 zaman, `+03:00` ya da `null` | Verinin hangi ana ait olduğu; **katman hesaplar**. Tool veri zamanı (`data_time`, ör. konumun `ts`'si) verdiyse o, vermediyse (anlık görüntü) saatin o anki değeri. Katman hatasında `null`. |
| `filters` | nesne | Tool'a verilen argümanlar, doğrulamadan geçmiş haliyle (varsayılanlar dahil). Agent sorunun doğru anlaşıldığını buradan kontrol eder. Argüman doğrulanamadıysa `{}`. |
| `stale` | boolean | **Katman hesaplar.** Saat − `as_of`, tool'un tazelik eşiğini (`ToolSpec.max_age`) aşarsa `true`; eşiğe eşit yaş eski sayılmaz. Eşik tanımsızsa her zaman `false`. |
| `tool_version` | metin ya da `null` | Tool'un sürümü (`MAJOR.MINOR.PATCH`). Kayıtlı olmayan tool istendiyse `null`. |
| `error` | nesne ya da `null` | Başarıda `null`. Hatada `{"code": "...", "message": "..."}`; `code` aşağıdaki listeden, `message` kısa ve genel bir Türkçe açıklama. Exception metni, yığın izi ya da iç ayrıntı içermez (CLAUDE.md › Yasaklar). |
| `author` | `"tool"` ya da `"layer"` | Zarfı kimin yazdığı. `tool`: tool'un kendisi. `layer`: tool'u saran katman; tool hiç çalışmadan ya da tool'un çıktısı reddedildikten sonra yanıtı katman üretir. |

## Tool ne döndürür

Tool zarfı kendisi kurmaz; katmana yalnızca şu nesneyi döndürür:

| Alan | Zorunlu | Anlamı |
|---|---|---|
| `value` | evet | Zarfın `value`'su olur. |
| `source` | evet | Zarfın `source`'u olur. |
| `data_time` | hayır | Verinin zamanı; saat dilimli ISO 8601. Saat dilimsizse çıktı reddedilir. |
| `error` | hayır | Yalnızca `NOT_FOUND` ya da `AMBIGUOUS_ENTITY`. Başka bir kod çıktının reddedilmesine yol açar. |

Tool `as_of` ya da `stale` gönderirse **yok sayılır**; ikisini de katman hesaplar. Bunların dışındaki ek alanlar da atılır.

## Hata kodları

| Kod | Yazan | Ne zaman döner | Agent ne yapar | Agent ne yapmaz |
|---|---|---|---|---|
| `NOT_FOUND` | `tool` | Aranan varlık (sefer no, callsign, tescil, stand) kaynakta yok. `value: null`. | Kaydın bulunamadığını, `filters`'taki arama değeriyle söyler. Sefer no ya da tarihi kontrol etmesini önerebilir. | Benzer bir kayıt seçip onu yanıt olarak vermez. Yetim kayıtlardan (`movements`, `positions`, `delays`) sefer no, tarife ya da durum kurmaz. |
| `AMBIGUOUS_ENTITY` | `tool` | Arama değeri birden fazla varlıkla eşleşiyor (ör. aynı callsign'lı iki uçuş). `value`, eşleşen adayların listesidir. | Adayların hepsini sefer no, tescil ve tarifeyle listeler; sefer no ya da tescille netleştirme ister. | Adaylardan birini kendisi seçmez; adayların değerlerini birleştirmez ya da toplamaz. |
| `STALE_DATA` | `layer` | Veri var ama `as_of` tazelik eşiğinden eski. `stale: true`; `value` son bilinen değeri taşır. | Son değeri `as_of` zaman damgasıyla verir ve verinin eski olduğunu açıkça söyler. | Güncel değeri ara değerleme, tahmin ya da başka kayıtlardan (ör. block zamanından konum) üretmez; eski değeri güncelmiş gibi sunmaz. |
| `CAPABILITY_NOT_IN_SCOPE` | `layer` | İstenen iş PoC kapsamı dışında (`docs/spec.md` §1: tahmin, yazma işlemi, proaktif alarm, gerçek kaynak sistem, kişisel veri vb.) ya da bunu yapan bir tool yok. Tool çağrılmaz. `value: null`. | Bu işin kapsam dışı olduğunu söyler; varsa kapsam içindeki yakın soruyu önerir. | İşi kendi bilgisiyle yapmaya çalışmaz (tahmin üretmez, kayıt "güncelledim" demez); başka bir tool'u amacı dışında kullanarak sonucu taklit etmez. |
| `SCHEMA_VALIDATION_FAILED` | `layer` | Tool argümanları tool şemasına uymuyor (tool çağrılmaz) ya da tool çıktısı çıktı şemasına uymuyor (çıktı atılır). `value: null`. | Argüman hatasıysa argümanı şemaya göre düzeltip **bir kez** yeniden çağırır; yine olmazsa ya da hata çıktıdaysa isteğin şu an yanıtlanamadığını söyler. | Reddedilen çıktıdan değer kullanmaz; şemayı aşmak için alan uydurmaz; aynı çağrıyı döngüde tekrarlamaz. |

`stale` ile `STALE_DATA` birlikte gider: `stale: true` olan her yanıtta `error.code` `STALE_DATA`'dır, `STALE_DATA` dönen her yanıtta `stale` `true`'dur.

## Eksik alan hata değildir

`value` içindeki bir alanın kaynakta bulunmaması **hata değildir**. Tool bu durumda hata kodu döndürmez, `error: null` kalır; alan `value`'da yer almaz (anahtar yok, `null` ya da varsayılan değer de yazılmaz).

- Agent alanın veride bulunmadığını söyler ve var olan diğer alanlarla yanıt verir.
- Agent eksik değeri başka alanlardan kendisi hesaplamaz (ör. tahmini zamanı tarife + gecikmeden çıkarmaz). Bkz. `docs/bozulma.md` › `missing_field`.
- Bu kural yalnızca `value` içindir. Zarfın sekiz alanı her zaman bulunur; tool çıktısında zorunlu alanın (`value`, `source`) eksik olması `SCHEMA_VALIDATION_FAILED` sebebidir.

## Saat tek yerden okunur

Sistem saati tek bir yerde okunur: `backend/clock.py` › `now()`. Tool'lar ve katman o anki zamanı yalnızca bu fonksiyondan alır; `datetime.now()`, `time.time()` ya da benzeri bir çağrı `backend/` altında başka hiçbir modülde yapılmaz (`tests/test_clock.py` tarar).

- `COPILOT_NOW` doluysa `now()` her çağrıda bu sabit anı döner (saat dilimli ISO 8601, ör. `2026-10-20T16:22:00+03:00`; `+03:00`'e çevrilir). Boş ya da tanımsızsa sistem saati `+03:00` ile döner. Saat dilimsiz ya da bozuk değer Türkçe `ClockError` verir.

- `as_of` (anlık görüntü kaynağında) ve `stale` hesabı bu saate göre yapılır.
- Simülasyonda saat simüle zamanı verir; böylece aynı veri ve aynı simüle zamanla zarf byte byte aynı olur.
- Testler saati `COPILOT_NOW` ile sabitler.

## Örnekler

Değerler `data/referans/seed42-2026-10-20.json`'dan alınmıştır; simüle saat `2026-10-20T16:22:00+03:00`. `get_flight_position` örnek amaçlı bir tool adıdır, henüz tanımlı değildir; örnekte tazelik eşiği 5 dakikadır. `tests/test_envelope.py` bu üç örneği katmanın ürettiği zarfla birebir karşılaştırır.

**1. Başarılı yanıt.** `get_flight_summary` (`experiments/function_calling/loop.py`), tüm yönler:

```json
{
  "value": {"date": "2026-10-20", "direction": "all", "total": 600, "cancelled": 4, "delayed": 115},
  "source": "data/referans/seed42-2026-10-20.json",
  "as_of": "2026-10-20T16:22:00+03:00",
  "filters": {"direction": "all"},
  "stale": false,
  "tool_version": "1.0.0",
  "error": null,
  "author": "tool"
}
```

**2. `STALE_DATA`.** `stale_position` senaryosu (`docs/bozulma.md`) uygulanmış veride `TK2345`'in konumu. 41 noktalık izin son noktası 16:22'dir; senaryo son 10 dakikayı siler, kalan son nokta 16:12'dir. 10 dakikalık yaş 5 dakikalık eşiği aştığı için zarfı katman yazar. Agent: "TK2345'in son bilinen konumu 16:12 itibarıyla, CLIMB fazında; veri 10 dakika eski, güncel konum yok."

```json
{
  "value": {
    "flight_id": "FL-20261020-0270",
    "flight_no": "TK2345",
    "ts": "2026-10-20T16:12:00+03:00",
    "lat": 41.197692,
    "lon": 28.680769,
    "heading_deg": 235.0,
    "speed_kt": 187.7,
    "phase": "CLIMB"
  },
  "source": "synth/out/stale.json",
  "as_of": "2026-10-20T16:12:00+03:00",
  "filters": {"flight_no": "TK2345"},
  "stale": true,
  "tool_version": "1.0.0",
  "error": {"code": "STALE_DATA", "message": "Veri güncel değil; son bilinen değer döndürüldü."},
  "author": "layer"
}
```

**3. `NOT_FOUND`.** `ZZ9999` hiçbir kayıtta yoktur (`docs/spec.md` §9).

```json
{
  "value": null,
  "source": "data/referans/seed42-2026-10-20.json",
  "as_of": "2026-10-20T16:22:00+03:00",
  "filters": {"flight_no": "ZZ9999"},
  "stale": false,
  "tool_version": "1.0.0",
  "error": {"code": "NOT_FOUND", "message": "Bu sefer numarasıyla uçuş bulunamadı."},
  "author": "tool"
}
```
