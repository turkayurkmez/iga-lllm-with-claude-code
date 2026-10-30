# Oturum Geçmişi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/chat` sunucu tarafı oturum geçmişi tutsun; model önceki turlara yaslanan takip mesajlarını anlasın.

**Architecture:** Bellekte `SessionStore` (LRU, 2 saat sona erme) her `tamam` turu `{question, answer, tool_calls}` olarak saklar. `/chat` `session_id` alır, geçmişi `run_agent(history=...)` ile düz metin turları olarak modele verir, `done` olayında `session_id`/`session_reset` döner. İstemci geçmiş gönderemez. Yeni talimat `v5` = `v4` + ilke 14.

**Tech Stack:** Python 3.13, FastAPI, pydantic, pytest; frontend Vite + React + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-30-chat-gecmisi-ve-genel-grafik-design.md` (bölüm A). Bölüm B (genel grafik sorgusu) ayrı plandır ve bu planın ardından yazılır.

## Global Constraints

- Tanımlayıcılar İngilizce; yorumlar, docstring'ler, kullanıcıya dönen mesajlar ve test isimleri Türkçe (CLAUDE.md › Kurallar).
- Sistem saati yalnızca `backend/clock.py` › `now()` ile okunur (`tests/test_clock.py` tarar); testlerde `monkeypatch.setenv("COPILOT_NOW", ...)`.
- Model adı koda gömülmez; hata ayrıntısı istemciye gitmez.
- Sınırlar (spec): modele son 6 tur ve en çok 12000 karakter; en çok 100 oturum (LRU); oturum başına 20 tur; 2 saat hareketsizlikte oturum dolar. Sabitler `backend/session.py`'dedir, `.env`'e açılmaz.
- `session_id`: `secrets.token_hex(16)`, biçim `^[0-9a-f]{32}$`; biçimsiz değer 422.
- Yalnızca `status == "tamam"` turlar geçmişe girer; tool sonuçları/zarflar saklanmaz.
- Talimat metni kuralları (`docs/system-talimat.md`): rakam, `{}`, model adı yok; `snake_case` yalnızca kayıtlı tool adları; dosya ≤ 40 satır; metin değişince `VERSIONS` ve Değişiklik günlüğü birlikte artar.
- Ruff satır sınırı 88; `# noqa` yalnızca açık kurallarda. Geliştirirken ilgili test dosyası, tam `pytest` ve `ruff` sonda birer kez (hafıza: test/lint sıklığı).
- Commit mesajı kilometre taşı önekiyle (`M8.2 - ...`) ve `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` satırıyla biter.
- Tam pytest'te değişiklikten bağımsız 3 kırmızı vardır (CLAUDE.md › Kurallar); yenisini bunlarla karıştırma.

## Review Focus

1. Bilinmeyen/süresi dolmuş `session_id` (sunucu yeniden başladı): hata değil, yeni oturum ve `session_reset: true`. (Task 3)
2. Biçimsiz `session_id` ya da fazla gövde alanı: 422 ve model hiç çağrılmaz. (Task 3)
3. `tamam` olmayan tur (hata, sınır) geçmişe girmez; sonraki mesaj kısmi cevabı görmez. (Task 3)
4. İstemci akışı keser: döngü sürer, tur yine eklenir. (Task 3)
5. Tek bir cevap 12000 karakteri aşar: o tur modele **tamamen** gitmez, ortadan kesilmez; bellekteki kayıt durur. (Task 1)
6. Aynı oturuma eşzamanlı ekleme: kayıp ya da bozulma yok. (Task 1)

---

### Task 1: Oturum deposu ve geçmiş çevirici

**Files:**
- Create: `backend/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Produces (Task 2, 3 kullanır):
  - `class HistoryTurn(TypedDict)`: `question: str`, `answer: str`, `tool_calls: list[dict]` (her biri `{"name": str, "input": dict}`).
  - `SESSION_ID_PATTERN: str = r"^[0-9a-f]{32}$"`.
  - `class Begin(NamedTuple)`: `session_id: str`, `reset: bool`, `turn_index: int` (oturumdaki kayıtlı tur sayısı + 1).
  - `class SessionStore`: `__init__(self, *, max_sessions=100, max_turns=20, ttl_seconds=7200)`; `begin(self, session_id: str | None) -> Begin`; `history(self, session_id: str) -> list[HistoryTurn]` (modele gidecek görünüm: en yeni `MODEL_TURNS=6` tur, toplam `MODEL_CHARS=12000` karakter, eskiden başlayarak atılır, tur bölünmez); `add(self, session_id: str, turn: HistoryTurn) -> None`.
  - `STORE: SessionStore` (süreç başına tek).
  - `render_history(turns: list[HistoryTurn]) -> list[dict]`: Anthropic mesajları; her tur için `{"role": "user", "content": question}` ve `{"role": "assistant", "content": answer + not}`; tool çağrısı varsa not `\n\n[Önceki turda çağrılan araçlar: ad {json}; ad {json}]` (JSON `ensure_ascii=False`, kompakt), yoksa not yok.

- [ ] **Step 1: Failing testleri yaz** (`tests/test_session.py`, `COPILOT_NOW` her testte `monkeypatch.setenv` ile sabit, `STORE` yerine yerel `SessionStore()`):
  - `test_bos_session_id_yeni_oturum_acar`: `begin(None)` → `reset is False`, `turn_index == 1`, `re.fullmatch(SESSION_ID_PATTERN, id)`.
  - `test_bilinmeyen_id_yeni_oturum_ve_reset`: `begin("a"*32)` → `reset is True`, dönen id `"a"*32`'den farklı.
  - `test_bilinen_id_ayni_oturumu_surdurur`: `begin` → `add` → `begin(id)`: `reset is False`, `turn_index == 2`.
  - `test_iki_saat_hareketsizlikte_oturum_dolar`: `add` sonrası `COPILOT_NOW`'ı 2 saat 1 sn ileri al; `begin(id).reset is True`. 1 saat 59 dk'da `reset is False`.
  - `test_en_eski_kullanilan_oturum_atilir`: `max_sessions=2`, üç oturum aç, ilkine hiç dokunma; ilk id ile `begin` → `reset is True`; ortadaki kullanılmışsa korunur.
  - `test_oturum_basina_en_fazla_20_tur_saklanir`: 25 `add`; `history` çağrısından bağımsız olarak iç kayıt 20 tur (`len(store._sessions[id].turns) == 20` yerine `begin(id).turn_index == 21`).
  - `test_modele_son_alti_tur_gider`: 8 tur ekle; `history` yalnızca son 6, sıra eskiden yeniye.
  - `test_toplam_karakter_butcesi_asilirsa_en_eski_tur_tamamen_atilir`: üç turun cevabı 5000 karakter; `history` son iki turu verir (üçü 15000 > 12000).
  - `test_butceyi_tek_basina_asan_tur_modele_hic_gitmez`: tek tur cevabı 12001 karakter; `history == []`; `begin(id).turn_index == 2` (kayıt durur).
  - `test_render_history_metin_turlari_ve_arac_notu`: tool çağrılı tur için `[{"role":"user",...},{"role":"assistant","content": "Cevap\n\n[Önceki turda çağrılan araçlar: get_chart_data {\"group_by\":\"airline\"}]"}]`; araçsız turda not yok; Türkçe karakter kaçışsız.
  - `test_eszamanli_ekleme_tur_kaybetmez`: 8 thread her biri 10 `add`; `begin(id).turn_index == 21` (20 sınırı) ve istisna yok.
  - `test_modul_var`: `importlib.util.find_spec("backend.session") is not None` (modül yokken de kırmızı kalsın).

- [ ] **Step 2: Çalıştır, kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_session.py -q`
Expected: tümü FAIL/ERROR (`backend.session` yok).

- [ ] **Step 3: `backend/session.py`'yi yaz.** Depo `collections.OrderedDict[str, _Session]` + `threading.Lock`; `_Session` `turns: list[HistoryTurn]` ve `last_used: datetime` (`clock.now()`); `begin` süresi dolmuş/bilinmeyen id'de yeni id üretir (`secrets.token_hex(16)`), LRU için `move_to_end`; `max_sessions` aşılınca `popitem(last=False)`. `history` kopya döner (dış kod depoyu değiştiremez). Karakter bütçesi `len(answer) + len(not)` ile hesaplanır (not, `render_history`'deki aynı fonksiyondan).

- [ ] **Step 4: Çalıştır, yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_session.py -q`
Expected: tümü PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/session.py tests/test_session.py
git commit -m "M8.2 - oturum deposu ve geçmiş çevirici"
```

---

### Task 2: `run_agent` geçmişi kabul eder

**Files:**
- Modify: `backend/agent.py:115-145` (imza ve `messages` kurulumu)
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `render_history(turns: list[HistoryTurn]) -> list[dict]` (Task 1).
- Produces: `run_agent(question: str, client: Any = None, instruction_version: str | None = None, history: list[HistoryTurn] | None = None) -> AgentResult`. `history` verilmezse ya da boşsa ilk istek bugünküyle bayt bayt aynıdır; `AgentResult` değişmez.

- [ ] **Step 1: Failing testleri yaz** (`tests/test_agent.py` sonuna; mevcut sahte istemci kalıbını ve `kwargs`'ı `copy.deepcopy` ile saklayan kaydediciyi kullan):
  - `test_gecmis_yoksa_ilk_istek_degismez`: `history=None` ve `history=[]` ile `messages == [{"role": "user", "content": QUESTION}]`.
  - `test_gecmis_bu_sorudan_once_metin_turlari_olarak_gider`: iki turluk geçmiş → ilk isteğin `messages` dizisi 4 geçmiş mesajı + son mesaj olarak yeni soru; geçmiş mesajlarında `tool_use`/`tool_result` bloğu yok (her `content` `str`).
  - `test_gecmis_arac_notunu_asistan_metnine_ekler`: tool çağrılı tur için asistan `content` `"[Önceki turda çağrılan araçlar: "` içerir.
  - `test_gecmis_sonraki_turlarin_mesaj_dizisini_bozmaz`: tool çağıran bir koşuda ikinci modele giden `messages` geçmiş + soru + asistan(`response.content`) + `tool_result` sırasında.

- [ ] **Step 2: Çalıştır, kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent.py -q -k gecmis`
Expected: FAIL (`unexpected keyword argument 'history'`).

- [ ] **Step 3: `run_agent` imzasına `history: list[HistoryTurn] | None = None` ekle;** `messages` listesini `[*render_history(history or []), {"role": "user", "content": question}]` olarak kur. Docstring'e geçmişin yalnızca sunucunun ürettiği turlar olduğunu yaz.

- [ ] **Step 4: Çalıştır, yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_agent.py -q`
Expected: tümü PASS (mevcut agent testleri değişmeden).

- [ ] **Step 5: Commit**

```bash
git add backend/agent.py tests/test_agent.py
git commit -m "M8.2 - run_agent geçmiş parametresi"
```

---

### Task 3: `/chat` oturumu bağlar

**Files:**
- Modify: `backend/main.py` (`ChatRequest`, `run_chat`, `ChatStream`, `chat`)
- Test: `tests/test_chat.py` (yeni bölüm: `# --- Oturum geçmişi ---`; mevcut `chat` fixture'ı ve `FakeClient`'ı kullan)

**Interfaces:**
- Consumes: `STORE`, `Begin`, `HistoryTurn`, `SESSION_ID_PATTERN` (Task 1); `run_agent(..., history=...)` (Task 2).
- Produces:
  - `ChatRequest.session_id: str | None = None` (`Field(pattern=SESSION_ID_PATTERN)`; açık `null` kabul edilir), `model_config = ConfigDict(extra="forbid")`.
  - `run_chat(llm, message, version, emit, audit_id, *, history=None, session_id=None, session_reset=False) -> dict`; `done` verisine `session_id: str | None` ve `session_reset: bool` eklenir, dönen sözlüğe `"session_id"` ve `"turn_index"` girmez (bunları `ChatStream` bilir).
  - `ChatStream.__init__(..., session: Begin, history: list[HistoryTurn])`; `_record` içinde, sonuç `tamam` ise `STORE.add(session.session_id, {"question": self._message, "answer": result.text, "tool_calls": [...]})` (yalnızca `executed` çağrılar). Bu, istemci kopsa da döngü bitince (`client_disconnected=True` yolunda) çalışır.

- [ ] **Step 1: Failing testleri yaz** (`tests/test_chat.py`):
  - `test_ilk_istek_yeni_oturum_acar_ve_done_session_id_tasir`: `done` olayında `session_id` 32 hex, `session_reset is False`.
  - `test_ikinci_istek_ayni_oturumda_onceki_turu_modele_verir`: iki `POST /chat`; ikinci istekte `FakeClient.requests[-1]["messages"]` ilk mesajları önceki soru ve cevap metni, sonuncusu yeni soru.
  - `test_onceki_turun_tool_cagrilari_nota_girer_sonuclari_girmez`: ilk tur `get_flight_summary` çağırdı; ikinci isteğin mesajlarında araç adı ve argümanı var, zarfın `value` sayıları (`600`) önceki asistan mesajında **yok** (cevap metninde geçmiyorsa).
  - `test_bilinmeyen_session_id_reset_ve_yeni_id`: `session_id="a"*32` → 200, `session_reset is True`, yeni `session_id` farklı, hata yok.
  - `test_biçimsiz_session_id_422_model_cagrilmaz` (parametreli: `"x"`, `"A"*32`, `"a"*31`, `123`): 422, `FakeClient.requests == []`.
  - `test_fazla_govde_alani_422`: `{"message": "...", "history": []}` → 422.
  - `test_tamam_olmayan_tur_gecmise_girmez`: ilk tur `max_tokens` ile biter; ikinci istekte model mesajlarında ilk tur yok (yalnızca yeni soru).
  - `test_istemci_kopsa_da_tur_eklenir`: `tests/test_audit.py` › `drive_chat` kalıbıyla akış kesilir, döngü biter; sonraki istekte geçmişte tur var. (`TestClient` kesme testi yapamaz; ASGI ile sür.)
  - `test_haritadan_secim_gecmise_girmez`: `selected` ile giden turun kaydedilen `question`'ı yalnızca orijinal mesaj (`Haritada seçili:` yok).

- [ ] **Step 2: Çalıştır, kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chat.py -q -k "oturum or session or gecmis"`
Expected: FAIL.

- [ ] **Step 3: Uygula.** `chat` ucunda `STORE.begin(request.session_id)` ayar/talimat denetimlerinden **sonra** çağrılır (503 yolları oturum açmaz); `reset` yalnızca istek `session_id` taşıyıp oturum bulunamadıysa `True` (`begin` bunu döner). Geçmiş `STORE.history(session.session_id)` ile alınır ve `ChatStream`'e verilir. Mevcut `done` verisi karşılaştıran testleri (`test_chat.py`, `test_audit.py`, `test_citation.py`) yeni iki alanı kapsayacak şekilde güncelle.

- [ ] **Step 4: Çalıştır, yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chat.py tests\test_audit.py tests\test_citation.py -q`
Expected: tümü PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_chat.py tests/test_audit.py tests/test_citation.py
git commit -m "M8.2 - /chat oturum geçmişi"
```

---

### Task 4: Audit satırına oturum alanları

**Files:**
- Modify: `backend/audit.py:98-135` (`write_question`), `backend/main.py` (`_record` çağrısı)
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: `Begin` (Task 1), `ChatStream` içindeki `session` (Task 3).
- Produces: `write_question(..., session_id: str | None = None, turn_index: int | None = None)`; satıra `"session_id"` ve `"turn_index"` anahtarları yazılır. `turn_index` = istek anındaki kayıtlı tur sayısı + 1 (`Begin.turn_index`); `tamam` olmayan tur da kendi sırasını taşır.

- [ ] **Step 1: Failing testleri yaz:**
  - `test_question_satiri_session_id_ve_turn_index_tasir`: `/chat` sonrası satırda `session_id == done.session_id`, `turn_index == 1`.
  - `test_ikinci_turun_turn_index_iki`: aynı oturumda ikinci soru `turn_index == 2`.
  - `test_eski_satirda_alan_yoksa_rapor_okur`: elle yazılmış, bu iki alanı taşımayan satırı `scripts/audit_report.py` hatasız okur (`record.get`).
  - `test_gecmis_icerigi_audit_e_girmez`: satır JSON'unda önceki turun cevap metni `answer` alanı dışında geçmez.

- [ ] **Step 2: Kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_audit.py -q -k "session or turn_index or eski"`
Expected: FAIL.

- [ ] **Step 3: `write_question`'a iki anahtar kelime argümanı ekle, `ChatStream._record`'dan geçir.**

- [ ] **Step 4: Yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_audit.py -q`
Expected: tümü PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/audit.py backend/main.py tests/test_audit.py
git commit -m "M8.2 - audit satırına session_id ve turn_index"
```

---

### Task 5: Talimat v5 (ilke 14)

**Files:**
- Create: `backend/instructions/v5.md` (v4'ün birebir kopyası + ilke 14 paragrafı; dosya ≤ 40 satır)
- Modify: `backend/instructions/__init__.py` (`VERSIONS["v5"] = "5.0.0"`), `docs/system-talimat.md` (Değişiklik günlüğüne `5.0.0` satırı), `tests/test_instruction_v3.py` (parametre listelerine `"v5"`; `"v2", "v3", "v4"` listesine de)
- Test: `tests/test_instruction_v5.py`

**Interfaces:**
- Consumes: `instructions.load("v5")`, `instructions.VERSIONS`.
- Produces: `v5` seçilebilir sürüm (`COPILOT_INSTRUCTION=v5`); varsayılan sürüm **değişmez** (`DEFAULT_VERSION = "v3"`).

- [ ] **Step 1: Failing testleri yaz** (`tests/test_instruction_v5.py`, `test_instruction_v4.py` kalıbında):
  - `test_v5_v4un_tum_paragraflarini_aynen_icerir`: v4'ün her boş-satırla ayrılmış paragrafı v5'te bulunur.
  - `test_v5_tek_yeni_paragraf_ekler`: v5 paragraf sayısı = v4 + 1; yeni paragraf "Neden:" ile biter ve "önceki tur" ifadesini içerir.
  - `test_v5_yeni_ilke_sayiyi_tool_cagrisina_baglar`: yeni paragraf "tool" kelimesini içerir (önceki turdan sayı verilmez), kısa cevabın önceki sorunun cevabı olduğunu söyler, emin değilsen sormayı söyler.
  - `test_v5_dosya_40_satiri_asmaz`.
  - `test_v5_kayitli_ve_gunlukte`: `VERSIONS["v5"] == "5.0.0"`; `docs/system-talimat.md` günlüğünde `5.0.0` satırı.
  - `test_varsayilan_surum_v3_kalir`: `instructions.DEFAULT_VERSION == "v3"`.
  - Mevcut sürümlü testler (`test_operasyon_verisi_yok`, `test_snake_case_yalniz_kayitli_tool_adlari`, `test_hata_kodlari_zarftaki_kodlardan`, `test_zarf_alan_adlari_gecmez`) `v5` ile de geçer.

- [ ] **Step 2: Kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_instruction_v5.py tests\test_instruction_v3.py -q`
Expected: FAIL (`v5` yok).

- [ ] **Step 3: v5.md'yi yaz.** Yeni paragraf spec'teki üç maddeyi (sayı yalnızca bu turun tool'undan; kısa cevap önceki sorunun cevabıdır ve önceki araç notundaki tarifi koruyup yalnızca değişeni günceller; emin değilsen sor) "Neden:" cümlesiyle verir. Metinde rakam, `{}`, model adı, tool adı dışında `snake_case` ve zarf alan adı geçmez.

- [ ] **Step 4: Yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_instruction_v5.py tests\test_instruction_v3.py tests\test_instructions.py tests\test_prompts.py -q`
Expected: PASS; `test_prompts.py::test_talimat_kayitli_tool_adlarini_kullanir` bilinen kırmızı olarak kalır.

- [ ] **Step 5: Commit**

```bash
git add backend/instructions/v5.md backend/instructions/__init__.py docs/system-talimat.md tests/test_instruction_v5.py tests/test_instruction_v3.py
git commit -m "M8.2 - talimat v5 (geçmiş ilkesi)"
```

---

### Task 6: Arayüz: oturum, "Yeni konuşma", sıfırlanma notu

**Files:**
- Modify: `frontend/src/chat.ts` (`Done` tipi, `isDone`, `streamChat`), `frontend/src/Chat.tsx` (durum, düğme, not, başlık metni)

**Interfaces:**
- Consumes: `done` olayındaki `session_id: string`, `session_reset: boolean` (Task 3).
- Produces: `streamChat(message, handlers, selected = null, sessionId: string | null = null)`; gövde `session_id` yalnızca `sessionId !== null` iken gönderilir (açık `null` 422 verir). `Done.session_id: string`, `Done.session_reset: boolean`.

- [ ] **Step 1: `Done` tipine iki alan ekle, `isDone` doğrulasın** (`typeof data.session_id === 'string'`, `typeof data.session_reset === 'boolean'`; eksikse akış hatası).
- [ ] **Step 2: `Chat.tsx`'te `sessionId` durumu (`useState<string | null>(null)`):** `onDone` günceller; `ask` `streamChat`'e geçirir. `session_reset` true ise o turda tek satırlık not: "Önceki konuşma sıfırlandı; bu soru bağımsız yanıtlandı."
- [ ] **Step 3: "Yeni konuşma" düğmesi:** `sessionId`'yi `null` yapar ve `turns`'u temizler (cevap beklenirken pasif). Başlıktaki "Her soru bağımsız gönderilir…" notu, oturum açıklamasıyla değişir ("Konuşma bu sayfada sürer; 'Yeni konuşma' ile sıfırlanır.").
- [ ] **Step 4: Doğrula**

Run (frontend/): `npm run build; npm run lint`
Expected: derleme geçer, yeni lint uyarısı yok (`Map.tsx` uyarısı önceden vardır).

- [ ] **Step 5: `chat.ts` mantığını node ile sına** (CLAUDE.md › Kurallar: scratchpad'e kopya, import'lara `.ts`): geçerli `done` (iki yeni alanlı) `onDone`'a gider; `session_id` eksik `done` `onError(STREAM_MESSAGE)` çağırır; `streamChat` gövdesi `sessionId` null iken `session_id` içermez.
- [ ] **Step 6: Commit**

```bash
git add frontend/src/chat.ts frontend/src/Chat.tsx
git commit -m "M8.2 - arayüzde oturum ve yeni konuşma"
```

---

### Task 7: Belgeler ve son doğrulama

**Files:**
- Modify: `docs/chat.md` (Uç: `session_id`; Olay tipleri: `done` alanları; Talimat bölümüne v5; Arayüz kuralları; "Chat belleği yoktur" cümlesi), `docs/agent.md` (Girdi: `history`; Kapsam dışı: konuşma geçmişi maddesi), `docs/audit.md` (iki yeni alan), `docs/sorumluluk-zinciri.md` (Açık soru 1 kapanır, karar tabloya), `CLAUDE.md` (`backend/main.py`, `backend/agent.py`, `chat.ts` özetleri ve `backend/session.py` satırı)

- [ ] **Step 1: Belgeleri spec'le tutarlı güncelle** (tablolar: `done` `{"status","reason","turns","instruction","audit_id","session_id","session_reset"}`; sınırlar tablosu; "tool sonucu saklanmaz" kararı).
- [ ] **Step 2: Tam doğrulamayı atla**


- [ ] **Step 3: Gerçek model denemesi yapma.** Uçtan uca davranış Task 3'ün sahte istemcili testleriyle sınanır; tarayıcıda "Yeni konuşma" ve sıfırlanma notunu gerçek modelle denemek ücretlidir ve kullanıcının ayrı kararıdır, bu planın adımı değildir.
- [ ] **Step 4: Commit**

```bash
git add docs CLAUDE.md
git commit -m "M8.2 - oturum geçmişi belgeleri"
```
