# Prompt Netleştirme Yapısı Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code'a yazılan belirsiz görev prompt'larını işe başlamadan önce Amaç/Bağlam/Veri/Kısıt/Format alanlarına göre netleştiren bir hook + skill yapısı kurmak.

**Architecture:** Bir `UserPromptSubmit` hook'u (PowerShell) slash komutlarını ve onay kalıplarını eler, kalan prompt'lara kısa bir hatırlatma ekler. Değerlendirme kurallarının tamamı `prompt-netlestir` skill'inde durur. Skill hem hatırlatmayla hem `/prompt-netlestir` ile çalışır.

**Tech Stack:** Windows PowerShell 5.1, Claude Code hooks/skills, pytest 9.1.1 (zaten `requirements.txt`'te).

**Spec:** `docs/superpowers/specs/2026-10-20-prompt-netlestirme-design.md`

## Global Constraints

- Hook PowerShell 5.1 ile çalışır; yeni bağımlılık yok, `.venv` gerektirmez.
- Hook hiçbir koşulda prompt'u engellemez: her hata yakalanır, çıktı boş, exit 0.
- Stdin UTF-8 `StreamReader` ile okunur.
- Kalıp listesi: `evet, hayır, tamam, ok, devam, devam et, onay, onaylıyorum, kabul, uygun, olur, iptal, dur` + tek harf ya da tek rakam.
- Eşleştirme: baştaki/sondaki boşluk ve noktalama atılır, tr-TR kültürüyle küçültülür, kalan metin kalıba tam eşit olmalı.
- Eklenen bağlam 2-3 satırı geçmez, emredicidir ve `prompt-netlestir` adını içerir.
- Tanımlayıcılar İngilizce; yorumlar, kullanıcıya dönen metinler ve test isimleri Türkçe.
- Komutlar `;` ile zincirlenir. Commit öneki `M2.0 - 0N`.
- `.claude/settings.json` içindeki `enabledPlugins` korunur.

## Review Focus

- Başında boşluk olan slash komutu (`"  /clear"`) → yine elenmeli (Task 1 testi).
- Boş ya da yalnızca boşluk içeren prompt → çıktı boş (Task 1 testi).
- `prompt` alanı olmayan geçerli JSON → çıktı boş, exit 0 (Task 1 testi).
- Kalıpla başlayan ama devam eden görev (`"evet, ama önce testleri yaz"`) → bağlam eklenmeli (Task 1 testi).
- Türkçe karakterli bağlam metninin stdout'ta geçerli JSON olarak çözülmesi → test stdout'u UTF-8 çözüp `json.loads` ile doğrular (Task 1 yardımcısı).

---

### Task 1: Hook betiği, testleri ve kaydı

**Files:**
- Create: `.claude/hooks/prompt-gate.ps1`
- Create: `tests/test_prompt_gate.py`
- Modify: `.claude/settings.json`

**Interfaces:**
- Consumes: yok.
- Produces: stdin'den `{"prompt": "..."}` okuyan, filtreyi geçen prompt için stdout'a
  `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "<metin>"}}`
  yazan, aksi halde hiçbir şey yazmayan betik. Her durumda exit 0.

- [ ] **Step 1: Testleri yaz**

`tests/test_prompt_gate.py` içinde bir yardımcı ve parametreli testler:

```python
GATE = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "prompt-gate.ps1"

def run_gate(stdin: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(GATE)],
        input=stdin, capture_output=True, timeout=30,
    )

def as_payload(prompt: str) -> bytes:
    return json.dumps({"prompt": prompt}, ensure_ascii=False).encode("utf-8")
```

Testler (her biri `returncode == 0` de doğrular):

- `test_slash_komutu_baglam_eklemez` — parametre: `"/clear"`, `"/prompt-netlestir x"`, `"  /clear"` → `stdout.strip() == b""`
- `test_onay_kalibi_baglam_eklemez` — parametre: `"evet"`, `"Hayır."`, `"  tamam  "`, `"B"`, `"2"`, `"onaylıyorum"`, `"HAYIR"`, `"devam et!"` → `stdout.strip() == b""`
- `test_bos_prompt_baglam_eklemez` — parametre: `""`, `"   \n"` → `stdout.strip() == b""`
- `test_gorev_promptu_baglam_ekler` — parametre: `"M2 için tool ekle"`, `"Uygun, Bölüm 2'ye geç"`, `"evet, ama önce testleri yaz"` → `json.loads(stdout.decode("utf-8"))` sonucu `["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"` ve `"prompt-netlestir" in ...["additionalContext"]`
- `test_bozuk_girdi_engellemez` — girdi: `b"{bozuk"`, `b""`, `b'{"baska": 1}'` → `stdout.strip() == b""`

- [ ] **Step 2: Testlerin başarısız olduğunu gör**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_prompt_gate.py -v`
Expected: betik olmadığı için bağlam bekleyen testler FAIL.

- [ ] **Step 3: `.claude/hooks/prompt-gate.ps1`'i yaz**

Yaklaşım: tüm gövde `try { ... } catch { }` içinde, sonunda `exit 0`.
- Stdin: `New-Object IO.StreamReader([Console]::OpenStandardInput(), [Text.Encoding]::UTF8)` ile `ReadToEnd()`, sonra `ConvertFrom-Json`.
- `prompt` yoksa ya da `Trim()` sonrası boşsa çık.
- `Trim()` sonrası `/` ile başlıyorsa çık.
- Normalleştirme: baş ve sondaki `[\p{P}\s]+` silinir, `ToLower([Globalization.CultureInfo]::GetCultureInfo('tr-TR'))`.
- Normalleştirilmiş metin kalıp dizisinde varsa ya da `^[\p{L}\p{Nd}]$` ile eşleşiyorsa çık.
- Aksi halde `ConvertTo-Json -Compress -Depth 3` ile çıktı; önce `[Console]::OutputEncoding = [Text.Encoding]::UTF8`.

Bağlam metni (birebir):

```
Prompt netleştirme kontrolü: Bu mesaj yeni bir görev prompt'uysa, çalışmaya başlamadan önce prompt-netlestir skill'ini Skill aracıyla yükle ve uygula.
Mesaj senin sorduğun bir soruya ya da gösterdiğin özete yanıtsa bu kontrolü atla.
```

Kalıp dizisi ve tr-TR küçültmesinin nedeni Türkçe yorumla betiğin başında belirtilir.

- [ ] **Step 4: Testlerin geçtiğini gör**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_prompt_gate.py -v`
Expected: tüm testler PASS.

- [ ] **Step 5: Hook'u `.claude/settings.json`'a kaydet**

`enabledPlugins`'in yanına:

```json
"hooks": {
  "UserPromptSubmit": [
    { "hooks": [ { "type": "command",
      "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"$CLAUDE_PROJECT_DIR/.claude/hooks/prompt-gate.ps1\"" } ] }
  ]
}
```

Doğrulama: `Get-Content .claude\settings.json -Raw | ConvertFrom-Json` hatasız çalışır ve `enabledPlugins` iki kaydıyla durur.

- [ ] **Step 6: Lint**

Run: `.\.venv\Scripts\python.exe -m ruff check backend scripts tests; .\.venv\Scripts\python.exe -m ruff format --check backend scripts tests`
Expected: hata yok.

- [ ] **Step 7: Commit**

```powershell
git add .claude/hooks/prompt-gate.ps1 tests/test_prompt_gate.py .claude/settings.json
git commit -m "M2.0 - 03 prompt-gate hook'u"
```

### Task 2: `prompt-netlestir` skill'i ve CLAUDE.md

**Files:**
- Create: `.claude/skills/prompt-netlestir/SKILL.md`
- Modify: `CLAUDE.md` (Proje özeti madde listesi ve Komutlar bloğu)

**Interfaces:**
- Consumes: Task 1'in bağlam metnindeki `prompt-netlestir` adı. Skill adı bununla birebir aynı olmalı.
- Produces: `/prompt-netlestir` ile çağrılabilen, hook hatırlatmasıyla yüklenen skill.

- [ ] **Step 1: `SKILL.md`'yi yaz**

Frontmatter:

```yaml
---
name: prompt-netlestir
description: AOCC Copilot reposunda bir görev prompt'unu çalışmaya başlamadan önce Amaç, Bağlam, Veri, Kısıt ve Format alanlarına göre değerlendirir; eksik alanları sorar, 5 alanlık özeti onaya sunar. prompt-gate hook'u hatırlattığında ya da kullanıcı /prompt-netlestir yazdığında kullan.
---
```

Gövde bölümleri (içerik spec'ten birebir alınır):
1. Ne zaman atlanır: mesaj Claude'un sorusuna/özetine yanıtsa.
2. Alan tablosu (spec › Alan tanımları).
3. Karar kuralı, 4 madde (spec › Karar kuralı).
4. Soru kuralları: `AskUserQuestion`, tek turda en fazla 4 soru, mümkünse seçenekli, yalnızca eksik alanlar.
5. Özet şablonu (spec › Özet şablonu) ve "onaydan önce dosya değiştirme, komut çalıştırma".
6. Elle çağırma: `/prompt-netlestir <metin>` "net ise sessiz geç" kuralını atlar ve özeti her zaman gösterir. Argüman yoksa, değerlendirilecek prompt bir önceki kullanıcı mesajıdır.

- [ ] **Step 2: CLAUDE.md'yi güncelle**

Proje özeti listesine, `docs/superpowers/specs/` maddesinden sonra:

```markdown
- `.claude/hooks/prompt-gate.ps1` + `.claude/skills/prompt-netlestir/`: görev prompt'larını işe başlamadan önce Amaç/Bağlam/Veri/Kısıt/Format'a göre netleştirir. Hook slash komutlarını ve onay kalıplarını atlar; `/prompt-netlestir` kontrolü elle zorlar.
```

Komutlar bloğundaki test satırını şununla değiştir:

```powershell
# Testler
.\.venv\Scripts\python.exe -m pytest; .\.venv\Scripts\python.exe -m pytest tests\test_prompt_gate.py::test_onay_kalibi_baglam_eklemez
```

Lint satırına `tests` eklenir.

- [ ] **Step 3: Tüm testleri çalıştır**

Run: `.\.venv\Scripts\python.exe -m pytest -v`
Expected: tüm testler PASS.

- [ ] **Step 4: Commit**

```powershell
git add .claude/skills/prompt-netlestir/SKILL.md CLAUDE.md
git commit -m "M2.0 - 04 prompt-netlestir skill'i"
```

- [ ] **Step 5: Elle kabul (kullanıcı, yeni oturumda)**

Hook ve skill yalnızca yeni bir Claude Code oturumunda yüklenir. Kullanıcı `/hooks` ile kaydı görür, sonra:
1. `tool ekle` → soru sorulur, ardından özet ve onay gelir.
2. `backend/prompts.py'deki SYSTEM_INSTRUCTIONS'a şu cümleyi ekle: "Emin değilsen söyle."` → soru sorulmadan çalışılır.
3. `/prompt-netlestir` + 2. senaryodaki prompt → yine de özet gösterilir.

Hook tetiklenmezse ilk bakılacak yer: hook komutunun Windows'ta hangi kabukla çalıştığı ve `$CLAUDE_PROJECT_DIR`'in açıldığı.
