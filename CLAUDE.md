# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Proje özeti

AOCC Copilot: havalimanı Operasyon Kontrol Merkezi (AOCC) personeli için Claude tabanlı asistan. Hedef, canlı operasyon verisini (uçuş, gate/stand, kaynak, olay) tool'larla sorgulayıp özetlemek; şu an canlı veri bağlantısı yok. Python 3.13 + FastAPI backend, Anthropic Python SDK 1.x'e doğrudan API key ile bağlanır. Gün 1 iskelesi `docs/spec.md`'ye göre kuruluyor: docker compose (`db` Postgres 17 + `backend`), `db/schema.sql`, `synth/` sentetik veri üreteci. `frontend/`: Vite + React + TypeScript iskelesi (create-vite react-ts şablonu), henüz uygulama ekranı yok.

- `backend/llm.py`: tek config ve istemci noktası. `.env`'yi import anında yükler (`scripts/` modül düzeyinde `client` import ettiği için böyle kalmalı); `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_TEMP_MODEL` eksik/boşsa Türkçe `ConfigError` fırlatır, yani bu modülü import eden her şey geçerli bir `.env` ister. Ortamdaki değişkenler `.env`'nin önüne geçer. `client` (senkron) script'ler, `async_client` FastAPI içindir.
- `backend/main.py`: `GET /health`, `POST /chat` (`{"message": "..."}`; boş/boşluk mesaj 422). `backend.llm`'i modül düzeyinde import etmez, ilk `/chat`'te `load_llm()` ile yükler; böylece `/health` API anahtarı olmadan çalışır, ayar eksikse `/chat` 503 + genel mesaj döner. `/chat` yanıtı SSE akışıdır: `delta` (metin parçası) olayları, ardından `done` (`stop_reason`) ya da `error`.
- `docker-compose.yml` + `backend/Dockerfile`: backend `db` sağlıklı olunca başlar ama veritabanına bağlanmaz. `.env` imaja girmez, `env_file` ile verilir; `db` yalnızca `POSTGRES_PASSWORD`'ü alır.
- `db/schema.sql`: spec §6 sözleşmesi; alan adları birebir korunur. Şema yalnızca **boş volume'da** yüklenir: şemayı değiştirdikten sonra `docker compose down -v` gerekir ve bu veritabanını sıfırlar (bilinçli davranış).
- `synth/generator.py`: `python -m synth.generator --seed N --date YYYY-MM-DD --out dosya.json`. Belirlenimci: rastgelelik yalnızca `random.Random(seed)`'den; sistem saati, `set` sırası ve `hash()` kullanılmaz; çıktı `newline="\n"` ile yazılır. §9 sabit kayıtları (`TC-LSD`, `TK2344`/`TK2345`) her seed/tarihte aynıdır. Sözleşme `tests/test_generator.py`'dedir.
- `synth/corruption.py` / `synth/stream.py`: sözleşme `docs/bozulma.md`'de. corruption üreteç çıktısını tek senaryoyla bozar (hata durumunda çıktı yazılmaz); stream `positions`'ı simüle zamanla stdout'a NDJSON olarak akıtır (özet ve hatalar stderr'de). Testleri `tests/test_corruption.py`, `tests/test_stream.py`.
- `docs/spec.md` §4'teki `COPILOT_MODEL`/`COPILOT_TEMP_MODEL` adları geçersiz; geçerli adlar `ANTHROPIC_*`.
- `backend/prompts.py`: `SYSTEM_INSTRUCTIONS`, `/chat`'e `system` olarak verilir — canlı veri yokken bunu söyle, sayı/durum uydurma, hesabı servise bırak, kısa ve Türkçe yanıt ver.
- `scripts/`: tek seferlik deneyler (durumsuzluk, aritmetik, sıcaklık). Doğrudan çalıştırılabilmeleri için repo kökünü `sys.path`'e eklerler.
- `experiments/function_calling/`: tool kullanım deneyleri. `single_call.py` tek çağrıda blok türlerini, `loop.py` gerçek `get_flight_summary` döngüsünü (sayılar referans veriden, `MAX_TOUR=5`, hatada `is_error`) gösterir. `loop_envelope.py [--soru ..] [--veri ..]` aynı döngüyü `araclar_iyi.json`'daki `flight_info`/`search` ile kurar; her sonuç `backend.envelope.call_tool` ile zarflanır, modele zarfın tamamı JSON gider, `is_error` yalnızca `SCHEMA_VALIDATION_FAILED`'da true; sonda "Cevap:" ve "Zarflar:" blokları basılır. Argüman modelleri `araclar_iyi.json`'la başlangıçta karşılaştırılır; JSON değişirse modeller de güncellenmeli. `olc.py <araclar.json> <çıktı.json>` `sorular.json`'daki 12 soruyu 3'er kez sorar (36 ücretli çağrı), tool adı kümesi beklenenle tam eşleşirse doğru sayar; `compare.py` (API'siz) `sonuc_once.json`/`sonuc_sonra.json`'u yan yana koyar. Tool tanımları `araclar_kotu.json`/`araclar_iyi.json`; ölçümler karşılaştırılabilir kalsın diye `sorular.json`'u değiştirme.
- `data/referans/seed42-2026-10-20.json`: üreteçle (`--seed 42 --date 2026-10-20`) üretilen referans gün verisi; elle düzeltilmez. Özet: 600 uçuş (300/300), 4 iptal, 115 gecikmeli. `data/` `.gitignore`'da değil.
- `docs/zarf.md`: tool çıktılarının ortak zarfı (8 sabit alan, 5 hata kodu, eksik alan hata değildir). Yeni tool bu sözleşmeye uyar. `backend/envelope.py` › `call_tool(registry, name, args)` zarfı kurar: tool yalnızca `{value, source, data_time?, error?}` döner, `as_of`/`stale`'i katman hesaplar (tool gönderirse yok sayılır), `ToolSpec.max_age` aşılırsa `STALE_DATA` (author=layer). Sözleşme `tests/test_envelope.py`'de; testler `zarf.md`'deki JSON örneklerini birebir karşılaştırır, örnek değişirse kod da değişmeli. Zarf `Envelope` pydantic modelinden kurulur; `docs/zarf.schema.json` bu modelden `python -m backend.envelope` ile üretilir, elle düzeltilmez (model değişince yeniden üret, yoksa test kırmızı).
- `backend/tools/`: uçuş tool'ları, sözleşme `docs/tools.md`. Giriş noktaları yalnızca `run_tool(name, args)` (hiç istisna fırlatmaz, her sonuç zarftır) ve `tool_definitions()`. Tek doğruluk kaynağı `contracts/<tool>.json` (`name`, `version`, `description`, `input_schema`, `value_schema`); argümanlar `input_schema` ile jsonschema'da doğrulanır, ayrı pydantic şeması yoktur. Yeni tool `__init__.py` › `IMPLEMENTATIONS`'a kaydedilir; veriyi `_ortak.load_data(keys)` ile her çağrıda `COPILOT_DATA`'dan okur, veri hatasında `DataError` fırlatır (run_tool bunu `SCHEMA_VALIDATION_FAILED`, author=layer yapar). Sözleşme `tests/test_tools.py`'de (~25 sn; bozuk veriyi tmp'de `synth.corruption` ile üretir).
- `frontend/`: npm projesi, `package-lock.json` commit edilir. `vite.config.ts` geliştirmede `/chat` ve `/health`'i `127.0.0.1:8000`'e proxy'ler; backend'de CORS yok, yeni endpoint eklenince proxy listesine de eklenmeli. Lint `oxlint`.
- `backend/clock.py` › `now()`: `backend/` altında sistem saatinin okunduğu tek yer (`tests/test_clock.py` tarar). `COPILOT_NOW` doluysa sabit an (saat dilimi zorunlu, yoksa `ClockError`), boşsa sistem saati `+03:00`. Testler saati `monkeypatch.setenv("COPILOT_NOW", ...)` ile sabitler.
- `docs/sorumluluk-zinciri.md`: deney bulgularından hangi işin LLM'e, hangisinin servise ait olduğuna dair GÖZLEM/KARAR tablosu.
- `docs/superpowers/specs/`: ilk teknoloji kararları. uv/`pyproject.toml` ve Python 3.12 kararları geçerliliğini yitirdi; ortam pip + `.venv` + Python 3.13.
- `.claude/hooks/prompt-gate.ps1` + `.claude/skills/prompt-netlestir/`: görev prompt'larını işe başlamadan önce Amaç/Bağlam/Veri/Kısıt/Format'a göre netleştirir. Hook slash komutlarını ve onay kalıplarını atlar; `/prompt-netlestir` kontrolü elle zorlar. Betik UTF-8 BOM ile kaydedilmeli (PowerShell 5.1 BOM'suz dosyayı ANSI okur).
- `.claude/hooks/tool-tests.ps1` (PostToolUse, `Write|Edit`): `backend/tools/` altında bir dosya değişince `tests/test_tools.py`'yi koşar (~30 sn); yeşilse sessiz, kırmızıysa FAILED satırlarını exit 2 ile Claude'a iletir. Bash ile yapılan değişiklikte tetiklenmez. Hedef `TOOL_HOOK_TEST_TARGET` ile değişir (testleri `tests/test_tool_tests_hook.py`); aynı BOM kuralı geçerli.
- `.claude/agents/tool-definition-auditor.md`: salt okunur subagent (Read/Glob/Grep). Kontratları `docs/tools.md` ve tool tanımı kuralına göre denetler; tool başına Boyut | İçerik | Sorun | Önerilen düzeltme tablosu verir, sorun yoksa bunu açıkça yazar. Hiçbir dosyayı değiştirmez.

## Komutlar

Windows PowerShell 5.1, tüm komutlar repo kökünden.

```powershell
# Kurulum
py -3.13 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# API (port 8000, /docs ile denenebilir)
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload

# Endpoint denemesi (ayrı pencerede)
curl.exe -s http://127.0.0.1:8000/health
curl.exe -N -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" --data-binary "@istek1.json"

# Frontend (frontend/ klasöründen; dev sunucusu port 5173, backend ayrıca çalışmalı)
npm install; npm run dev
npm run build; npm run lint

# Docker (db + backend); şema yüklenmesi için volume boş olmalı
docker compose up --build
docker compose exec db psql -U copilot -d copilot -c "\dt"
docker compose down -v   # veritabanını sıfırlar

# Deney script'leri
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe scripts\first_call.py
.\.venv\Scripts\python.exe scripts\temperature.py --model <model-adı>

# Lint / format
.\.venv\Scripts\python.exe -m ruff check backend scripts synth tests experiments; .\.venv\Scripts\python.exe -m ruff format backend scripts synth tests experiments

# Sentetik veri (çıktı synth/out/, git'e girmez)
$env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe -m synth.generator --seed 42 --date 2026-10-20 --out synth\out\2026-10-20.json

.\.venv\Scripts\python.exe -m synth.corruption --in synth\out\2026-10-20.json --scenario stale_position --out synth\out\stale.json
.\.venv\Scripts\python.exe -m synth.stream --in synth\out\2026-10-20.json --from 16:00 [--speed 600] [--no-wait]
git -c core.autocrlf=false diff --no-index --stat synth\out\2026-10-20.json synth\out\stale.json   # bozulma farkı

# Yalnızca üreteç testleri (~15 sn; tüm paket ~190 sn, timeout'u ≥300 sn ver)
.\.venv\Scripts\python.exe -m pytest tests\test_generator.py

# Uçtan uca sunucu testi: arka planda başlat, /health'i yokla, try/finally ile kapat
$p = Start-Process .\.venv\Scripts\python.exe -ArgumentList "-m uvicorn backend.main:app --port 8765" -PassThru -WindowStyle Hidden
try { <for döngüsüyle /health yokla; istekleri at> } finally { Stop-Process -Id $p.Id -Force }

# Testler (tümü; tek test örneği)
.\.venv\Scripts\python.exe -m pytest; .\.venv\Scripts\python.exe -m pytest tests\test_prompt_gate.py::test_onay_kalibi_baglam_eklemez
```

## Kurallar

- Tanımlayıcılar İngilizce; yorumlar, docstring'ler, kullanıcıya dönen mesajlar ve birim test isimleri Türkçe.
- Model adı her zaman `backend.llm.MODEL` / `TEMP_MODEL`'den alınır.
- Tool tanımlarında açıklama "ne döndürür / ne zaman kullanılır / ne zaman KULLANILMAZ" içerir, enum ve örnek değer verilir; belirsiz açıklamada model birden fazla tool'u birlikte çağırıyor.
- Kontrat şemalarında her object `additionalProperties: false`; `minLength`/`maxLength`/`minimum`/`maximum`/`multipleOf` kullanılmaz, biçim `pattern` ile denetlenir. Kontrat değişince `tool_definitions` testi kontratla birebir karşılaştırır.
- Repo dışındaki (tmp) bir test dosyasını pytest'le koşarken `--rootdir`'i dosyanın klasörüne ver; verilmezse rootdir `C:\Users\turka` olur ve tek test ~15 sn sürer.
- `.claude/agents/` altına yeni eklenen subagent, oturum yeniden başlatılana kadar Agent aracında görünmez (`/agents` sihirbazı yok).
- Yanıttan metin alırken yalnızca `block.type == "text"` blokları birleştirilir; içerikte thinking blokları da olabilir.
- `max_tokens` varsayılanı 16000; thinking de çıktı token'ı harcar.
- Sıcaklık gerekiyorsa `extra_body={"temperature": ...}` ile gönderilir (SDK 1.x parametreyi kaldırdı). Güncel modeller (ör. `claude-sonnet-5-5`) varsayılan dışı sıcaklığı 400 ile reddeder.
- Model hatasında istemciye yalnızca genel bir Türkçe mesaj gider; ayrıntı `logger.exception` ile sunucu loguna yazılır.
- SSE ve JSON çıktısı `ensure_ascii=False` ile üretilir; Türkçe karakterler UTF-8 kalır.
- Config hata yolunu test etmek için boş değeri Python'dan ver: `python -c "import os; os.environ['ANTHROPIC_MODEL']=''; import backend.llm"`. PowerShell'de `$env:X=""` değişkeni siler ve `.env` değeri devreye girer.
- Model hatası denemesi: sunucuyu `$env:ANTHROPIC_MODEL="olmayan-model"` ile ayrı bir portta başlat; ortamdaki değer `.env`'yi ezer.
- Geçmişe asistan turu eklerken `response.content`'i olduğu gibi geri gönder; yalnızca metni değil, thinking bloklarını da.
- `sys.path.insert` sonrasındaki importlara `# noqa: E402` ekleme; E402 kapalı, ruff RUF100 hatası verir.
- Bağımlılıklar `requirements.txt`'te `==` ile sabitlenir.
- Ruff satır sınırı 88; PLW1510 (`subprocess.run`'a `check=` ver), RUF007 (`zip(x, x[1:])` yerine `itertools.pairwise`), FURB167 (`re.S` değil `re.DOTALL`) ve TRY004 (`isinstance` denetiminde `TypeError` fırlat) açık.
- Test dosyaları `test_*.py` adını taşır; pytest başka adları toplamaz.
- `tests/test_generator.py`, `test_corruption.py`, `test_stream.py` gevşetilmez; kırmızıysa kod düzeltilir. Sözleşme testleri koddan önce yazılır; hata testleri modülün var olduğunu da denetler (`importlib.util.find_spec`), yoksa modül eksikken de yeşil kalırlar.
- `synth` CLI'ları: hatada stderr'e `Hata: ...` yazar, 1 ile çıkar, çıktı (dosya/stdout) üretmez; tüm doğrulama ilk yazımdan önce yapılır.
- PowerShell 5.1'de `>` stdout'u UTF-16'ya çevirir; byte'ları birebir dosyaya almak için `cmd /c "... > dosya"` kullan.
- Yeni deney bulguları `docs/sorumluluk-zinciri.md` tablosuna işlenir.
- Komutlar `&&` değil `;` ile zincirlenir.
- Konsola Türkçe yazan script'ler `PYTHONIOENCODING=utf-8` ile çalıştırılır.
- Bash aracında Türkçe çıktı süzülecekse `PYTHONIOENCODING=utf-8 ... | grep -a` kullan; `$` içeren `python -c` tek satırlıklarını PowerShell yerine Bash'te çalıştır.
- Kaynak kodu Write/Edit ile yaz; Python kodunu başka bir Python string'i ya da heredoc içinden üretme (kaçış dizileri, ör. `"\n"`, gerçek karaktere dönüşür).
- Commit mesajları kilometre taşı önekiyle yazılır, ör. `M1.1 - 04 durumsuzluk deneyi`.

## Yasaklar

- Model adını koda gömme.
- `messages.create(temperature=...)` kullanma; SDK 1.x'te `TypeError` verir.
- Hata ayrıntısını (exception metni, API yanıtı, request id) istemciye gönderme.
- `.env` ve `*istek*.json` deneme dosyalarını commit etme.
- PowerShell'de `curl` takma adını kullanma; `curl.exe` kullan.
- Türkçe çıktı beklenen script'leri `python -I` ile çalıştırma; `PYTHONIOENCODING`'i yok sayar.
- Modelin operasyonel sayı/durum uydurmasına veya hesap sonucu üretmesine izin veren prompt değişikliği yapma.
- `.venv` Python süreçlerini toptan durdurma; VS Code eklenti sunucuları da `.venv`'den çalışır. Yalnızca başlattığın PID'i ya da `CommandLine`'ında `uvicorn` geçenleri durdur.
- Gerçek API çağrısı yapan script'leri döngüde ya da gereksiz yere tekrar çalıştırma; her çalıştırma ücretlidir.
