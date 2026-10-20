# Prompt Netleştirme Yapısı (Claude Code)

- **Tarih:** 2026-10-20
- **Durum:** Taslak, kullanıcı incelemesinde
- **Kapsam:** Yalnızca bu repoda Claude Code'a yazılan geliştirme prompt'ları. AOCC Copilot
  ürününün `/chat` akışı kapsam dışıdır.

## Amaç

Claude Code'a yazılan bir prompt belirsizse, Claude işe başlamadan önce prompt'u beş alana
(Amaç, Bağlam, Veri, Kısıt, Format) göre değerlendirir ve eksik alanları kullanıcıya sorar.
Hedef, Claude'un bu projede varsayım yapma ihtimalini en aza indirmektir.

Başarı ölçütleri:

- Belirsiz bir görev prompt'unda Claude, çalışmaya başlamadan önce eksik alanları sorar ve
  onay alır.
- Net bir prompt'ta Claude araya girmez.
- Slash komutları ve onay/kısa yanıtlar kontrolü tetiklemez.
- Hook hiçbir koşulda prompt'u engellemez.

## Kararlar

| Konu | Karar | Gerekçe |
|---|---|---|
| Tetikleme | Karma: otomatik hook + elle `/prompt-netlestir` | Kontrol unutulmaz; istenince zorlanabilir. |
| Mimari | İnce hook + skill | Kurallar tek yerde (skill) durur; hook her prompt'a 2-3 satır ekler. |
| Ön filtre | Uzunluğa değil kalıba dayalı | Bu projede en belirsiz prompt'lar genelde kısa olanlardır. |
| Onay | Soru sorulduysa özet göster ve onay bekle; prompt netse sessizce çalış | Varsayımı en aza indirir, net prompt'ta gereksiz tur oluşturmaz. |
| Hook dili | PowerShell 5.1 | Yeni bağımlılık getirmez, `.venv` gerektirmez. |

Değerlendirilip reddedilen seçenekler:

- **Kalın hook:** kuralların tamamı her prompt'a eklenir. Her mesaj yüzlerce token alır ve
  kurallar hook ile skill'de iki kopya halinde yaşar.
- **Yalnızca CLAUDE.md kuralı:** pasif bir talimattır, uzun oturumlarda unutulabilir.

## Alan tanımları

Her alan için iki şey tanımlanır: Claude'un repodan bulabileceği bilgi (sormaz, kaynağını
gösterir) ve sorması gereken bilgi.

| Alan | Ne sorar | Repodan çıkarılabilir (sorma, kaynak göster) | Eksik sayılır, sor |
|---|---|---|---|
| **Amaç** | Bu iş neden yapılıyor, bitince ne değişmiş olacak? | Kilometre taşı bağlamı (git log, `docs/`) | Başarı ölçütü belirsizse ("iyileştir", "düzelt", "ekle" ama ne için?) |
| **Bağlam** | Hangi dosya/modül, hangi kilometre taşı, mevcut durum ne? | Dosya yapısı, `backend/llm.py`, `backend/main.py`, mevcut spec'ler | Prompt'ta geçen modül/özellik birden fazla yere eşlenebiliyorsa ya da repoda yoksa |
| **Veri** | Hangi girdiyle çalışılacak? (uçuş/gate/olay alanları, örnek istek, mock veri, model yanıtı) | Var olan şema ve örnekler | Uydurulması gereken her alan adı, değer, örnek kayıt. Canlı veri olmadığı için Claude bunları asla kendisi üretmez |
| **Kısıt** | Neye dokunulmamalı, hangi kurallar geçerli? | CLAUDE.md Kurallar/Yasaklar (ör. model adını gömme, ücretli API çağrısı) | Kapsam sınırı belirsizse (sadece backend mi, test de mi?) ya da iş ücretli API çağrısı gerektiriyorsa ve bu açıkça istenmemişse |
| **Format** | Çıktı ne olacak? (kod değişikliği, script, doc, commit, sadece açıklama) | Proje kuralları (Türkçe yorum, commit öneki) | Çıktı türü belirsizse ("bak bakalım" → analiz mi, düzeltme mi?), commit/push istenip istenmediği belli değilse |

### Karar kuralı

1. Beş alanın her biri prompt'tan ya da repodan kesin olarak doluyorsa Claude soru sormadan
   çalışır.
2. Bir alan "eksik sayılır" sütununa düşüyorsa Claude çalışmaya başlamadan önce yalnızca eksik
   alanları sorar. Sorular `AskUserQuestion` ile, mümkünse seçenekli olarak gelir ve tek turda en
   fazla 4 soru sorulur.
3. Cevaplardan sonra Claude 5 alanlık özeti gösterir ve onay bekler. Onaydan önce dosya
   değiştirmez, komut çalıştırmaz. İstisna: değerlendirme için dosya okuma/arama ve `git log`,
   `git status`, `git diff`, `git show`; script, test ya da API çağrısı yapan komutlar bu istisnaya
   girmez.
4. "Repodan çıkarılabilir", "tahmin edilebilir" anlamına gelmez. Claude bir değeri dosyada ya
   da komut çıktısında doğrudan göremiyorsa o alan eksik sayılır.

### Özet şablonu

```
Amaç:   ...
Bağlam: ...  (kaynak: backend/main.py)
Veri:   ...
Kısıt:  ...  (kaynak: CLAUDE.md › Yasaklar)
Format: ...
Varsayım: yok   ← sıfır değilse her biri ayrı satırda listelenir
Onaylıyor musun?
```

Repodan doldurulan her alanın yanında kaynağı parantez içinde yazılır.

## Akış

```
Prompt girildi
   │
   ▼
prompt-gate.ps1 (UserPromptSubmit hook)
   ├─ "/" ile başlıyor            → hiçbir şey ekleme
   ├─ onay/kısa yanıt kalıbı      → hiçbir şey ekleme
   ├─ betik hatası (herhangi)     → hiçbir şey ekleme, exit 0 (fail-open)
   └─ diğer                       → additionalContext: "Görev prompt'uysa önce prompt-netlestir skill'ini uygula"
   │
   ▼
Claude
   ├─ Mesaj kendi sorduğu soruya/özete yanıt → skill'i atla, devam et
   ├─ Skill uygula → 5 alan repo + prompt'tan doluyor → sessizce çalış
   └─ Eksik alan var → AskUserQuestion (≤4 soru) → 5 alan özeti → onay bekle → çalış
```

**Elle çağırma:** `/prompt-netlestir <metin>` "net ise sessiz geç" kuralını atlar ve özeti her
zaman gösterir.

**Bilinçli sınır:** "Uygun, Bölüm 2'ye geç" gibi onay ile yönlendirmeyi birleştiren cümleler
kalıp listesine takılmaz, hook bunlarda hatırlatmayı ekler. Mesajın kendi sorusuna yanıt
olduğunu Claude anlar ve skill'i atlar. Hook yalnızca ucuz bir ön elemedir, asıl kararı Claude
verir.

## Hook ayrıntıları

- **Dosya:** `.claude/hooks/prompt-gate.ps1`, PowerShell 5.1.
- **Girdi:** stdin'deki JSON'un `prompt` alanı. Stdin, UTF-8 `StreamReader` ile okunur;
  PowerShell 5.1'in varsayılan kod sayfası Türkçe kalıpları bozar.
- **Çıktı:** filtreyi geçen prompt için `hookSpecificOutput.hookEventName = "UserPromptSubmit"`
  ve `hookSpecificOutput.additionalContext` içeren bir JSON. Eklenen metin 2-3 satırı geçmez ve
  emredici yazılır. Filtreye takılan prompt için çıktı boştur.
- **Kalıp eşleştirme:** büyük/küçük harf duyarsızdır (Türkçe kültürle küçültme). Baştaki ve
  sondaki boşluklar ile noktalama yok sayılır; kalan metin listedeki bir kalıba tam eşit olmalıdır.
- **Kalıp listesi** (script başında bir dizi olarak tutulur, genişletilebilir):
  `evet, hayır, tamam, ok, devam, devam et, onay, onaylıyorum, kabul, uygun, olur, iptal, dur`;
  ayrıca tek harf ya da tek rakamdan oluşan seçimler (`A`, `b`, `2` …).
- **Fail-open:** script içindeki her hata yakalanır; çıktı boş, exit 0 olur.
- **Kayıt:** `.claude/settings.json` içine `hooks.UserPromptSubmit` eklenir; komut
  `powershell -NoProfile -ExecutionPolicy Bypass -File "$CLAUDE_PROJECT_DIR/.claude/hooks/prompt-gate.ps1"`.
  Repo yolu boşluk içerdiği için yol tırnak içindedir. Mevcut `enabledPlugins` olduğu gibi kalır.

## Dosyalar

| Dosya | Durum | İçerik |
|---|---|---|
| `.claude/skills/prompt-netlestir/SKILL.md` | yeni | Alan tablosu, karar kuralı, soru kuralları, özet şablonu, elle çağırma davranışı |
| `.claude/hooks/prompt-gate.ps1` | yeni | Ön filtre ve fail-open davranışı |
| `.claude/settings.json` | değişir | `hooks.UserPromptSubmit` kaydı |
| `tests/test_prompt_gate.py` | yeni | Hook birim testleri |
| `requirements.txt` | değişebilir | `pytest` yoksa `==` ile sabitlenmiş sürümle eklenir |
| `CLAUDE.md` | değişir | Yapı bölümüne hook/skill ve elle çağırma komutu için 2 satır |

## Test

### Otomatik (`pytest`, API çağrısı yok)

`tests/test_prompt_gate.py`, `powershell -NoProfile -ExecutionPolicy Bypass -File prompt-gate.ps1`'i
alt süreç olarak çalıştırır ve stdin'e UTF-8 JSON verir. Test isimleri Türkçedir.

| Durum | Beklenen |
|---|---|
| `/clear`, `/prompt-netlestir x` | çıktı boş, exit 0 |
| `evet`, `Hayır.`, `  tamam  `, `B`, `2` | çıktı boş, exit 0 |
| `onaylıyorum`, `HAYIR` (Türkçe karakter/büyük harf) | çıktı boş, exit 0 |
| `M2 için tool ekle` | geçerli JSON, `additionalContext` içinde `prompt-netlestir` geçer |
| `Uygun, Bölüm 2'ye geç` | geçerli JSON (bilinçli sınır) |
| bozuk JSON, boş stdin | çıktı boş, exit 0 |

Ruff kontrolü `tests` klasörünü de kapsar.

### Elle kabul (skill davranışı)

Yeni bir oturumda:

1. Belirsiz prompt ("tool ekle") → soru sorulur, ardından özet ve onay gelir.
2. Net prompt ("`backend/prompts.py`'deki `SYSTEM_INSTRUCTIONS`'a şu cümleyi ekle: …") → soru
   sorulmadan çalışılır.
3. `/prompt-netlestir` ile net prompt → yine de özet gösterilir.

## Kapsam dışı

- AOCC Copilot `/chat` akışında son kullanıcı mesajlarının netleştirilmesi.
- Kullanıcı genelindeki (`~/.claude`) ayarlar; yapı yalnızca bu repoda geçerlidir.
