# Canlı konum akışı: sözleşme

Bu belge, simüle konum verisinin **yayıncı → broker → tüketici → SSE → ekran** hattıyla operatör ekranına canlı gibi akmasının sözleşmesidir. Hedef, gerçek radar beslemesi (FR24 biçimi, `docs/sim-flight-radar.json`) geldiğinde hattın yalnızca yayıncısının değişmesidir: mesaj biçimi gerçek veriyle aynıdır.

Bu belge sözleşmedir. Broker (`broker/compose.yaml`, `broker/mosquitto.conf`), istemci kütüphanesi (`paho-mqtt==2.1.0`, `requirements.txt`) ve referans veri (`data/referans/seed42-2026-10-20-radar.json`) hazırdır; yayıncı, tüketici, SSE endpoint'i ve ekran ayrı işte yazılır, testleri koddan önce yazılır.

```
data/referans/…-radar.json
        │  python -m stream.publisher --from HH:MM --speed 60
        ▼
 [ yayıncı ] ──MQTT 3.1.1──▶ [ Mosquitto :1883 ] ──MQTT──▶ [ tüketici (backend) ]
                                  aocc/sim/v1/#                    │ son konum + bayatlık
                                                                   ▼
                                               GET /live/positions (SSE)
                                                                   ▼
                                                     [ ekran /canli (Vite) ]
```

## Veri

### Kaynak dosya

`data/referans/seed42-2026-10-20-radar.json`, `data/referans/seed42-2026-10-20.json`'ın gerçek veri biçimlerine çevrilmiş halidir. Tek seferlik üretilmiştir (kullanıcı onayıyla, elle düzeltme yasağının istisnası); dönüştürücü repoda değildir. Kaynak dosya değişmez; yeni dosya elle düzeltilmez.

```json
{"meta": {"seed": 42, "date": "2026-10-20", "generator_version": "1.0.0",
          "source": "data/referans/seed42-2026-10-20.json", "format": "radar"},
 "flights": [ … 600 uçuş kaydı, definitions biçimi … ],
 "positions": [ … 24436 konum kaydı, radar biçimi, (LastUpdate, uçuş) sırasıyla … ]}
```

Ortak kurallar:

- **Kaynakta olmayan alan yazılmaz.** Sentetik veride karşılığı olmayan alan (ör. `Altitude`, `pax`) kayıtta hiç bulunmaz; `null` ya da uydurma değer yazılmaz (`docs/zarf.md` › Eksik alan hata değildir).
- **Yerel havalimanı kodu `IST`'tir.** Sentetik verideki `XXXX` (`docs/spec.md` §6) `IST`'e çevrilir; diğer kodlar aynen kalır.
- Zamanlar `+03:00` yerel saattir. Radar kaydında Unix epoch saniyesi (`LastUpdate`), uçuş kaydında `_date` (`YYYY-MM-DD`) + `_time` (`HH:MM`) çifti olarak yazılır.
- Sabit kayıtlar (§9) korunur: `TK2344`/`TK2345`, `TC-LSD`, `THY2345`; `TK2345`'in son konumu 16:22'dir (`LastUpdate` `1792502520`).

### Konum kaydı (`positions[]`, radar biçimi)

Alan adları ve sırası `docs/sim-flight-detail.json`'dandır. Radar anlık görüntüsündeki (`docs/sim-flight-radar.json` › `d`) konumsal dizinin elemanları aynı sıradadır; `Key` sözlük anahtarıdır.

| Alan | Tip | Kaynak (`seed42`) | Örnek (`TK2345`, 16:22) |
|---|---|---|---|
| `Key` | metin, 8 hex | `sha256(flight_id)`'nin ilk 8 karakteri; uçuş boyunca sabit, uçuşlar arasında tekil | `"dc110c28"` |
| `Latitude` | sayı | `positions.lat` | `41.05` |
| `Longitude` | sayı | `positions.lon` | `28.4` |
| `Track` | sayı, derece | `positions.heading_deg`; tam sayıysa tamsayı | `235` |
| `Speed` | sayı, knot | `positions.speed_kt`; tam sayıysa tamsayı | `280` |
| `Type` | metin, ICAO tip | `flights.aircraft_type` | `"A321"` |
| `Registration` | metin, tireli | `flights.registration` | `"TC-LSD"` |
| `LastUpdate` | tamsayı, epoch sn | `positions.ts` | `1792502520` |
| `Origin` | metin, IATA | `flights.origin` (`XXXX` → `IST`) | `"IST"` |
| `Destination` | metin, IATA | `flights.destination` (`XXXX` → `IST`) | `"VAN"` |
| `Flight` | metin | `flights.flight_no` | `"TK2345"` |
| `Onground` | mantıksal | `positions.phase` ∈ {`TAXI_IN`, `AT_STAND`, `TAXI_OUT`} | `false` |
| `Callsign` | metin | `flights.callsign` | `"THY2345"` |

Yazılmayan radar alanları (sentetik karşılığı yok): `_id`, `AircraftId`, `Altitude`, `Squawk`, `RadarId`, `Vspeed`, `SourceType`, `ETA`. `positions.phase` radar biçiminde olmadığı için yazılmaz; yalnızca `Onground` ondan türer.

### Uçuş kaydı (`flights[]`, AODB biçimi)

Alan adları `docs/definitions.json`'dandır; anahtarlar örnekteki gibi alfabetik sıradadır.

| Alan | Kaynak (`seed42`) | Örnek (`TK2345`) |
|---|---|---|
| `_id` | `<harf önek>_<rakamlar>_<YYYYMMDD>_<flight_nature>` | `"TK_2345_20261020_DEPARTURE"` |
| `airline_iata` | `flight_no`'nun harf öneki | `"TK"` |
| `atad_date`, `atad_time` | `movements.actual_runway_time` | `"2026-10-20"`, `"16:09"` |
| `bay` | `movements.stand_code` | `"R236"` |
| `callsign` | `flights.callsign` | `"THY2345"` |
| `cancelled` | Yalnızca iptal edilen uçuşta, `true`. **Sentetik ek alan**: iptalin `op_status` kodu bilinmiyor (bkz. Açık sorular). | — |
| `dest_iata`, `origin_iata` | `flights.destination` / `origin` (`XXXX` → `IST`) | `"VAN"`, `"IST"` |
| `etad_date`, `etad_time` | `flights.estimated_time` | `"16:05"` |
| `flight_nature` | `movements.movement_type` | `"DEPARTURE"` |
| `flight_number` | `flights.flight_no` | `"TK2345"` |
| `in_block_date`, `in_block_time` | `movements.actual_block_time`, **yalnızca ARRIVAL'da** | — |
| `linked_flight_number`, `linked_flight_sto_date`, `linked_flight_sto_time` | Aynı uçağın günlük çifti (ardışık `flight_id`, `docs/spec.md` §7) | `"TK2344"`, `"13:05"` |
| `op_status` | İptal edilmeyen uçuşta `"OP"`; iptalde yazılmaz | `"OP"` |
| `registration` | `flights.registration`, tiresiz | `"TCLSD"` |
| `reporting_date` | `meta.date` | `"2026-10-20"` |
| `sto_date`, `sto_time` | `flights.scheduled_time` | `"15:40"` |
| `total_delay` | `delays.delay_minutes`, yalnızca gecikmeli uçuşta | `25` |
| `unique_flight_id` | `flights.flight_id` | `"FL-20261020-0270"` |

Yazılmayan alanlar: `abs_taxitime`, `airline_name`, `body_type`, `dest_city`, `origin_city`, `ground_services`, `int_status`, `otp`, `pax`, `pax_capacity`, `route_duration`, `runway`, `service_type`. Sentetik veride olup bu biçimde karşılığı olmayanlar: `gate_code` ve `aircraft_type` (tip konum kaydında `Type` olarak vardır).

## Broker

| Konu | Karar |
|---|---|
| Ürün | Eclipse Mosquitto `2.0.20`, Docker. |
| Dosyalar | `broker/compose.yaml` (proje adı `aocc-broker`, tek servis `mosquitto`) ve aynı klasörde `broker/mosquitto.conf` (salt okunur bağlanır). Kök `docker-compose.yml`'dan (`db`, `backend`) ayrıdır; birbirini başlatmaz. Konteyner açılışında `chown: … Read-only file system` uyarısı beklenir, zararsızdır. |
| Protokol | MQTT 3.1.1, TCP `1883`. WebSocket yok: tarayıcı broker'a bağlanmaz, SSE'yi backend verir. |
| İstemci | Python'da `paho-mqtt` 2.1.0, `CallbackAPIVersion.VERSION2`. |
| Erişim | `127.0.0.1:1883` (host). İki compose projesi ayrı ağdadır; konteynerdeki backend broker'a `host.docker.internal:1883` ile ulaşır. Anonim erişim açık; **yalnızca yerel geliştirme** içindir. Ortak bir ortama çıkmadan önce parola dosyası ve TLS gerekir. |
| Kalıcılık | Kapalı (`persistence false`), volume yok. Broker yeniden başlayınca retained mesajlar silinir; veri seti değiştirilirken temiz başlangıç `restart`'tır. |
| Sağlık | `mosquitto_sub -t '$SYS/broker/uptime' -C 1 -W 3`; compose `healthy` gösterir. |

Komutlar repo kökünden:

```powershell
docker compose -f broker/compose.yaml up -d
docker compose -f broker/compose.yaml exec -T mosquitto mosquitto_sub -h localhost -t 'aocc/sim/v1/#' -v   # akışı izle
docker compose -f broker/compose.yaml restart   # retained mesajları sıfırla
docker compose -f broker/compose.yaml down
```

## Topic'ler

Kök `aocc/sim/v1/`. `sim` simüle kaynağı, `v1` mesaj sözleşmesinin sürümüdür; gerçek besleme `aocc/live/v1/` kökünü kullanır, tüketici kökü ayardan alır. Topic'ler yalnızca yayıncının yazdığı yerlerdir; tüketici hiçbir topic'e yazmaz.

| Topic | Mesaj | QoS | Retained | Ne zaman |
|---|---|---|---|---|
| `aocc/sim/v1/status` | Durum | 1 | evet | Bağlanınca `yayinda`, akış bitince `bitti`; beklenmedik kopuşta broker LWT ile `koptu` yazar. |
| `aocc/sim/v1/clock` | Saat | 0 | evet | Simüle saatin her 30 saniyesinde bir; konum olsa da olmasa da. |
| `aocc/sim/v1/flights/<_id>` | Uçuş kaydı | 1 | evet | Akış başında bir kez, her uçuş için. |
| `aocc/sim/v1/positions/<Key>` | Konum kaydı | 0 | evet | Kaydın `LastUpdate`'i simüle saate geldiğinde. Retained olduğu için geç bağlanan tüketici her uçağın son konumunu hemen alır. |

## Mesajlar

Tüm gövdeler UTF-8 JSON nesnesidir (`ensure_ascii=False`, tek satır). Ek sarmal (envelope) yoktur: konum ve uçuş mesajı, kaynak dosyadaki kaydın kendisidir. Retained bir mesajı silmek için yayıncı aynı topic'e boş gövde (0 byte) yazar; tüketici boş gövdeyi "kayıt kaldırıldı" sayar.

**Konum** (`positions/<Key>`): Veri › Konum kaydı. Topic'teki `<Key>` gövdedeki `Key`'e eşittir; değilse tüketici mesajı atar.

**Uçuş** (`flights/<_id>`): Veri › Uçuş kaydı. Topic'teki `<_id>` gövdedeki `_id`'ye eşittir.

**Saat** (`clock`):

| Alan | Tip | Açıklama | Örnek |
|---|---|---|---|
| `now` | ISO 8601, `+03:00` | Simüle an. | `"2026-10-20T16:22:00+03:00"` |
| `epoch` | tamsayı | Aynı anın Unix saniyesi; `LastUpdate` ile karşılaştırma bunun üzerinden yapılır. | `1792502520` |
| `speed` | sayı | Gerçek 1 sn'de geçen simüle saniye. | `60` |

**Durum** (`status`):

| Alan | Tip | Açıklama |
|---|---|---|
| `state` | `yayinda` / `bitti` / `koptu` | Yayıncının durumu. `koptu`, bağlanırken LWT olarak kaydedilir; broker yayıncının bağlantısı temiz kapanmadan koparsa yayınlar. |
| `source` | metin | `--in` değeri (`yayinda`'da). |
| `date` | `YYYY-MM-DD` | Kaynağın `meta.date`'i (`yayinda`'da). |
| `from` | `HH:MM` | Başlangıç saati (`yayinda`'da). |

## Yayıncı (`stream/publisher.py`)

```
python -m stream.publisher --in data/referans/seed42-2026-10-20-radar.json --from HH:MM [--speed 60] [--no-wait] [--broker mqtt://127.0.0.1:1883] [--root aocc/sim/v1]
```

| Argüman | Zorunlu | Açıklama |
|---|---|---|
| `--in` | evet | Radar biçimli referans dosya (Veri › Kaynak dosya). Yalnızca okunur. |
| `--from` | evet | Simüle saatin başlangıcı, `HH:MM`. Gün `meta.date`'ten, saat dilimi `+03:00`. |
| `--speed` | hayır | Gerçek 1 sn'de geçen simüle saniye, varsayılan `60`, `0`'dan büyük. |
| `--no-wait` | hayır | Beklemeden yayınlar (test ve hızlı doldurma için). Sıra ve içerik değişmez. |
| `--broker` | hayır | `mqtt://host:port`; varsayılan ortamdaki `COPILOT_MQTT_URL`, o da boşsa `mqtt://127.0.0.1:1883`. |
| `--root` | hayır | Topic kökü, varsayılan `aocc/sim/v1`. |

Akış:

1. Girdi doğrulanır (dosya okunuyor, `meta.date` geçerli, `--from` ve `--speed` geçerli, her konumun `Key` ve `LastUpdate`'i var). Hata varsa broker'a bağlanılmaz: stderr'e `Hata: …`, çıkış 1, hiçbir mesaj yayınlanmaz (`synth` CLI kuralı).
2. Broker'a bağlanılır; LWT `status` = `{"state": "koptu"}` (QoS 1, retained). Bağlanamazsa `Hata:` ve 1.
3. Girdideki **tüm** `Key`'lerin `positions/<Key>` topic'lerine boş retained mesaj yazılır: aynı veriyle yeniden başlatmada önceki koşunun konumları kalmaz.
4. `status` = `yayinda`; ardından her uçuş kaydı `flights/<_id>`'ye.
5. Simüle saat `--from`'dan başlar ve 30 sn adımlarla ilerler. Her adımda önce `LastUpdate`'i o adıma kadar (`≤`) gelmiş, henüz yayınlanmamış konumlar `(LastUpdate, Key)` sırasıyla yayınlanır, sonra `clock` yayınlanır. `LastUpdate`'i `--from`'dan önce olan konumlar yayınlanmaz.
6. Bekleme `synth.stream` ile aynıdır (`docs/bozulma.md` › Akış › Belirlenimcilik ve bekleme): adım *i*'nin yayın anı başlangıç + (adım_i − from) / speed gerçek saniyedir, kayma birikmez; `--no-wait`'te hiç beklenmez.
7. Son konum yayınlandıktan sonra son `clock`, ardından `status` = `bitti` yazılır, bağlantı temiz kapatılır (LWT tetiklenmez). stderr'e tek satır özet: yayınlanan konum sayısı, ilk ve son simüle saat. Ctrl+C'de de `bitti` yazılır.

- Yayınlanan mesajların içeriği ve sırası yalnızca `--in` ve `--from`'dan türer; `--speed`, `--no-wait` ve sistem saati yalnızca **ne zaman** yayınlandığını etkiler.
- Yayıncı kayıtları düzeltmez, süzmez, ara değerleme yapmaz; girdide ne varsa onu yayınlar.

## Tüketici (`stream/consumer.py` + backend)

Tüketici backend sürecinde çalışan tek bir MQTT abonesidir; tarayıcı başına ayrı abonelik açılmaz. `<kök>/#`'e abone olur; adresi `COPILOT_MQTT_URL`'den, kökü `COPILOT_MQTT_ROOT`'tan (boşsa `aocc/sim/v1`) okur. Backend konteynerde çalışırken değer `mqtt://host.docker.internal:1883`'tür (Broker › Erişim).

Durum (bellekte, süreç başına bir tane):

| Parça | İçerik |
|---|---|
| `positions` | `Key` → son konum kaydı. Yeni mesajın `LastUpdate`'i eldekinden küçükse atılır (sıra dışı ya da yinelenen mesaj). |
| `flights` | `_id` → uçuş kaydı. |
| `clock` | Son saat mesajı. Yoksa bayatlık hesaplanmaz. |
| `status` | Son durum mesajı; broker'a bağlantı yoksa `broker_yok`. |

- **Gelecek konum gösterilmez.** `LastUpdate` > `clock.epoch` olan konum saklanır ama SSE'ye verilmez; saat ona ulaşınca verilir (`docs/tools.md` › `get_flight_details` › `ts ≤ now` kuralı).
- Tüketici konumu düzeltmez, tahmin etmez, ara değerleme yapmaz; uçuş kaydından konum türetmez.
- Tüketici sistem saatini bayatlık için kullanmaz; tek saat `clock` mesajıdır. (Backend'de sistem saati yalnızca `backend/clock.py`'den okunur; heartbeat aralığı bekleme süresidir, saat okuması değildir.)
- Broker bağlantısı koparsa tüketici yeniden bağlanmayı dener (1, 2, 4 … en fazla 30 sn); bu sürede `status` `broker_yok`'tur, eldeki konumlar korunur.

## Bayatlık

Kural `docs/zarf.md` ile aynıdır; konum için eşik **5 dakikadır** (`docs/zarf.md` › Örnekler › `get_flight_position`).

- Yaş = `clock.epoch` − `LastUpdate` (saniye).
- Yaş **300 sn'yi aşarsa** konum bayattır (`stale: true`). Eşiğe eşit yaş bayat sayılmaz.
- Bayatlığı tüketici hesaplar; yayıncı ve ekran hesaplamaz. Ekran yalnızca SSE'deki `stale`'i gösterir.
- Bayat konum silinmez ve güncelmiş gibi sunulmaz: son değer `LastUpdate` zaman damgasıyla verilir ve eski olduğu açıkça işaretlenir. Ara değerleme, tahmin ya da başka kayıttan (block zamanı, rota) konum üretilmez.
- `status` `yayinda` değilken (`bitti`, `koptu`, `broker_yok`) saat ilerlemez; bayatlık son saatle donar ve ekran akışın durduğunu ayrıca gösterir.
- Örnek: `TK2345`'in izi 16:02–16:22'dir. Saat 16:27:00'de yaş 300 sn, konum güncel; 16:27:30'da yaş 330 sn, konum bayat. `stale_position` uygulanmış veride iz 16:12'de biter ve aynı kural 16:17:30'da bayat yapar.

## SSE: `GET /live/positions`

Yanıt `text/event-stream; charset=utf-8`; her olayın `data`'sı tek satır JSON (`ensure_ascii=False`). Biçim `/chat` akışıyla aynı kurallara uyar (`docs/chat.md`). Vite proxy listesine `/live` eklenir (CLAUDE.md › frontend).

| Olay | Ne zaman | `data` |
|---|---|---|
| `snapshot` | Bağlantı açılınca bir kez, ilk olay. | `{"clock", "status", "positions": [görünüm…]}` (`positions` `Flight`'a göre sıralı). |
| `position` | Yeni konum SSE'ye verilebilir olduğunda. | Görünüm. |
| `stale` | Bir konum güncelden bayata geçtiğinde (saat ilerledikçe); her geçişte bir kez. | Görünüm (`stale: true`). |
| `removed` | Retained konum boş mesajla silindiğinde. | `{"Key"}` |
| `clock` | Her saat mesajında. | Saat mesajı. |
| `status` | Durum değiştiğinde. | `{"state"}` |

Görünüm = konum kaydının alanları olduğu gibi + `as_of` (`clock.now`), `age_s` (tamsayı) ve `stale` (mantıksal). Saat yoksa `as_of`, `age_s` ve `stale` yazılmaz.

- 15 gerçek saniyede bir `: ping` yorumu gönderilir (bağlantı canlı tutma).
- İstemci koparsa sunucu o istemcinin kuyruğunu bırakır; tüketici durumu etkilenmez. Yeniden bağlanan istemci yine `snapshot` ile başlar; `Last-Event-ID` desteklenmez.
- Hata ayrıntısı (broker adresi, exception) olaylara yazılmaz; yalnızca `status` `broker_yok`.

## Ekran (`/canli`)

Vite + React'te yeni rota `/canli` (`src/Live.tsx`, SSE istemcisi `src/live.ts`). Harita bu sürümde yoktur.

- Tablo, `Flight`'a göre sıralı: `Flight`, `Callsign`, `Registration`, `Type`, `Origin → Destination`, `Latitude`/`Longitude`, `Track`, `Speed`, `Onground`, son güncelleme (`LastUpdate`, yerel `HH:MM:SS`), yaş, durum.
- Durum rozeti: `stale` `false` ise "güncel", `true` ise "bayat — HH:MM itibarıyla". Bayat satır silinmez, soluk gösterilir.
- Üstte simüle saat (`clock.now`, `HH:MM:SS`) ve akış durumu. `status` `yayinda` değilse satırların üstünde "Akış durdu (<durum>), son saat HH:MM:SS" bandı.
- Ekran değer hesaplamaz: yaşı ve bayatlığı SSE'den alır, konumu kaydırmaz, eksik alanı "—" ile gösterir ve doldurmaz.

## `stream/` paketi

| Dosya | Durum | İçerik |
|---|---|---|
| `stream/__init__.py` | yazılacak | Paket. |
| `stream/messages.py` | yazılacak | Topic adları, mesaj kurucu/ayrıştırıcıları, bayatlık eşiği (`STALE_AFTER_S = 300`). |
| `stream/publisher.py` | yazılacak | Yayıncı CLI. |
| `stream/consumer.py` | yazılacak | MQTT aboneliği ve durum; bayatlık hesabı saf fonksiyon olarak test edilir. |
| `tests/test_stream_publisher.py`, `tests/test_stream_consumer.py`, `tests/test_live_sse.py` | yazılacak | Broker gerektirmeyen testler sahte istemciyle; broker'lı uçtan uca test `docker compose -f broker/compose.yaml up -d` ister ve broker yoksa atlanır. |

`synth/stream.py` (stdout'a NDJSON) ayrı kalır; sentetik biçimdeki veriyi akıtır ve testleri değişmez. Broker ayarı `stream/`'de değil, `broker/`'dadır. Bağımlılık: `paho-mqtt==2.1.0` (`requirements.txt`).

## Kurallar

- Mesaj gövdesi kaynak kaydın kendisidir; hattın hiçbir aşaması alan eklemez, değiştirmez, türetmez. Tek istisna SSE görünümündeki `as_of`, `age_s`, `stale`'dir ve bunları yalnızca tüketici hesaplar.
- Bayatlık eşiği tek yerde tanımlıdır (`stream/messages.py`); ekranda ya da yayıncıda tekrar yazılmaz.
- Yayıncı ve tüketici dosyaya yazmaz; broker kalıcılığı kapalıdır.
- Gerçek kaynağa geçişte yalnızca yayıncı değişir; kök `aocc/live/v1` olur, mesaj biçimi aynı kalır.

## Açık sorular

Veri ekibiyle teyit edilecek; cevaplanınca Veri tabloları ve referans dosya güncellenir.

1. İptal edilen uçuşun `op_status` kodu. Şimdilik yazılmıyor, yerine sentetik ek alan `cancelled: true` var.
2. Kalkışta off-block zamanının alan adı (`in_block_*`'ın departure karşılığı). Şimdilik departure'da block zamanı yazılmıyor.
3. `total_delay`'in anlamı. Örnekte `-2`, gerçekleşen − tarife farkına benziyor (`in_block` 14:18, `sto` 14:20); şimdilik planlanan gecikme (`delay_minutes`) yazılıyor.
4. Gate'in AODB biçimindeki alanı (`gate_code`'un karşılığı).
5. Radar `Key`'inin gerçek beslemede nasıl üretildiği. Burada `sha256(flight_id)[:8]`; tüketici `Key`'i yalnızca anahtar olarak kullanır, içeriğine bakmaz.
6. Bozulma senaryolarının (`docs/bozulma.md`) radar biçiminde üretimi. `synth.corruption` sentetik biçimde çalışır; radar biçimine çeviren dönüştürücü repoda yoktur.

## Kapsam dışı

- Harita, iz çizimi, filtre ve arama.
- Agent'ın canlı konum tool'u (`get_flight_position`). Tool tanımlandığında bu hattın tüketici durumunu kaynak olarak kullanabilir; sözleşmesi ayrı yazılır.
- Kimlik doğrulama, TLS, çoklu backend örneği, broker kümeleme.
- Geçmiş konumları saklama ve yeniden oynatma (yayıncı `--from` ile baştan başlatılır).
