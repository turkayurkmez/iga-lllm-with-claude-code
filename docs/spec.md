# AOCC Copilot: Spec (Gün 1 iskelesi ve sentetik veri)

## 1. Hedef

Operatör doğal dille sorar; agent doğru tool'u seçer, **deterministik olarak hesaplanmış** sayıyı kaynağı ve veri zamanıyla verir, ilgili uçuşu veya park sahasını haritada gösterir. Hesap serviste yapılır, model yorumlar.

**Kapsam dışı (PoC §3.2):** RAG, her türlü tahmin, proaktif alarm, yazma işlemi (watchlist, rapor, not, kayıt güncelleme), PBB/VDGS/PLC entegrasyonu, rol ve kimlik, gerçek kaynak sistem bağlantısı, kişisel veri.

## 2. Repo yapısı

```
docker-compose.yml
.env.example           (değişken adları aşağıda)
.gitignore
.dockerignore
requirements.txt
CLAUDE.md
db/schema.sql
synth/                 üreteç (generator.py, python -m synth.generator ile çalışır; __init__.py ile paket)
backend/               FastAPI (M1.1'den gelen dosyalar burada kalır; taşınmaz, yeniden adlandırılmaz)
  Dockerfile
tests/                 pytest
eval/                  boş (.gitkeep)
frontend/              boş (.gitkeep)
docs/                  spec.md ve M1.1'den gelen dosyalar
scripts/               M1.1'den gelen dosyalar, dokunulmaz
```

- Python paketleri `backend` ve `synth` repo kökünden `python -m` ile çalışır.
- `frontend/` bu aşamada **servis değildir**; yalnızca yer tutucudur.
- Mevcut M1.1 ve M1.2 dosyaları (`backend/*.py`, `scripts/`, `docs/sorumluluk-siniri.md`, `CLAUDE.md`) korunur; plan bunları silmeyi veya yeniden yazmayı önermemelidir.

## 3. Servisler (docker compose)

| Servis | İmaj | Kural |
|---|---|---|
| `db` | `postgres:17-alpine` | Port `127.0.0.1:5432` (yalnızca yerel). Adlandırılmış volume `/var/lib/postgresql/data` altında. `db/schema.sql` ilk açılışta yüklenir (initdb dizini, salt okunur mount). Sağlık kontrolü `pg_isready`. Kullanıcı ve veritabanı adı `copilot`, parola `.env`'den. |
| `backend` | `python:3.13-slim` tabanlı, `backend/Dockerfile` | Port `8000`. `db` **sağlıklı** olunca başlar. Komut: `uvicorn backend.main:app --host 0.0.0.0 --port 8000`. Kaynak koddan bağımlılıklar `requirements.txt` ile kurulur. `.env` imajın içine kopyalanmaz; `env_file` ile verilir. |

- `GET /health` cevabı `{"status":"ok"}` olmalı ve **API anahtarı olmadan da** çalışmalıdır (anahtar yalnızca `/chat` çağrısında gerekir).
- Backend bu aşamada veritabanına **bağlanmaz**; bağımlılık yalnızca başlatma sırası içindir.
- `docker compose down -v` veritabanını sıfırlar; şema yalnızca **boş volume'da** yüklenir. Bu bilinçli bir davranıştır ve `CLAUDE.md`'ye not düşülür.

## 4. Ortam değişkenleri

`.env.example` mevcut satırlara (`ANTHROPIC_API_KEY`, `COPILOT_MODEL`, `COPILOT_TEMP_MODEL`) ek olarak **`POSTGRES_PASSWORD=`** (boş) içerir. `.env` hiçbir koşulda okunmaz veya içeriği yazdırılmaz; Claude Code parola satırını eklemesi için insana bırakır.

## 5. `.gitignore` ve `.dockerignore`

`.gitignore`'a eklenir: `synth/out/` ve `istek*.json`. `.dockerignore`: `.env`, `.venv`, `.git`, `synth/out`, `__pycache__`, `istek*.json`.

## 6. Veri modeli (`db/schema.sql`)

Şema sadakati ilkesi (PoC §5.2): alan adları, tipler, kod listeleri ve ilişkiler gerçek AODB mantığına yakın tutulur. Aşağıdaki liste **sözleşmedir**; adlar birebir kullanılır. Zamanlar `timestamptz`, tüm günler `+03:00`.

| Tablo | Alanlar |
|---|---|
| `aircraft` | `registration` text PK · `type_icao` text · `code_letter` char(1) A–F · `operator_iata` text |
| `stands` | `stand_code` text PK · `stand_type` `CONTACT`/`REMOTE` · `max_code_letter` char(1) A–F · `mars` boolean · `status` `AVAILABLE`/`UNAVAILABLE` · `lat`, `lon` double precision |
| `gates` | `gate_code` text PK · `terminal` text · `pier` text · `stand_code` text FK→stands, **boş olabilir** (otobüs kapısı) |
| `flights` | `flight_id` text PK (`FL-YYYYMMDD-NNNN`) · `flight_no` text · `callsign` text · `registration` FK→aircraft · `aircraft_type` text · `origin` text · `destination` text · `scheduled_time`, `estimated_time` timestamptz · `cancelled` boolean · `status` `SCHEDULED`/`ACTIVE`/`COMPLETED`/`CANCELLED`, varsayılan `SCHEDULED`. `flight_no` ve `callsign` üzerinde indeks |
| `movements` | `flight_id` PK FK→flights (uçuş başına 1) · `movement_type` `ARRIVAL`/`DEPARTURE` · `stand_code` FK, boş olabilir · `gate_code` FK, boş olabilir · `actual_runway_time`, `actual_block_time` timestamptz, boş olabilir |
| `positions` | `flight_id` FK · `ts` timestamptz · `lat`, `lon` double precision · `heading_deg`, `speed_kt` real · `phase` text. PK (`flight_id`, `ts`) |
| `delays` | `flight_id` PK FK→flights · `delay_minutes` integer, **≥ 15** · `delay_code` text · `category` text |

**Kod listeleri.**
- `code_letter` / `max_code_letter`: A < B < C < D < E < F. Bir uçak yalnızca `max_code_letter` değeri kendi harfine eşit veya büyük olan stand'a park eder.
- `phase`: `APPROACH`, `TAXI_IN`, `AT_STAND`, `TAXI_OUT`, `CLIMB`.
- `category`: `PASSENGER_BAGGAGE`, `AIRCRAFT_TECHNICAL`, `GROUND_HANDLING`, `WEATHER`, `ATC_RESTRICTION`, `AIRPORT_FACILITIES`, `REACTIONARY`. `delay_code` iki haneli, IATA benzeri **kurgusal** koddur.
- `flights.status` üreteçten gelmez; simülasyon saati (M1.4) ve yükleyici belirler. Üreteç yalnızca `cancelled` yazar.
- Yerel havalimanı kodu `XXXX`; diğer uçlar IATA 3 harf. (Gerçek AODB ile kod standardı eşlemesi veri ekibiyle teyit edilecek, PoC §5.2.)

## 7. Hacimler (bir gün)

Tek sayı değil **aralık**; testler aralıkla yazılır.

| Varlık | Değer |
|---|---|
| Hareket (`flights`/`movements` satırı) | 550–650; arrival ve departure ayrı ayrı 275–325 |
| Uçak | tam 200 |
| Stand | tam 120 (72 `CONTACT`, 48 `REMOTE`); en az 5 tanesi `UNAVAILABLE` |
| Gate | tam 80 (72 tanesi bir `CONTACT` stand'a bağlı, 8 tanesi otobüs kapısı) |
| Gecikmeli hareket | iptal edilmeyenlerin %15–25'i; `delay_minutes` 15–250 |
| İptal | 4–10 hareket; iptalde stand, gate, gerçekleşen zaman, konum ve gecikme **yok** |
| Konum | iptal edilmeyen her hareket için 30 sn çözünürlükte 20 dakikalık iz (arrival: son 20 dk, on-block'ta biter; departure: off-block'ta başlar) |

Her arrival, aynı uçağın aynı gün departure'ı ile çift oluşturur (ardışık `flight_id`: arrival tek, departure çift sıra no). Aynı uçak ve aynı stand için çiftlerin yer işgali zamanları **çakışmaz**.

## 8. Üreteç sözleşmesi

```
python -m synth.generator --seed N --date YYYY-MM-DD --out dosya.json
```

- Çıktı yolunun klasörünü kendisi oluşturur. stdout'a tek satır özet: toplam hareket, arrival, departure, gecikmeli, iptal, uçak, stand, gate.
- **Aynı seed ve tarih → birebir aynı dosya.** Sistem saati okunmaz. Rastgelelik yalnızca `--seed`'den gelir; Python'un küme (`set`) veya sözlük sırasına, `hash()` değerine ya da `PYTHONHASHSEED`'e bağlı hiçbir davranış olmaz. Çıktı kararlı sıralanır.
- Farklı seed → farklı çıktı.
- Tek JSON dosyası. Üst anahtarlar: `meta`, `aircraft`, `stands`, `gates`, `flights`, `movements`, `delays`, `positions`. Alan adları §6'daki tablo sütunlarıyla aynıdır (`flights.status` hariç). `meta` seed, tarih ve üretecin sürümünü taşır.
- `scheduled_time` her zaman verilen günde olur. Gecikmeli bir hareketin `estimated_time` değeri tarifeden `delay_minutes` kadar sonradır; gecikmesiz hareketin tahmini zamanı tarifeye eşittir.
- Konumlar rotada basit doğrusal ara değerlemeyle üretilir (gerçekçi uçuş dinamiği istenmez).
- `synth/out/` altına yazılan çıktılar git'e girmez.

## 9. Sabit (pinned) kayıtlar

Her seed ve her tarih için şu kayıtlar **bulunmalı ve aynı olmalıdır**: golden set (PoC Ek A) bunlara dayanır.

| Kayıt | Değer |
|---|---|
| Uçak | tescil `TC-LSD`, tip `A321`, kod harfi `C`, operatör `TK` |
| Arrival | sefer no `TK2344`, tarife 13:05 |
| Departure | sefer no `TK2345`, callsign `THY2345`, tescil `TC-LSD`, tarife 15:40, **25 dakika gecikmeli** (tahmini 16:05), iptal **değil** |
| Yerleşim | `TK2345` bir stand'a **ve** bir gate'e atanmış; konum izi var |
| Olmayan | sefer no veya callsign olarak `ZZ9999` hiçbir kayıtta **yoktur** (bilerek) |

Hareket toplamları, gecikmeli sayısı ve diğer tüm kayıtlar seed'e göre değişir. Golden set'te sayıların beklenen değeri **sabit yazılmaz**, veriden hesaplanır (Gün 4).

## 10. Test beklentileri (`tests/`)

Testler üreteçten **önce** yazılır; ilk koşumda kırmızıdır. Üreteç yazılırken testler gevşetilmez.

1. İki **ayrı süreçte**, farklı `PYTHONHASHSEED` değerleriyle, aynı seed ve tarihle çıktı birebir aynıdır. (Aynı süreçte iki koşum yetmez.)
2. Farklı seed farklı çıktı verir.
3. Özet satırı §8'deki alanları içerir; çıktı klasörü yoksa oluşturulur.
4. Hacimler §7 aralıklarındadır; gecikmeli oranı %15–25.
5. Referans bütünlüğü: her yabancı anahtar geçerli; iptal edilmeyen hareketin stand'ı `AVAILABLE`, kod harfi uygun; gate mevcut.
6. Zaman damgaları verilen günde; her arrival için departure sonradır.
7. Aynı uçak ve aynı stand için yer işgali aralıkları çakışmaz.
8. En çok geciken altı hareketin gecikme dakikası birbirinden farklıdır (Ek A "en çok geciken beş uçuş" sorusu belirsizlik taşımasın).
9. §9'daki sabit kayıtlar vardır; `ZZ9999` yoktur.
10. pytest, `requirements.txt`'te `pytest==9.1.1` olarak sabitlenir (sürüm Windows'ta hazırlıkta teyit edilir).

## 11. Bu aşamada yapılmaz

Üretecin veritabanına yüklenmesi · simülasyon saati (`clock.py`) · bozulma enjeksiyonu (`corruption.py`) · tool'lar, agent, sistem talimatı değişikliği · frontend kodu · PostGIS ve harita geometrisi (`seed_geo.sql` Gün 4) · hiçbir komutun Claude Code tarafından çalıştırılması (bu modülde komutları insan çalıştırır).

## 12. Kabul

- `docker compose up --build` sonrası `db` sağlıklı, `backend` ayakta; `curl.exe http://127.0.0.1:8000/health` → `{"status":"ok"}`.
- `docker compose exec db psql -U copilot -d copilot -c "\dt"` §6'daki yedi tabloyu listeler.
- `python -m pytest` yeşil.
- `git status` temiz; `.env` ve `synth/out/` izlenmiyor.

## 13. Açık sorular (bu belgeyi etkilemez, kayıt amaçlı)

- Gün 2'de tool'lar JSON dosyasından mı, Postgres'ten mi okuyacak? Yükleyici hangi modülde yazılacak?
- Kod standardı (IATA/ICAO) ve `delay_code` listesi gerçek AODB ile eşlenecek (veri ekibi gözden geçirmesi, PoC P-01).