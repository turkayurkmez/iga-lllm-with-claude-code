# Uçuş tool'ları: sözleşme

Bu belge `get_flight_summary`, `resolve_flight_identity`, `get_flight_details` ve `get_chart_data` tool'larının sözleşmesidir. Kod `backend/tools/` paketindedir (`__init__.py` giriş noktaları, `_ortak.py` ortak parçalar); sözleşme testleri koddan önce yazılır ve gevşetilmez. Tool çıktıları `docs/zarf.md`'deki ortak zarfla döner.

## Ortak kurallar

### Giriş noktaları

Modülün dışarıya açtığı yalnızca iki giriş noktası vardır:

| Giriş noktası | İmza | Ne döndürür | Kim kullanır |
|---|---|---|---|
| `run_tool` | `run_tool(name: str, args: Any) -> dict` | JSON'a yazılabilir zarf (`docs/zarf.md` › Alanlar; sekiz alanın hepsi). Hiçbir koşulda exception fırlatmaz; her sonuç zarftır. | Tool kullanım döngüsü: modelin `tool_use` bloğundaki `name` ve `input` doğrudan verilir. |
| `tool_definitions` | `tool_definitions() -> list[dict]` | Üç tool'un Anthropic tool tanımı (`name`, `description`, `input_schema`), bu belgedeki sırayla. | `messages.create(tools=...)`. |

- `run_tool`, zarfı `backend/envelope.py` › `call_tool` ile kurar. Tool zarfı kendisi kurmaz; yalnızca `{value, source, data_time?, error?}` döndürür. `as_of` ve `stale`'i katman hesaplar (`docs/zarf.md` › Tool ne döndürür).
- Tool sistem saatini kendisi okumaz. O anki zaman gerekiyorsa (yalnızca `get_flight_details` › konum seçimi) `backend/clock.py` › `operational_now()`'dan alınır; zarfın `as_of`'u da bu saattir.
- **Operasyonel saat.** Canlı mod kapalıyken `operational_now()` = `now()` (`COPILOT_NOW`, boşsa sistem saati); davranış öncekiyle aynıdır. Canlı mod açıkken (`docs/canli_akis.md` › Canlı mod ve tool'lar) ve tüketici bir `clock` mesajı almışsa simüle andır (`clock.epoch`, `+03:00`); saat mesajı henüz yoksa yine `now()`. Audit kayıtlarının zamanı `now()`'da kalır.
- `tool_definitions`'taki `input_schema`, `run_tool`'un argüman doğrulamasında kullanılan modelle aynı parametreleri, zorunlu alanları ve enum'ları tanımlar. Açıklamalar "ne döndürür / ne zaman kullanılır / ne zaman KULLANILMAZ" bölümlerini, enum değerlerini ve örnek değer içerir (CLAUDE.md › Kurallar).
- Üç tool'un `tool_version`'ı `1.0.0`'dır. Hiçbirinde tazelik eşiği (`ToolSpec.max_age`) tanımlı değildir; bu yüzden `stale` her zaman `false` olur ve `STALE_DATA` dönmez.

### Hata eşlemesi

| Durum | Kod | Yazan | Zarf |
|---|---|---|---|
| `name` üç tool'dan biri değil | `CAPABILITY_NOT_IN_SCOPE` | `layer` | Tool çağrılmaz, veri okunmaz. `value`, `source`, `as_of`, `tool_version` `null`; `filters` `{}`. |
| Argüman şemaya uymuyor (eksik zorunlu alan, ek alan, yanlış tip, enum dışı değer, nesne olmayan `args`) | `SCHEMA_VALIDATION_FAILED` | `layer` | Tool çağrılmaz, veri okunmaz. `value`, `source`, `as_of` `null`; `filters` `{}`; `tool_version` `1.0.0`. |
| Veri okunamıyor ya da veri sözleşmeye uymuyor (aşağıda › Veri kaynağı) | `SCHEMA_VALIDATION_FAILED` | `layer` | `run_tool` tool'un veri hatasını yakalar. `value`, `source`, `as_of` `null`; `filters` doğrulanmış argümanlar; `tool_version` `1.0.0`; `message` çıktı reddindekiyle aynı genel metin. Ayrıntı yalnızca sunucu loguna yazılır. |
| Tool çıktısı çıktı şemasına uymuyor | `SCHEMA_VALIDATION_FAILED` | `layer` | `call_tool`'un mevcut davranışı (`docs/zarf.md`). |
| Aranan varlık yok | `NOT_FOUND` | `tool` | Tool'a göre ayrıntı aşağıda. |
| Arama birden fazla varlıkla eşleşiyor | `AMBIGUOUS_ENTITY` | `tool` | Yalnızca `resolve_flight_identity` yazar. |

Exception metni, dosya yolu ayrıntısı, yığın izi zarfa girmez (CLAUDE.md › Yasaklar).

### Veri kaynağı

- Veri, ortam değişkeni `COPILOT_DATA`'nın gösterdiği JSON dosyasıdır (`synth.generator` ya da `synth.corruption` çıktısı; biçim `docs/spec.md` §8).
- `COPILOT_DATA` **her çağrıda** ortamdan okunur ve dosya her çağrıda yeniden açılır. Modül düzeyinde okuma, önbellek ya da import anında yükleme yoktur; değişken çalışma sırasında değişirse bir sonraki çağrı yeni dosyayı okur.
- Zarfın `source`'u `COPILOT_DATA`'nın değeridir, olduğu gibi (çözümlenmiş mutlak yol değil).
- Veri hatası sayılan durumlar: `COPILOT_DATA` tanımsız ya da boş; dosya yok ya da okunamıyor; içerik geçerli UTF-8 JSON değil; tool'un kullandığı üst anahtar (`meta`, `flights`, `movements`, `delays`, `positions`) yok; tool'un hesap için zorunlu tuttuğu bir alan kayıtta yok (tool tablolarında "zorunlu alan" olarak belirtilir).
- Hesap için zorunlu olmayan bir alanın kayıtta bulunmaması hata değildir (`docs/zarf.md` › Eksik alan hata değildir): alan `value`'ya yazılmaz.
- Kaynakta değeri `null` olan alan da `value`'ya yazılmaz (ör. iptal edilen uçuşun `stand_code`'u). `value`'da `null` değerli alan bulunmaz.
- Yetim kayıtlar (`flights`'ta karşılığı olmayan `movements`, `positions`, `delays` satırları; `docs/bozulma.md` › `undefined_flight`) hiçbir tool'da kullanılmaz: sayılmaz, aranmaz, döndürülmez.

## `get_flight_summary`

Günün uçuşlarının sayısal özeti. Hesap tamamen tool'da yapılır; model sayıyı yorumlar, yeniden hesaplamaz.

### Girdi

| Alan | Tip | Zorunlu | Değerler | Örnek | Açıklama |
|---|---|---|---|---|---|
| `direction` | metin | evet | `all`, `arrival`, `departure` | `"all"` | `all`: tüm uçuşlar; `arrival`: `movement_type` `ARRIVAL` olanlar; `departure`: `movement_type` `DEPARTURE` olanlar. Kullanıcı yön belirtmediyse model `all` verir. Büyük harfli değer (`ALL`) enum dışıdır. |

### `value`

| Alan | Tip | Kaynak / hesap | Örnek (`seed42-2026-10-20`, `all`) |
|---|---|---|---|
| `date` | metin, `YYYY-MM-DD` | `meta.date` | `"2026-10-20"` |
| `direction` | metin | Doğrulanmış `direction` argümanı | `"all"` |
| `total` | tamsayı | `flights`'ta kaydı olan ve `movements`'ta yönü eşleşen uçuşların sayısı; iptal edilenler dahil | `600` |
| `cancelled` | tamsayı | Bu uçuşlardan `cancelled` değeri `true` olanların sayısı | `4` |
| `delayed` | tamsayı | Bu uçuşlardan `delays`'te kaydı olanların sayısı (`flight_id` başına bir) | `115` |

Zorunlu alanlar (yoksa veri hatası): `meta.date`; her `flights` kaydında `flight_id` ve `cancelled`; her `movements` kaydında `flight_id` ve `movement_type`.

`data_time` verilmez; `as_of` çağrı anındaki saattir. Özet saatten bağımsızdır: günün tamamını sayar, saate göre süzmez.

### `filters`

| Alan | Değer | Örnek |
|---|---|---|
| `direction` | Doğrulanmış argüman, verildiği gibi | `{"direction": "all"}` |

### Kenar durumlar

| Durum | Sonuç | Agent ne yapar |
|---|---|---|
| `direction` verilmemiş | `SCHEMA_VALIDATION_FAILED`, `author: layer`, `filters: {}` | Argümanı `all` ile düzeltip bir kez yeniden çağırır. |
| `direction` enum dışı (`"ALL"`, `"gelen"`, `""`) | `SCHEMA_VALIDATION_FAILED`, `author: layer`, `filters: {}` | Enum'daki değerle bir kez yeniden çağırır. |
| Ek argüman (ör. `{"direction": "all", "airline": "TK"}`) | `SCHEMA_VALIDATION_FAILED`, `author: layer`, `filters: {}` | Kırılımın desteklenmediğini söyler; ek alanı atıp yalnızca istenirse bir kez yeniden çağırır. |
| Yöne uyan hiç uçuş yok | Hata değil; `total`, `cancelled`, `delayed` `0`, `error: null` | Sıfırı kaynağıyla verir; sayı uydurmaz. |
| İptal edilen uçuş | `total`'e ve `cancelled`'a girer; `delayed`'e girmez (iptalde gecikme kaydı yoktur, `docs/spec.md` §7) | Toplamın iptalleri içerdiğini belirtebilir; `total − cancelled` gibi bir hesabı kendisi yapmaz. |
| `undefined_flight` uygulanmış veri (yetim `movements`/`delays`) | Yetim kayıtlar sayılmaz; `total` ve `delayed` bir eksik çıkar | Verilen sayıyı kullanır; yetim kayıtları kendisi sayıya eklemez. |
| `duplicate_callsign` uygulanmış veri | Etkisi yok; sayım `flight_id` üzerinden yapılır | Normal yanıt verir. |
| `missing_field`: bir uçuşta `flights.cancelled` ya da `movements.movement_type` yok | Veri hatası: `SCHEMA_VALIDATION_FAILED`, `author: layer`, `value: null`, `filters` doğrulanmış argüman | İsteğin şu an yanıtlanamadığını söyler; kısmi sayı vermez, yeniden denemez. |
| `missing_field`: sayımda kullanılmayan bir alan yok (ör. `flights.estimated_time`) | Etkisi yok | Normal yanıt verir. |
| `COPILOT_DATA` tanımsız, boş, dosya yok ya da JSON bozuk | Veri hatası: `SCHEMA_VALIDATION_FAILED`, `author: layer`, `source: null` | İsteğin şu an yanıtlanamadığını söyler; yeniden denemez. |
| Model tek bir sefer hakkında bu tool'u çağırıyor | Tool sefer argümanı almaz; ek argüman verilirse `SCHEMA_VALIDATION_FAILED` | `resolve_flight_identity` ve `get_flight_details` kullanır. |

## `resolve_flight_identity`

Kullanıcının verdiği kimliği (sefer no, callsign ya da tescil) uçuş kaydına çevirir. `get_flight_details`'e verilecek `flight_id`'yi bulmanın tek yolu budur; belirsizliği bu tool ortaya çıkarır.

### Girdi

| Alan | Tip | Zorunlu | Değerler | Örnek | Açıklama |
|---|---|---|---|---|---|
| `query` | metin | evet | Boşluk kırpıldıktan sonra en az 1 karakter | `"THY2345"` | Sefer no (`TK2345`), callsign (`THY2345`) ya da tescil (`TC-LSD`). Model kimliğin türünü belirtmez; tool üç alanda da arar. |

**Eşleşme kuralı.** `query`'nin başındaki ve sonundaki boşluk kırpılır, büyük/küçük harf farkı yok sayılır; `flights` kayıtlarının `flight_no`, `callsign` ve `registration` alanlarıyla **tam eşitlik** aranır. Tek istisna sayı kısmındaki baştaki sıfırlardır: harf öneki + rakamlardan oluşan değerlerde (`flight_no`, `callsign`) rakamların başındaki sıfırlar hem sorguda hem kayıtta yok sayılır, en az bir rakam kalır (`THY15` = `THY0015`, `TK02344` = `TK2344`). `registration`'a uygulanmaz. Bunun dışında kısmi eşleşme, önek araması, benzerlik ya da yazım düzeltmesi yapılmaz (`TK234`, `15`, `THY` hiçbir şeyle eşleşmez). Yalnızca `flights` kayıtları aranır.

### `value`

Eşleşme sayısına göre üç biçimi vardır:

| Eşleşme | `value` | `error` |
|---|---|---|
| 0 | `null` | `NOT_FOUND`, "Bu kimlikle uçuş bulunamadı." |
| 1 | Aday nesnesi | `null` |
| 2 ve üzeri | Aday nesnelerinin listesi, `flight_id`'ye göre artan | `AMBIGUOUS_ENTITY`, "Bu kimlik birden fazla uçuşla eşleşiyor." |

Aday nesnesi:

| Alan | Tip | Kaynak | Örnek (`THY2345`) |
|---|---|---|---|
| `flight_id` | metin | `flights.flight_id` | `"FL-20261020-0270"` |
| `flight_no` | metin | `flights.flight_no` | `"TK2345"` |
| `callsign` | metin | `flights.callsign` | `"THY2345"` |
| `registration` | metin | `flights.registration` | `"TC-LSD"` |
| `movement_type` | metin, `ARRIVAL`/`DEPARTURE` | `movements.movement_type` | `"DEPARTURE"` |
| `scheduled_time` | ISO 8601, `+03:00` | `flights.scheduled_time` | `"2026-10-20T15:40:00+03:00"` |
| `matched_on` | metin, `flight_no`/`callsign`/`registration` | Eşleşen alan. Aynı kayıt birden fazla alanda eşleşirse öncelik `flight_no` > `callsign` > `registration` | `"callsign"` |

Zorunlu alanlar (yoksa veri hatası): her `flights` kaydında `flight_id`. `flight_no`, `callsign`, `registration`, `scheduled_time` ya da `movement_type` bir kayıtta yoksa o kayıt o alanda aranmaz ve aday nesnesine o alan yazılmaz.

`data_time` verilmez; `as_of` çağrı anındaki saattir.

### `filters`

| Alan | Değer | Örnek |
|---|---|---|
| `query` | Doğrulanmış argüman, modelin verdiği haliyle (kırpma ve harf dönüşümü yalnızca eşleşmede uygulanır) | `{"query": "THY2345"}` |

### Kenar durumlar

| Durum | Sonuç | Agent ne yapar |
|---|---|---|
| `query` verilmemiş, boş ya da yalnızca boşluk | `SCHEMA_VALIDATION_FAILED`, `author: layer`, `filters: {}` | Kullanıcıdan sefer no, callsign ya da tescil ister; uydurmaz. |
| `query` metin değil (ör. `2345`) | `SCHEMA_VALIDATION_FAILED`, `author: layer`, `filters: {}` | Değeri metin olarak bir kez yeniden gönderir. |
| `ZZ9999` (`docs/spec.md` §9) | `NOT_FOUND`, `value: null`, `author: tool` | Kaydın bulunamadığını `filters.query` ile söyler; benzer bir sefer önermez. |
| Kısmi değer (`TK234`, `2345`) | `NOT_FOUND` | Tam sefer no, callsign ya da tescil ister. |
| Küçük harf ya da boşluklu değer (`" thy2345 "`) | Tek eşleşme, `matched_on: "callsign"`; `filters.query` `" thy2345 "` | Normal yanıt verir. |
| Sayıda baştaki sıfır (`"THY02345"`, `"TK02344"`; kayıtta `TK0015` iken `"tk15"`) | Sıfırlar yok sayılır; tek eşleşme, `filters.query` verildiği haliyle | Normal yanıt verir. |
| Tescil ile arama (`TC-LSD`) | Uçağın günlük arrival/departure çifti nedeniyle genellikle 2+ eşleşme: `FL-20261020-0269` (`TK2344`) ve `FL-20261020-0270` (`TK2345`); `AMBIGUOUS_ENTITY` | Adayların hepsini sefer no, yön ve tarifeyle listeler; hangisinin sorulduğunu sorar. Birini kendisi seçmez. |
| `duplicate_callsign` uygulanmış veride callsign ile arama | 2 eşleşme, `AMBIGUOUS_ENTITY` | Adayları sefer no, tescil ve tarifeyle listeler; sefer no ya da tescille netleştirme ister. |
| `duplicate_callsign` uygulanmış veride sefer no ile arama | Tek eşleşme | Normal yanıt verir. |
| `undefined_flight` uygulanmış veride hedefin sefer no'su ya da callsign'ı | `NOT_FOUND`; yetim kayıtlara bakılmaz | Kaydın bulunamadığını söyler; yetim kayıtlardan bilgi kurmaz. |
| İptal edilen uçuş | Normal aday olarak döner (iptal durumu adayda yoktur) | İptal durumunu `get_flight_details` ile öğrenir. |
| `missing_field`: kayıtta `flights.callsign` yok | O kayıt callsign ile bulunamaz; sefer no ve tescille bulunur, adayda `callsign` alanı yoktur | Bulunamadıysa `NOT_FOUND` olarak söyler; callsign'ı sefer no'dan türetmez. |
| `COPILOT_DATA` tanımsız, boş, dosya yok ya da JSON bozuk | Veri hatası: `SCHEMA_VALIDATION_FAILED`, `author: layer`, `source: null` | İsteğin şu an yanıtlanamadığını söyler; yeniden denemez. |

## `get_flight_details`

Tek bir uçuşun kaydını, hareketini, gecikmesini ve son konumunu döndürür. Uçuşu `flight_id` ile alır; `flight_id` `resolve_flight_identity`'den gelir, bu yüzden bu tool belirsizlik üretmez.

### Girdi

| Alan | Tip | Zorunlu | Değerler | Örnek | Açıklama |
|---|---|---|---|---|---|
| `flight_id` | metin | evet | `FL-YYYYMMDD-NNNN` biçimi (`docs/spec.md` §6), büyük harfle, tam eşitlik | `"FL-20261020-0270"` | `resolve_flight_identity` sonucundaki `flight_id`. Sefer no, callsign ya da tescil değildir. |

### `value`

| Alan | Tip | Kaynak | Örnek (`FL-20261020-0270`, saat 16:22) |
|---|---|---|---|
| `flight_id` | metin | `flights.flight_id` | `"FL-20261020-0270"` |
| `flight_no` | metin | `flights.flight_no` | `"TK2345"` |
| `callsign` | metin | `flights.callsign` | `"THY2345"` |
| `registration` | metin | `flights.registration` | `"TC-LSD"` |
| `aircraft_type` | metin | `flights.aircraft_type` | `"A321"` |
| `origin` | metin | `flights.origin` | `"XXXX"` |
| `destination` | metin | `flights.destination` | `"VAN"` |
| `scheduled_time` | ISO 8601, `+03:00` | `flights.scheduled_time` | `"2026-10-20T15:40:00+03:00"` |
| `estimated_time` | ISO 8601, `+03:00` | `flights.estimated_time` | `"2026-10-20T16:05:00+03:00"` |
| `cancelled` | boolean | `flights.cancelled` | `false` |
| `movement_type` | metin, `ARRIVAL`/`DEPARTURE` | `movements.movement_type` | `"DEPARTURE"` |
| `stand_code` | metin | `movements.stand_code` | `"R236"` |
| `gate_code` | metin | `movements.gate_code` | `"BUS4"` |
| `actual_runway_time` | ISO 8601, `+03:00` | `movements.actual_runway_time` | `"2026-10-20T16:09:00+03:00"` |
| `actual_block_time` | ISO 8601, `+03:00` | `movements.actual_block_time` | `"2026-10-20T16:02:00+03:00"` |
| `delay_minutes` | tamsayı | `delays.delay_minutes` | `25` |
| `delay_code` | metin | `delays.delay_code` | `"82"` |
| `delay_category` | metin | `delays.category` (ad çakışmasın diye önekli) | `"ATC_RESTRICTION"` |
| `position` | nesne | `positions`'ta bu uçuşun `ts`'si `clock.operational_now()`'a eşit ya da ondan önce olan kayıtları arasında `ts`'si en büyük olanı; alanları `ts`, `lat`, `lon`, `heading_deg`, `speed_kt`, `phase`. Canlı modda kaynak canlı depodur (aşağıda › Canlı mod) | `{"ts": "2026-10-20T16:22:00+03:00", "lat": 41.05, "lon": 28.4, "heading_deg": 235.0, "speed_kt": 280.0, "phase": "CLIMB"}` |

- `flights.status` döndürülmez (üreteçten gelmez, `docs/spec.md` §6).
- Kaynakta olmayan ya da `null` olan her alan `value`'ya yazılmaz; `position` nesnesinin alanları için de aynı kural geçerlidir. Gecikmesi olmayan uçuşta `delay_*` alanları, konumu olmayan uçuşta `position` yoktur.
- `ts` karşılaştırması metinle değil zaman damgasıyla yapılır.
- Zorunlu alanlar (yoksa veri hatası): her `flights`, `movements`, `delays`, `positions` kaydında `flight_id`; seçilen uçuşun her `positions` kaydında `ts`.

**Canlı mod.** Canlı mod açıkken `position` dosyadaki `positions` tablosundan değil canlı depodan (`docs/canli_akis.md` › Depo) gelir. Diğer alanlar ve veri hataları değişmez; `positions` tablosu yine okunur ve doğrulanır, ama konum için kullanılmaz.

- **Aday kayıtlar:** depoda görünür olan, `Flight` = uçuşun `flight_no`'su ve `LastUpdate` ≤ `operational_now()` olan kayıtlar. Aralarından `LastUpdate`'i en büyük olan seçilir.
- **Alan eşlemesi:**

  | `position` alanı | Canlı kayıttaki karşılığı |
  |---|---|
  | `ts` | `LastUpdate` (ISO 8601, `+03:00`) |
  | `lat` | `Latitude` |
  | `lon` | `Longitude` |
  | `heading_deg` | `Track` |
  | `speed_kt` | `Speed` |

- `phase` canlı kayıtta yoktur, yazılmaz. Kayıtta olmayan alan da yazılmaz.
- Eşleşen canlı kayıt yoksa `position` yazılmaz; dosyaya geri düşülmez.
- Kontrat ve `tool_version` değişmez.

`data_time` verilmez; `as_of` çağrı anındaki saattir. Konumun ait olduğu an `position.ts`'dedir ve `as_of`'tan farklı olabilir. Konumun tazeliği bu tool'da denetlenmez (`stale: false`); tazelik eşikli konum sorgusu ayrı bir tool'un (`get_flight_position`, `docs/zarf.md` › Örnekler) işidir.

### `filters`

| Alan | Değer | Örnek |
|---|---|---|
| `flight_id` | Doğrulanmış argüman, verildiği gibi | `{"flight_id": "FL-20261020-0270"}` |

### Kenar durumlar

| Durum | Sonuç | Agent ne yapar |
|---|---|---|
| `flight_id` verilmemiş ya da biçime uymuyor (`"TK2345"`, `"fl-20261020-0270"`, `""`) | `SCHEMA_VALIDATION_FAILED`, `author: layer`, `filters: {}` | Önce `resolve_flight_identity` ile `flight_id`'yi bulur; sefer no'yu `flight_id` diye göndermez. |
| Biçime uyan ama `flights`'ta olmayan `flight_id` | `NOT_FOUND`, "Bu kimlikle uçuş bulunamadı.", `value: null`, `author: tool` | Kaydın bulunamadığını söyler; `flight_id`'yi kendisi tahmin edip yeniden denemez. |
| `undefined_flight` uygulanmış veride hedefin `flight_id`'si | `NOT_FOUND`; yetim `movements`, `positions`, `delays` kullanılmaz | Kaydın bulunamadığını söyler; uygunsa veri tutarsızlığını belirtir; yetim kayıtlardan bilgi kurmaz. |
| İptal edilen uçuş | `cancelled: true`; `movement_type` vardır; `stand_code`, `gate_code`, `actual_*`, `delay_*`, `position` yoktur (kaynakta `null` ya da kayıt yok) | Uçuşun iptal olduğunu söyler; stand, gate ya da konum uydurmaz. |
| Gecikmesiz uçuş | `delay_*` alanları yok; `estimated_time` `scheduled_time`'a eşit | Gecikme olmadığını söyler. |
| Konum izi henüz başlamamış (tüm `ts` değerleri `clock.operational_now()`'dan sonra) | `position` yok | Konum verisi olmadığını söyler; gelecekteki iz noktasını vermez. |
| Konum izi bitmiş (inmiş, ya da kalkıp izden çıkmış uçuş) | `position` izin son noktasıdır; `position.ts` `as_of`'tan eski olabilir | Konumu `position.ts` zaman damgasıyla verir; güncelmiş gibi sunmaz. |
| `stale_position` uygulanmış veri | `position` kalan son noktadır (10 dakika eski); `stale: false`, `error: null` | Konumu `position.ts` ile verir ve `as_of`'tan eski olduğunu söyler; ara değerleme yapmaz, block zamanından konum çıkarmaz. |
| `movements`'ta saatten sonraki `actual_*` zamanı | Kaynaktaki haliyle döner; tool `actual_*` alanlarını saate göre süzmez | Alanı kaynaktaki değeriyle verir; durumu (`ACTIVE`/`COMPLETED`) kendisi türetmez. |
| `missing_field`: `flights.estimated_time` yok | `estimated_time` alanı yok; `delay_minutes` durur | Tahmini zamanın veride bulunmadığını söyler; tarife + gecikmeden hesaplamaz. |
| `missing_field`: `movements.*` ya da `delays.*` alanı yok | O alan `value`'da yok; diğer alanlar durur | Alanın veride bulunmadığını söyler; diğer alanlarla yanıt verir. |
| `duplicate_callsign` uygulanmış veri | Etkisi yok; arama `flight_id` ile yapılır | Normal yanıt verir. |
| `COPILOT_DATA` tanımsız, boş, dosya yok ya da JSON bozuk | Veri hatası: `SCHEMA_VALIDATION_FAILED`, `author: layer`, `source: null` | İsteğin şu an yanıtlanamadığını söyler; yeniden denemez. |

## `get_chart_data`

Uçuş listesi üzerinde genel grafik sorgusu. Sohbette "…grafiğe dök" türü isteklerin tek tool'udur (kontrat `2.0.0`: `backend/tools/contracts/get_chart_data.json`; testleri `tests/test_chart.py`, `tests/test_chart_fields.py`, `tests/test_chart_query.py`). Model grafiğin **tarifini** verir (tür, gruplama, ölçü, süzgeç, değişim); noktaları tool hesaplar. Model seri yazmaz, toplam ya da yüzde çıkarmaz (CLAUDE.md › Yasaklar). Zarftan `chart_card` olayı kurulur (`docs/chat.md`).

### Düz uçuş görünümü

Her uçuş için tek satır (`backend/tools/chart_fields.py` › `FIELDS`, `build_rows`): `flights` + `movements` (`flight_id` ile; hareketi olmayan uçuş kapsam dışı) + `delays` (`flight_id`) + `aircraft` (`registration`) + `stands` (`movements.stand_code`). Yetim kayıtlar kullanılmaz. Kaynakta değeri olmayan (`null`/boş) alan satırda **hiç yoktur**; o alana göre gruplamada uçuş `unclassified` sayılır.

| Tür | Alanlar |
|---|---|
| Kategorik (gruplanır, süzülür) | `airline` (sefer no'nun ilk iki karakteri, büyük harf; ad üretilmez), `flight_no`, `callsign`, `registration`, `aircraft_type`, `origin`, `destination` (IATA kod; yerel havalimanı `XXXX`), `code_letter`, `operator_iata`, `movement_type` (`ARRIVAL`/`DEPARTURE`), `stand_code`, `gate_code`, `stand_type`, `max_code_letter`, `delay_code`, `delay_category`, `cancelled` (`"true"`/`"false"`), `status` (`cancelled`, `delayed`, `on_time`) |
| Zaman (kovalanır, süzülür) | `scheduled_time`, `estimated_time`, `actual_runway_time`, `actual_block_time` |
| Sayısal (toplanır, süzülür) | `delay_minutes` |

Kontrattaki alan enum'ları `FIELDS` ile birebir aynıdır (testle denetlenir).

### Girdi

| Alan | Zorunlu | Değerler | Varsayılan |
|---|---|---|---|
| `chart_type` | evet | `bar_horizontal`, `bar_vertical`, `stacked_bar`, `grouped_bar`, `pie`, `doughnut`, `line`, `area`, `heatmap` | — |
| `group_by` | evet | `{"field": <kategorik ya da zaman alanı>, "bucket": "hour"\|"half_hour"}`; zaman alanı `bucket` ister, diğerleri almaz | — |
| `series_by` | hayır | `group_by` ile aynı biçim, farklı alan | yok |
| `measure` | hayır | `{"agg": "count"\|"sum"\|"avg"\|"min"\|"max", "field": "delay_minutes"}`; `count`'ta `field` yok | `{"agg": "count"}` |
| `filters` | hayır | `[{"field": <alan>, "op": "eq"\|"ne"\|"in"\|"gt"\|"ge"\|"lt"\|"le", "value": ...}]` (VE) | `[]` |
| `sort` | hayır | `value_desc`, `value_asc`, `label` | `value_desc` |
| `limit` | hayır | `5`, `10`, `20`, `50` | `10` |
| `derive` | hayır | `"pct_change_vs_previous"` (yalnızca zaman kovasıyla) | yok |
| `plot` | hayır | `"value"`, `"change_pct"` | `"value"` |

- `chart_type` kullanıcıdan gelir. Belirtmediyse model tool'u çağırmadan türü sorar; kural tool açıklamasındadır, talimat metni değişmedi.
- **Süzgeç değerleri.** Zaman alanlarında ISO 8601 zaman (saat dilimi zorunlu, kronolojik karşılaştırma) ya da tarihsiz `"HH:MM"` (kaydın yerel saat bölümüyle, tarihe bakmadan). `gt`/`ge`/`lt`/`le` yalnızca sayısal ve zaman alanlarında. `in` en çok 20 öğeli, boş olmayan dizi. `cancelled` için `true`/`false` ya da `"true"`/`"false"`. Alanı satırda olmayan uçuş hiçbir koşulu sağlamaz (`ne` dahil).
- **Ölçü.** `count` bütün süzgeçli uçuşları sayar. `sum`/`avg`/`min`/`max` yalnızca `delay_minutes` değeri olan (gecikme kaydı olan) uçuşları kullanır; hiç değeri olmayan grup `items`'ta yer almaz. `avg` bir ondalığa yuvarlanır (tek yuvarlama noktası).
- **Sıra ve kesme.** Zaman kovası: saat artan sırayla, `sort`/`limit` yok sayılır. `status`: `cancelled`, `delayed`, `on_time`. Diğerleri: `sort`, sonra `limit`; `groups_total` kesilmeden önceki grup sayısıdır. `series_by` varsa en büyük 8 seri kalır (değere göre, eşitlikte etiket), kalan sayısı `series_truncated`'dır.
- **Zaman kovası etiketi.** `hour` → `"14:00"`; `half_hour` → `"14:00"`/`"14:30"`.
- **Değişim (`derive`).** Her satır için aynı seride hemen önceki kova varsa ve değeri sıfırdan büyükse `change_pct = round((bu − önceki) / önceki × 100, 1)` ve `trend` (`up`/`down`/`flat`, ham değerlerle) eklenir. Önceki kova yoksa (ilk kova, uçuşsuz saat, süzgeç dışı saat) ya da sıfırsa iki alan **yazılmaz**: sıfıra bölme, sonsuz ya da uydurma yüzde olmaz. `plot: "change_pct"` grafiğin bunu çizmesini sağlar.
- **Geçerlilik** (şemanın anlatamadığı kurallar, `chart_query.check_query`; ihlal `SCHEMA_VALIDATION_FAILED`, author `layer`, veri okunmaz): `line`/`area` zaman kovasıyla; `stacked_bar`/`grouped_bar`/`heatmap` `series_by` ister; `pie`/`doughnut` ile `series_by` olmaz; `series_by` ≠ `group_by`; `bucket` yalnızca zaman alanıyla; `sum`/`avg`/`min`/`max` sayısal alan ister; `derive` zaman kovasıyla; `plot: "change_pct"` `derive` ister ve yalnızca `bar_horizontal`, `bar_vertical`, `grouped_bar`, `line`, `area` ile; hücre sınırı: `series_by` varsa (grup üst sınırı × 8) ≤ 200 (`hour` 24, `half_hour` 48, `status` 3, diğerleri `limit`).
- Süzgeç hiçbir uçuşu bırakmazsa hata değildir: `flights` 0, `items` boş.

### `value`

`date`, `chart_type`, `group_by`, `series_by?`, `measure`, `derive?`, `plot` (doğrulanmış argümanlar), `flights` (süzgeçten geçen uçuş), `groups_total`, `unclassified`, `series_truncated?` (yalnızca `series_by` varken) ve `items`: düz satırlar `{"label", "series"?, "value", "change_pct"?, "trend"?}`, grup sırasıyla, grup içinde seri sırasıyla.

Örnekler (`seed42-2026-10-20`):

- `{"chart_type": "pie", "group_by": {"field": "movement_type"}}` → `ARRIVAL` 300, `DEPARTURE` 300.
- `{"chart_type": "bar_horizontal", "group_by": {"field": "airline"}, "filters": [{"field": "movement_type", "op": "eq", "value": "ARRIVAL"}]}` → `flights` 300; `TK` 154, `AJ` 34, `QR` 25, `PC` 23, `AF` 15, `KL` 13, `LX` 13, `BA` 10, `LH` 7, `EK` 6.
- "Gelen-giden uçuşların 18:00'deki sayısının 17:00'ye göre değişimi (ok ve % ile yatay çubuk)": `group_by` `scheduled_time` + `hour`, `series_by` `movement_type`, `filters` `scheduled_time ge "17:00"` ve `lt "19:00"`, `derive` `pct_change_vs_previous`, `plot` `change_pct`, `bar_horizontal` → dört satır (17:00 ve 18:00 × iki seri); 17:00 satırlarında `change_pct`/`trend` yok, 18:00 satırlarında var.

## Örnek akış

Soru: "THY2345 hangi stand'da?" (`COPILOT_DATA=data/referans/seed42-2026-10-20.json`, `COPILOT_NOW=2026-10-20T16:22:00+03:00`)

1. `run_tool("resolve_flight_identity", {"query": "THY2345"})` → tek aday, `flight_id` `FL-20261020-0270`, `matched_on: "callsign"`.
2. `run_tool("get_flight_details", {"flight_id": "FL-20261020-0270"})` → `stand_code` `R236`, `gate_code` `BUS4`.
3. Agent: "TK2345'e (THY2345) atanan stand R236, gate BUS4. Kayda göre uçak 16:02'de stand'dan ayrılmış, 16:09'da kalkmış. Kaynak: data/referans/seed42-2026-10-20.json, 16:22 itibarıyla." (`actual_block_time` ve `actual_runway_time` kayıttan okunur; agent stand'da olduğunu söylemez.)

Soru tescille gelseydi (`TC-LSD`), 1. adım `AMBIGUOUS_ENTITY` ile `TK2344` ve `TK2345`'i döndürür; agent hangisinin sorulduğunu sorar ve 2. adıma geçmez.
