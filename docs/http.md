# Tool HTTP sarmalayıcısı: sözleşme

Bu belge, `backend/tools/` giriş noktalarını (`run_tool`, `tool_definitions`; `docs/tools.md` › Giriş noktaları) HTTP üzerinden açan sarmalayıcının sözleşmesidir. Uç noktalar `backend/main.py`'deki FastAPI uygulamasına eklenir; sözleşme testleri koddan önce yazılır ve gevşetilmez.

**HTTP yalnızca taşıyıcıdır.** Zarfı kurmaz, değiştirmez, alan eklemez ya da çıkarmaz; zarfı `run_tool` kurar (`docs/zarf.md`). Sarmalayıcının tek kararı, zarfın `error.code`'una bakarak HTTP durum kodunu seçmektir.

## Uç noktalar

| Yöntem ve yol | İstek gövdesi | Ne yapar | Yanıt gövdesi | Durum kodu |
|---|---|---|---|---|
| `GET /tools` | Yok | `tool_definitions()`'ı çağırır. | `tool_definitions()`'ın döndürdüğü liste, olduğu gibi: her öğe `name`, `description`, `input_schema`; sıra `docs/tools.md`'deki sıradır. | Her zaman `200`. |
| `POST /tools/{ad}` | Tool argümanları, JSON (ör. `{"direction": "all"}`) | Yoldaki `{ad}`'ı ve çözülmüş gövdeyi olduğu gibi `run_tool(ad, gövde)`'ye verir. | `run_tool`'un döndürdüğü zarf, birebir (sekiz alan). | Aşağıda › Durum kodu eşlemesi. |

### `GET /tools`

- Liste her istekte `tool_definitions()`'tan yeniden alınır; sarmalayıcı önbellek tutmaz, kontrat değişince bir sonraki istek yeni tanımı döndürür.
- `value_schema` ve `version` listeye eklenmez; liste Anthropic tool tanımı biçimindedir (`docs/tools.md` › Giriş noktaları).
- Yanıt zarf değildir; `GET /tools` zarf üretmez.

### `POST /tools/{ad}`

- `{ad}` doğrulanmaz, kırpılmaz, harf dönüşümüne uğramaz. Bilinmeyen ad da `run_tool`'a gider; `run_tool` `CAPABILITY_NOT_IN_SCOPE` zarfı döndürür.
- Gövde, sarmal nesne olmadan doğrudan argümandır. `{"args": {...}}` biçimi desteklenmez; böyle bir gövde `args` adlı ek argüman sayılır ve `SCHEMA_VALIDATION_FAILED` döner.
- Argüman doğrulaması yalnızca `run_tool`'da (kontrattaki `input_schema` ile) yapılır. Sarmalayıcı argüman için ayrı pydantic modeli tanımlamaz, FastAPI'nin kendi doğrulama hatasını (`{"detail": [...]}`) üretmez.
- Sorgu dizesi (`?direction=all`) okunmaz; argüman yalnızca gövdeden gelir.

## Durum kodu eşlemesi

Durum kodu **yalnızca** zarfın `error.code`'una bakılarak seçilir. `author`, `stale`, `value` ya da `filters` durum kodunu etkilemez. Gövde her satırda zarfın kendisidir.

| `error.code` | HTTP durum kodu | Ne zaman | Örnek istek |
|---|---|---|---|
| `null` (başarı) | `200 OK` | Tool çalıştı, sonuç döndü. | `POST /tools/get_flight_summary`, `{"direction": "all"}` |
| `STALE_DATA` | `200 OK` | Veri var ama eski; `value` son bilinen değeri taşır. Üç uçuş tool'unda tazelik eşiği tanımlı olmadığı için şu an dönmez (`docs/tools.md` › Giriş noktaları). | Şu an yok |
| `NOT_FOUND` | `404 Not Found` | Aranan varlık kaynakta yok. | `POST /tools/resolve_flight_identity`, `{"query": "ZZ9999"}` |
| `AMBIGUOUS_ENTITY` | `409 Conflict` | Arama birden fazla varlıkla eşleşiyor; `value` aday listesidir. | `POST /tools/resolve_flight_identity`, `{"query": "TC-LSD"}` |
| `CAPABILITY_NOT_IN_SCOPE` | `404 Not Found` | `{ad}` kayıtlı bir tool değil. | `POST /tools/get_weather`, `{}` |
| `SCHEMA_VALIDATION_FAILED` | `422 Unprocessable Content` | Argüman şemaya uymuyor, gövde nesne değil, veri okunamıyor ya da veri sözleşmeye uymuyor, tool çıktısı çıktı şemasına uymuyor. | `POST /tools/get_flight_summary`, `{"direction": "ALL"}` |

- `NOT_FOUND` ile `CAPABILITY_NOT_IN_SCOPE` aynı durum kodunu (`404`) taşır; istemci ikisini `error.code`'dan ayırır, durum kodundan değil.
- Veri hatası da `SCHEMA_VALIDATION_FAILED` olduğu için `422` döner, sunucu tarafı bir sorun olsa da. Sarmalayıcı bunu argüman hatasından ayırmaz, çünkü yalnızca `error.code`'a bakar; ayrım `filters`'ta görünür (argüman hatasında `{}`, veri hatasında doğrulanmış argümanlar; `docs/tools.md` › Hata eşlemesi).
- Tablo kapalıdır: `docs/zarf.md`'ye yeni bir hata kodu eklenirse bu tabloya da satır ve testlere durum eklenmeden kod yayımlanmaz.

### Taşıma hataları

Aşağıdaki durumlarda `run_tool` çağrılmaz ve zarf **kurulmaz**; yanıt, genel bir Türkçe mesaj taşıyan `{"detail": "..."}` nesnesidir. Bunlar tool sonucu değil, taşıma hatasıdır.

| Durum | HTTP durum kodu | Yanıt gövdesi | Not |
|---|---|---|---|
| Gövde boş | `400 Bad Request` | `{"detail": "İstek gövdesi geçerli JSON değil."}` | Argümansız tool olsa bile gövde `{}` olarak gönderilir. |
| Gövde JSON olarak çözülemiyor ya da geçerli UTF-8 değil | `400 Bad Request` | `{"detail": "İstek gövdesi geçerli JSON değil."}` | Çözümleme hatasının ayrıntısı (konum, karakter) gövdeye girmez; yalnızca sunucu loguna yazılır. |
| Geçerli JSON ama nesne değil (`[1]`, `"x"`, `null`, `5`) | `422 Unprocessable Content` | `run_tool`'un döndürdüğü `SCHEMA_VALIDATION_FAILED` zarfı | Taşıma hatası değildir; gövde olduğu gibi `run_tool`'a gider ve `run_tool` reddeder. |
| Sarmalayıcının kendisinde beklenmeyen hata | `500 Internal Server Error` | `{"detail": "Beklenmeyen bir hata oluştu."}` | `run_tool` exception fırlatmaz; bu yalnızca sarmalayıcının kendi hatasıdır. Ayrıntı `logger.exception` ile loglanır. |
| Desteklenmeyen yöntem (ör. `GET /tools/get_flight_summary`) | `405 Method Not Allowed` | FastAPI'nin varsayılan gövdesi | Zarf kurulmaz. |

## Kurallar

- **Zarf birebir taşınır.** Yanıt gövdesi `run_tool`'un döndürdüğü sözlüktür: alan sırası, değerler ve `null`'lar aynen kalır. Sarmalayıcı `as_of`'u yeniden hesaplamaz, `stale`'i değiştirmez, `error.message`'ı yeniden yazmaz, `source`'u gizlemez.
- **Saat okunmaz.** Sarmalayıcı sistem saatini okumaz; `Date` gibi zaman başlıkları dışında zaman bilgisi yanıta yalnızca zarfın `as_of`'u ile girer (`docs/zarf.md` › Saat tek yerden okunur).
- **Veri okunmaz.** Sarmalayıcı `COPILOT_DATA`'yı okumaz, dosya açmaz; veri her çağrıda `run_tool` içinde okunur (`docs/tools.md` › Veri kaynağı).
- **Kodlama.** Yanıt `Content-Type: application/json; charset=utf-8` ile ve `ensure_ascii=False` ile yazılır; Türkçe karakterler kaçış dizisine dönüşmez (CLAUDE.md › Kurallar).
- **Hata ayrıntısı gitmez.** Exception metni, yığın izi, dosya yolu ayrıntısı, JSON çözümleme konumu yanıta girmez; yalnızca sunucu loguna yazılır (CLAUDE.md › Yasaklar). Zarftaki `error.message` zaten genel metindir.
- **Durumsuzluk.** Sarmalayıcı istekler arasında durum tutmaz; aynı istek, aynı veri ve aynı saatle (`COPILOT_NOW`) byte byte aynı yanıtı verir.
- **API anahtarı gerekmez.** `/tools` uç noktaları `backend.llm`'i import etmez; `/health` gibi `ANTHROPIC_*` ayarları olmadan çalışır.
- **Önbellek yok.** Yanıtlara `Cache-Control: no-store` eklenir; tool sonucu canlı veri sayılır.
- **Proxy.** Geliştirmede frontend `/tools`'a Vite proxy'si üzerinden ulaşır; uç noktalar eklenince `frontend/vite.config.ts`'deki proxy listesine `/tools` eklenir. CORS açılmaz.

## Arayüz kuralları

Frontend'in (`frontend/`) `/tools` yanıtlarını nasıl gösterdiğine dair kurallar. Amaç, agent'a konan kuralların (`docs/zarf.md` › Hata kodları) ekranda da geçerli olması: arayüz sayı/durum üretmez, yalnızca zarfı gösterir.

| Konu | Kural | Yapılmaz |
|---|---|---|
| Hata ayrımı | Ne gösterileceğine `error.code` ile karar verilir; HTTP durum kodu yalnızca "zarf geldi mi, taşıma hatası mı" ayrımı için kullanılır. `404`'te `NOT_FOUND` ile `CAPABILITY_NOT_IN_SCOPE` koddan ayrılır. | Durum koduna göre mesaj seçilmez; `404` görünce "bulunamadı" yazılmaz. |
| Hata mesajı | Zarf geldiyse `error.message` olduğu gibi gösterilir. Taşıma hatasında (`400`, `500`, ağ hatası) `detail` ya da arayüzün kendi genel Türkçe mesajı gösterilir. | Mesaj yeniden yazılmaz, yanıt gövdesi ham JSON olarak kullanıcıya basılmaz. |
| Değer | `value` olduğu gibi gösterilir. Sayılar (`total`, `cancelled`, `delayed`) servisin hesabıdır. | Arayüz toplam, oran, fark ya da tahmin hesaplamaz; `value`'da olmayan alanı başka alanlardan türetmez (ör. tahmini zamanı tarife + gecikmeden). |
| Eksik alan | `value`'da olmayan alan için "veride yok" gösterilir. | Boş alan `0`, `-` ya da varsayılan değerle doldurulmaz; alan uydurulmaz. |
| Kaynak ve zaman | Her sonuçta `source` ve `as_of` görünür. `as_of` `+03:00` saatiyle gösterilir. | `as_of` yerine tarayıcı saati gösterilmez. |
| Eski veri | `stale: true` ise değer, `as_of` ile birlikte ve verinin eski olduğunu belirten görünür bir uyarıyla gösterilir. | Eski değer güncelmiş gibi sunulmaz; konum ara değerlemeyle ilerletilmez. |
| Belirsizlik | `AMBIGUOUS_ENTITY`'de `value`'daki adayların hepsi listelenir (sefer no, callsign, tescil, tarife); kullanıcı birini seçince seçilen adayın `flight_id`'siyle `get_flight_details` çağrılır. | Adaylardan biri otomatik seçilmez; adayların değerleri birleştirilmez. |
| Bulunamadı | `NOT_FOUND`'da aranan değer `filters`'tan gösterilir. | Benzer bir kayıt önerilmez ya da gösterilmez. |
| Kapsam dışı | `CAPABILITY_NOT_IN_SCOPE`'ta işin kapsam dışı olduğu söylenir. | Başka bir tool ile sonuç taklit edilmez. |
| Şema hatası | `SCHEMA_VALIDATION_FAILED`'da isteğin şu an yanıtlanamadığı söylenir; kullanıcı girdisi düzeltilip yeniden gönderilebilir. | İstek otomatik olarak döngüde tekrarlanmaz; reddedilen yanıttan değer kullanılmaz. |
| Filtreler | `filters` sorunun nasıl anlaşıldığını göstermek için kullanılabilir. | `filters` istekteki değerle değiştirilmez. |
| Tool listesi | Tool seçimi ve form alanları `GET /tools`'taki `input_schema`'dan (zorunlu alanlar, enum'lar) kurulur. | Tool adları, enum değerleri ya da argüman alanları frontend koduna gömülmez. |

**İstisna: doğrulama sayfası.** `frontend/src/App.tsx` sözleşmeyi bilinen girdilerle sınayan bir doğrulama sayfasıdır; sorgu listesi (`frontend/src/queries.ts`) tool adlarını, argümanları ve beklenen durum kodunu bilerek gömer. Sayfa yine de `GET /tools`'u çeker ve her sorgunun tool'unun listede olup olmadığını gösterir. Diğer kurallar bu sayfada da geçerlidir. Kullanıcıya dönük ekranlar bu istisnadan yararlanmaz.

## Örnekler

Değerler `data/referans/seed42-2026-10-20.json`'dan; `COPILOT_DATA=data/referans/seed42-2026-10-20.json`, `COPILOT_NOW=2026-10-20T16:22:00+03:00`.

**1. Başarı, `200`.** `POST /tools/get_flight_summary`, gövde `{"direction": "all"}`:

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

**2. `NOT_FOUND`, `404`.** `POST /tools/resolve_flight_identity`, gövde `{"query": "ZZ9999"}`:

```json
{
  "value": null,
  "source": "data/referans/seed42-2026-10-20.json",
  "as_of": "2026-10-20T16:22:00+03:00",
  "filters": {"query": "ZZ9999"},
  "stale": false,
  "tool_version": "1.0.0",
  "error": {"code": "NOT_FOUND", "message": "Bu kimlikle uçuş bulunamadı."},
  "author": "tool"
}
```

**3. `CAPABILITY_NOT_IN_SCOPE`, `404`.** `POST /tools/get_weather`, gövde `{}`:

```json
{
  "value": null,
  "source": null,
  "as_of": null,
  "filters": {},
  "stale": false,
  "tool_version": null,
  "error": {"code": "CAPABILITY_NOT_IN_SCOPE", "message": "Bu istek copilot'un kapsamı dışında."},
  "author": "layer"
}
```

**4. `SCHEMA_VALIDATION_FAILED`, `422`.** `POST /tools/get_flight_summary`, gövde `{"direction": "ALL"}`:

```json
{
  "value": null,
  "source": null,
  "as_of": null,
  "filters": {},
  "stale": false,
  "tool_version": "1.0.0",
  "error": {"code": "SCHEMA_VALIDATION_FAILED", "message": "Tool argümanları şemaya uymuyor."},
  "author": "layer"
}
```

**5. Taşıma hatası, `400`.** `POST /tools/get_flight_summary`, gövde `{direction: all}` (geçersiz JSON):

```json
{"detail": "İstek gövdesi geçerli JSON değil."}
```
