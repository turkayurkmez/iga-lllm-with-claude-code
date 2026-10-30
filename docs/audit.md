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
| `ts` | ISO 8601, `+03:00` | Satırın yazıldığı an (akış bittikten sonra; bkz. Uçlar). |
| `question` | metin | Operatörün sorusu: `/chat` gövdesindeki `message`'ın baştaki ve sondaki boşluğu silinmiş hali (`ChatRequest` doğrulayıcısı; döngüye giden metnin aynısı). Başka değişiklik, kısaltma yoktur. |
| `status` | metin | `AgentResult.status` (beş değerden biri; `docs/agent.md` › Durumlar) ya da model çağrısı / beklenmeyen hata için `model_error`. |
| `reason` | metin ya da `null` | `AgentResult.reason`. `tamam`'da `null`; `model_error`'da `ERROR_MESSAGE` (`backend/main.py`). |
| `answer` | metin ya da `null` | Yalnızca `status` `tamam` iken `AgentResult.text` (akışa giden `text_delta`'ların birleşimi). İstemci akışı kesmiş olsa da yazılır. Diğer durumlarda `null`; kesik/ara metin kayda girmez (`docs/chat.md` › Kod garantileri 8). |
| `model` | metin ya da `null` | `backend.llm.MODEL`. Kodda sabit yazılmaz. |
| `instruction` | nesne ya da `null` | `AgentResult.instruction` (`name`, `version`, `summary`) olduğu gibi. `model_error`'da sonuç olmadığından `name` ve `version` istekte çözülen sürümden, `summary` yüklenen metinden doldurulur. |
| `turns` | tamsayı ya da `null` | `len(AgentResult.turns)`. `model_error`'da `null` (turlar döngüyle birlikte kaybolur; `docs/agent.md` › Kurallar). |
| `tool_calls` | liste | Aşağıdaki öğelerden oluşur; `AgentResult.turns[].tool_calls[]` sırasıyla, `executed: false` olanlar dahil. Tool çağrısı yoksa ya da `model_error`'da `[]`. |
| `chips` | liste | Döngünün ürettiği `source_chip` olaylarının `data`'sı (`tool`, `source`, `as_of`, `stale`, `error_code`), üretildiği sırayla ve olduğu gibi (`docs/chat.md` › Kod garantileri 3'teki tekilleştirmeyle). İstemci akışı kesmiş olsa da döngünün ürettiği çiplerin hepsi. Çip yoksa `[]`. `kpi_card` ve `selection_card` kayda girmez (`value` taşırlar). |
| `client_disconnected` | mantıksal | İstemci akış bitmeden bağlantıyı kestiyse `true`: son olay (`done` ya da `error`) istemciye iletilemedi. Akış sonuna kadar iletildiyse `false`. |
| `injection_flags` | liste | Şüphe işaretleri (`docs/enjeksiyon.md` E6): `message:<kod>` (mesajda `backend/injection.py` › `FINDINGS` eşleşmesi; istek reddedilmez), `unverified_numbers`, `instruction_leak` (yalnızca `tamam`), `tekrar_siniri`. Bulgu yoksa `[]`. Bu alan eklenmeden önceki satırlarda yoktur; okuyan kod `record.get("injection_flags")` kullanır. |
| `unverified_numbers` | liste | Cevapta olup soruda ya da bu koşunun tool `value`'larında bulunmayan sayı/saat simgeleri (yalnızca `tamam`; yoksa `[]`). Eski satırlarda yoktur. |

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
- `audit_id` akış başlarken üretilir; `done`'da her zaman dolu gider.
- `question` satırı **akış bittikten sonra** tek kez yazılır: son olay (`done` ya da `model_error`'daki `error`) istemciye iletildikten sonra, cevap ve çiplerle. Son olay yazılırken satır henüz dosyada değildir.
- **İstemci akışı yarıda keserse** döngü durdurulmaz (`docs/agent.md` › Kapsam dışı); döngü bitince satır `client_disconnected: true` ile yine tek kez yazılır. Kesilme iki yoldan anlaşılır: sunucu `http.disconnect` bildirir (ASGI < 2.4) ya da olay gönderimi `OSError` verir (ASGI 2.4, uvicorn).
- Kayıt yazılamazsa (izin, disk) hata `logger.exception` ile loglanır; akış etkilenmez (zaten bitmiştir). `done`'daki `audit_id` yetim kalır; buna verilen geri bildirim eşleşmeyen satır olur.
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

1. **Tool `value`'su kayda girmez.** Zarfın yalnızca `source`, `as_of`, `stale`, `tool_version`, `author` ve `error.code` alanları taşınır (çiplerde de aynı alanlar). `value`, `filters`, `error.message`, `kpi_card` değerleri ve `selection_card` adayları (`value` dizisidir) yazılmaz. Operatif değerin kendisi kaynakta ve cevap metnindedir; kayıt yalnızca nereden geldiğini gösterir.
2. **Bir soru, bir satır.** Her `/chat` isteği (akış başladıysa) tam olarak bir `question` satırı üretir; beş bitiş durumunda, `model_error`'da ve istemci akışı kestiğinde. Geri bildirim bu satırı değiştirmez, ayrı satırdır.
3. **Kayıt yorumlamaz.** Alanlar `AgentResult`'tan ve zarftan olduğu gibi taşınır; hesap, özet, kısaltma, saat dönüşümü yoktur.
4. **Hata ayrıntısı girmez.** Exception metni, yığın izi, API yanıtı, request id ve API anahtarı hiçbir satıra yazılmaz (CLAUDE.md › Yasaklar). `model_error`'da `reason` genel `ERROR_MESSAGE`'dır.
5. **Kayıt akışı bozmaz.** Audit yazımı olay sırasını ve içeriğini değiştirmez; tek fark `done`'daki `audit_id` alanıdır. Yazım hatası akışı kesmez.
6. **Model ve saat gömülmez.** `model` `backend.llm.MODEL`'den, `ts` `clock.now()`'dan gelir.
7. **Testler sahte modelle ve geçici klasörle koşar.** `COPILOT_AUDIT_DIR` `tmp_path`'e, `COPILOT_NOW` sabit ana ayarlanır; testler satırı okuyup `value` anahtarının hiçbir düzeyde bulunmadığını da assert eder.

## Arayüz kuralları

1. Thumbs down ikonu yalnızca `done.status` `tamam` iken (ve `audit_id` doluyken; eski sunucuya karşı korunma), cevabın altında gösterilir. `error` ile biten akışta gösterilmez.
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
   "tool_version": "1.0.0", "author": "tool", "error_code": null}],
 "chips": [{"tool": "get_flight_summary", "source": "data/referans/seed42-2026-10-20.json",
   "as_of": "2026-10-20T16:22:00+03:00", "stale": false, "error_code": null}],
 "client_disconnected": false, "injection_flags": [], "unverified_numbers": []}
{"type": "feedback", "audit_id": "3f9c2a7e4b1d4c8e9a0f6b2d7e5c1a3b", "ts": "2026-10-20T16:23:10+03:00", "rating": "down"}
```

Satırda `600`, `4`, `115` yalnızca modelin cevap metninde (`answer`) geçer; zarfın `value`'su yoktur.

## Okuma scripti

`--isaretli` bayrağı `injection_flags` dolu soruları en yeniden eskiye listeler; hiç yoksa `İşaretli kayıt yok.` yazar.

`scripts/audit_report.py` kayıtları salt okur; dosyaları değiştirmez, modele ya da API'ye gitmez. Klasör `backend.audit.audit_dir()`'dir (`COPILOT_AUDIT_DIR`, boşsa `logs/audit`). Çıktı Türkçe düz metindir; `PYTHONIOENCODING=utf-8` ile çalıştırılır. Testleri `tests/test_audit_report.py`.

| Çağrı | Ne gösterir |
|---|---|
| (parametresiz) | Tüm günlerden `ts`'e göre en yeni 5 `question`. Bu 5'in içinde thumbs down alanlar önce, sonra kalanlar; ikisi de yeniden eskiye. Her soru tek satır: tarih ve saat, `audit_id`'nin ilk 8 karakteri, `status`, olumsuzsa `[olumsuz]`, soru, cevap (80 karakteri aşarsa kısaltılıp `…` eklenir; `null` ise `(cevap yok)`). |
| `--id <kimlik>` | Bir sorunun yolculuğu: `audit_id`, `ts`, soru, talimat (`name`, `version`) ve model, tur tur tool çağrıları (ad, `input`, çalıştı mı, `source`, `as_of`, `stale`, `error_code`), çipler, `status` ve `reason`, tam cevap, istemcinin akışı kesip kesmediği, geri bildirimler (`ts`'leriyle; yoksa `Geri bildirim yok.`). Kimlik tam `audit_id` ya da en az 6 karakterlik benzersiz önekidir. |
| `--tarih YYYY-MM-DD` | O günün dosyasındaki bütün sorular, thumbs down alanlar önce (yeniden eskiye), sonra kalanlar (yeniden eskiye). Her biri soru → cevap → geri bildirim. |

- Geri bildirim, hangi günün dosyasında olursa olsun `audit_id` ile eşleştirilir; ertesi gün verilen de sayılır. Aynı soruya birden çok geri bildirim varsa hepsi gösterilir, öncelik için bir tanesi yeter. Hiçbir soruya karşılık gelmeyen geri bildirim gösterilmez.
- `--id` ile `--tarih` birlikte verilemez (argparse kullanım hatası, çıkış kodu 2).
- Kayıt yoksa (klasör boş ya da o günün dosyası yok) `Kayıt yok.` yazılır, çıkış kodu 0.
- Hata durumunda stderr'e `Hata: ...` yazılır, stdout'a bir şey yazılmaz, çıkış kodu 1: klasör yok, tarih `YYYY-MM-DD` değil, kimlik 6 karakterden kısa ya da hex değil, kimlik hiçbir soruya uymuyor, önek birden çok soruya uyuyor (uyan kimliklerin hepsi stderr'de listelenir).
- Okunamayan satır (geçersiz JSON) atlanır; stderr'e `Uyarı: <dosya>:<satır no> okunamadı.` yazılır, diğer satırlar gösterilir.
- Yalnızca kayıtta olan alanlar gösterilir; script hesap yapmaz, değer türetmez.

## Kapsam dışı

- Kullanıcı kimliği ve oturum: uygulamada kimlik doğrulama yoktur; satırda kullanıcı alanı bulunmaz.
- Saklama süresi, dosya döndürme/silme, sıkıştırma.
- Çok süreçli yazım (birden çok uvicorn worker): kilit süreç içidir; tek süreç varsayılır.
- Docker'da kalıcı klasör (volume) bağlama.
- Token sayısı ve süre ölçümü (`docs/chat.md` › Kapsam dışı).
- Olumlu geri bildirim, geri bildirimin geri alınması, serbest metin not.
- Kayıtları okuyan analiz/rapor aracı.
