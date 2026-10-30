# Canlı mod demosu: dört pencere

Amaç: simüle konum akışını (yayıncı → Mosquitto → backend tüketicisi → SSE → harita) ve Copilot'un canlı konuma bakarak cevap vermesini göstermek. Sözleşme `docs/canli_akis.md`'dedir; burada yalnızca açılış sırası ve nedenleri vardır.

Tüm komutlar Windows PowerShell 5.1'de, **repo kökünden** çalışır (Pencere 3 hariç). Her pencere ayrı bir PowerShell'dir.

## Ön koşullar

- Docker Desktop açık.
- `.env` dolu: `ANTHROPIC_*`, `COPILOT_DATA=data/referans/seed42-2026-10-20.json`, `COPILOT_MQTT_URL=mqtt://127.0.0.1:1883`, `COPILOT_MQTT_ROOT=aocc/sim/v1`. `COPILOT_MQTT_URL` boşsa tüketici başlamaz ve `/live/positions` 503 döner.
- `COPILOT_NOW` **boş** olmalı (ya da yorum satırı). Canlı modda operasyonel saat `clock` mesajından gelir; saat mesajı gelene kadar sabit `COPILOT_NOW` kullanılır ve demonun ilk saniyelerinde eski bir an gösterir.
- `frontend/` için bir kez `npm install`.

## Sıra ve nedenleri

Akış tek yönlüdür; **veriyi üreten en son, onu gösterenler önce** açılır. Böylece izleyici ilk konumu görmeye hazır olur, hiçbir mesaj boşa gitmez.

| # | Pencere | Neden bu sırada |
|---|---|---|
| 1 | Broker | Herkes ona bağlanır; önce o ayakta olmalı. |
| 2 | Backend | Açılışta broker'a abone olur (tüketici). Broker yoksa `connect_async` ile beklemeden açılır ve yeniden dener, ama `status` `broker_yok` görünür; sırayı doğru tutunca bu karışıklık olmaz. |
| 3 | Frontend | SSE'ye bağlanır, `snapshot` alır. Tarayıcıyı yayıncıdan **önce** açmak, ilk konumların ekrana düşüşünü canlı göstermenin tek yoludur. |
| 4 | Yayıncı | Zinciri çalıştıran tek parça. Başlayınca saat ve konumlar akmaya başlar; en son açılır. |

### Pencere 1: Broker (Mosquitto)

```powershell
docker compose -f broker/compose.yaml up -d
docker compose -f broker/compose.yaml ps   # healthy görünene kadar bekle
```

- Neden önce: backend ve yayıncı ona bağlanır.
- Temiz başlangıç gerekirse (önceki koşudan kalan retained konumlar): `docker compose -f broker/compose.yaml restart`. Persistence kapalı olduğu için retained mesajlar silinir.
- Konteyner açılışında `chown: … Read-only file system` uyarısı beklenir, zararsızdır.
- Pencere açık kalır; kapatma için sonda `docker compose -f broker/compose.yaml down`.

### Pencere 2: Backend (FastAPI + tüketici)

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

- Neden ikinci: lifespan'da `COPILOT_MQTT_URL` doluysa `LiveHub` ve paho abonesi başlar, `<kök>/#`'e abone olur. Yayıncı gelmeden abone olmuş olması, ilk mesajların hiçbirinin kaçmaması demektir (retained olsa da).
- `--reload` verme: dosya değişince yeniden başlar, tüketici durumu (saat, konumlar) sıfırlanır ve demo ortasında harita boşalır.
- Doğrulama: `curl.exe -s http://127.0.0.1:8000/health`.

### Pencere 3: Frontend (Vite)

```powershell
cd frontend
npm run dev
```

Tarayıcıda `http://localhost:5173/sohbet` aç (sohbetin sağında harita). Tablo görünümü için `/canli`.

- Neden üçüncü: proxy backend'e (`BACKEND_URL`, varsayılan `http://127.0.0.1:8000`) gider; backend yokken `/live/positions` bağlantısı kurulamaz ve harita "Akış durdu" bandında kalır.
- Yayıncı henüz başlamadığı için bu aşamada harita boş ve bantta `broker_yok` ya da durum yok görünür; **beklenen davranıştır**, hata değildir. Stand kareleri `GET /map/stands`'ten gelir ve hemen çizilir.
- Vite yalnızca `::1`'i dinler: `127.0.0.1:5173` değil `localhost:5173` kullan.

### Pencere 4: Yayıncı (başlatan parça)

```powershell
.\.venv\Scripts\python.exe -m stream.publisher --in data/referans/seed42-2026-10-20-radar.json --from 16:00 --speed 60
```

- Neden en son: bu komut akışı başlatır. Başlayınca ekrandaki saat 16:00'dan ilerler (gerçek 1 sn = simüle 60 sn), uçaklar haritaya düşer.
- `--from 16:00`: `TK2345`'in izi 16:02–16:22'dir, yani demo kısa sürede hem hareketli uçak hem de iz bitişini (final konum) gösterir. Başka bir an için `--from HH:MM`.
- Hız: `--speed 60` (varsayılan). Daha yavaş ve konuşmaya uygun: `--speed 30` (`--interval 1` ile aynı). `--speed` ve `--interval` birlikte verilmez.
- stdout'a her konum ve saat mesajı `topic gövde` olarak basılır (izleyiciye akışın gerçek olduğunu gösterir). Özet stderr'e gider.
- Ctrl+C temiz kapatır (`status` = `bitti`); harita "Akış durdu (bitti)" bandına geçer. Yeniden başlatınca önceki koşunun konumları temizlenir, baştan akar.

## Demo akışı (öneri)

1. Dört pencere hazır, tarayıcı `/sohbet`'te. Boş harita ve stand'leri göster.
2. Pencere 4'ü başlat; saatin ilerlediğini ve uçakların belirdiğini göster.
3. Sohbete canlı konuma bağlı bir soru sor (ör. `TK2345` şu an nerede?). Cevap `clock` ile aynı simüle ana göre gelir.
4. Haritadan bir uçağa tıkla: `Bağlam: <id> ×` çipi çıkar, sonraki mesaja `selected` eklenir.
5. Yayıncıyı Ctrl+C ile durdur: bant ve gri uçaklar akışın durduğunu gösterir; konumlar silinmez.

## Sorun giderme

| Belirti | Sebep / çözüm |
|---|---|
| `/live/positions` 503 | `COPILOT_MQTT_URL` boş ya da `mqtt://host[:port]` biçiminde değil; `.env`'i düzelt, backend'i yeniden başlat (değer açılışta bir kez okunur). |
| Harita boş, bant `broker_yok` | Broker kapalı ya da backend broker'dan önce başlamış (yeniden bağlanma 1–30 sn sürer). Pencere 1'i kontrol et. |
| Saat ilerlemiyor | Yayıncı çalışmıyor ya da bitti (`status` `yayinda` değilken saat donar). |
| Önceki koşunun uçakları görünüyor | Broker'ı `restart` et, sonra yayıncıyı başlat. |
| Yayıncı `Hata:` ile çıkıyor | `--in` yolu, `--from` biçimi (`HH:MM`) ya da broker erişimi; hata olduğunda hiçbir mesaj yayınlanmaz. |
| Backend konteynerde çalışıyor | `COPILOT_MQTT_URL=mqtt://host.docker.internal:1883` olmalı; bu demo backend'i konteynersiz çalıştırır. |
| Her şey tamam ama sohbet cevap vermiyor | `/chat` 503: `ANTHROPIC_*` eksik. `/health` bundan etkilenmez. |

## Kapatma

Sıra ters: Pencere 4 (Ctrl+C) → 3 (Ctrl+C) → 2 (Ctrl+C) → 1 (`docker compose -f broker/compose.yaml down`). Yayıncı önce durursa `bitti` yazar ve broker'a temiz kapanır; broker en son kapanınca hiçbir bileşen bağlantı hatası basmaz.

## Senaryo

Konuşma dilinde yazılmıştır. Her satırda "Olmazsa" dolu olmalıdır. Satırlar demo sırasında eklenir; şimdilik yalnızca açılış satırı vardır.

| Söyleyeceğim | Yapacağım | Ekranda Beklenen | Olmazsa |
|---|---|---|---|
| "Şu an havalimanında canlı bir akış var gibi çalışacağız. Bu veri simüle, ama gerçek radar beslemesiyle aynı biçimde geliyor. Önce haritaya bakalım, henüz boş." | Dört pencere hazır, yayıncı henüz **başlamadı**. Tarayıcıda `http://localhost:5173/sohbet` açık. | Sohbetin sağında harita çizili, stand kareleri ve `stand_code` etiketleri görünür, uçak yok. Üstte "Akış durdu" bandı çıkabilir (beklenen). | Harita hiç çizilmiyorsa Pencere 2'de backend'in ayakta olduğunu (`/health`) ve Vite'ın `BACKEND_URL`'i gördüğünü kontrol et; sayfada `127.0.0.1` değil `localhost` kullan. Stand'ler gelmiyorsa `COPILOT_DATA` yolunu bak (`GET /map/stands` 503 verir). Hâlâ olmazsa konuşmaya "harita biraz sonra açılıyor" diye devam et, Pencere 4'ü başlatıp sayfayı yenile. |

## Bilinçli Sınır

## Eksiklikler

## Prova notları
