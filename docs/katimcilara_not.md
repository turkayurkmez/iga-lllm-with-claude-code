# Katılımcılara Not

Bu eğitimde **AOCC Copilot** adlı gerçek bir uygulamayı adım adım geliştirdik: havalimanı Operasyon Kontrol Merkezi (AOCC) personeli için Claude tabanlı, tool kullanan bir asistan. Aşağıda konular geliştirme sırasıyla (kilometre taşı = M) verilmiştir. Her başlıkta ne yaptığımız, öğrenme çıktıları ve repoda bakılacak yer vardır.

Genel fikir tek cümlede: **Model akıl yürütür ve konuşur; sayıyı, durumu ve hesabı servis (deterministik kod) üretir; her şey sözleşmeyle ve testle bağlanır.**

---

## M1 — Temel: API, durumsuzluk, sorumluluk sınırı

**Yaptıklarımız:** Repo ve ortam kurulumu (Python 3.13, `.venv`, `.env`), Anthropic SDK ile ilk çağrı; üç deney: durumsuzluk, aritmetik, sıcaklık. Bulgular `docs/sorumluluk-zinciri.md` tablosuna (GÖZLEM / KARAR) işlendi. `CLAUDE.md` ilk kez yazıldı.

**Öğrenme çıktıları**
- Tek config/istemci noktası (`backend/llm.py`) kurmayı, anahtar ve model adını koda gömmemeyi açıklar.
- LLM API'sinin **durumsuz** olduğunu gösterir; geçmişi kimin tutması gerektiğini ve token maliyetinin geçmişle nasıl büyüdüğünü yorumlar.
- Modelin sayı toplayabilse bile hesabın neden servise bırakıldığını gerekçelendirir.
- Güncel modellerde `temperature` parametresinin kısıtını bilir (`extra_body` ile gönderme, 400 hatası).
- Deneyden bulguya, bulgudan karara giden izlenebilir bir karar tablosu tutar.

Bakılacak yer: `scripts/stateless.py`, `calc_number.py`, `temperature.py`, `docs/sorumluluk-zinciri.md`.

## M2 — Spec, geliştirme disiplini, sentetik veri, tool use

**Yaptıklarımız:**
- Spec yazımı (`docs/spec.md`), docker compose (Postgres + backend), `db/schema.sql`.
- Claude Code ile çalışma düzeni: `CLAUDE.md`, **hook** (`prompt-gate`) ve **skill** (`prompt-netlestir`) ile prompt netleştirme (Amaç / Bağlam / Veri / Kısıt / Format).
- **Sentetik veri üreteci** (`synth/generator.py`): belirlenimci (seed), sabit senaryo kayıtları; **bozulma** senaryoları (`synth/corruption.py`) ve simüle **akış** (`synth/stream.py`).
- **Tool use**: tool açıklamasının kalitesi modelin seçimini nasıl değiştirir (`experiments/function_calling/`, kötü vs. iyi tanım, 12 soru × 3 tekrar ölçümü).
- **Zarf (envelope)**: tool çıktısının ortak biçimi (`docs/zarf.md`, `backend/envelope.py`): 8 sabit alan, 5 hata kodu, `as_of`/`stale`'in katmanca hesaplanması.

**Öğrenme çıktıları**
- Sözleşmeyi (spec/belge) koddan önce yazıp testle bağlamayı uygular (sözleşme testi önce, kırmızı → yeşil).
- Hook ve skill'in farkını, hangisinin ne zaman devreye girdiğini açıklar.
- Belirlenimci sentetik veri üretmenin (sistem saati, `set` sırası, `hash()` yasağı) test edilebilirlik için neden gerekli olduğunu anlatır.
- Veri bozulması (bayat konum, eksik alan) senaryolarıyla sistemin dayanıklılığını sınar.
- İyi tool tanımının bileşenlerini (ne döndürür / ne zaman kullanılır / ne zaman KULLANILMAZ, enum, örnek) sayar ve ölçerek kanıtlar.
- Ortak zarf sayesinde modelin "veri yok", "bayat", "hata" durumlarını ayırt edebildiğini gösterir.

## M3 — Tool katmanı, subagent, frontend iskeleti, tool döngüsü

**Yaptıklarımız:** Uçuş tool'ları (`backend/tools/`, tek doğruluk kaynağı `contracts/<tool>.json`, `run_tool` hiç istisna fırlatmaz); jsonschema ile argüman doğrulama; PostToolUse hook'u (tool değişince testleri koşar); `tool-definition-auditor` **subagent**'ı; Vite + React + TypeScript iskeleti; **tool loop** (model → tool → sonuç → model).

**Öğrenme çıktıları**
- Kontrat-öncelikli tool tasarımı yapar; şema kurallarını (`additionalProperties: false`, `pattern` ile biçim) uygular.
- Tool'un hata vermesi ile hatanın zarfta taşınması arasındaki farkı açıklar.
- Salt okunur bir subagent ile tool tanımlarını denetletir.
- Tool kullanım döngüsünü (`stop_reason`, `tool_use` / `tool_result` blokları, `is_error`) elle kurar.

## M4 — Sistem talimatı, agent döngüsü, `/chat`, denetim kaydı

**Yaptıklarımız:**
- **Sistem talimatı** sürümleri (`backend/instructions/v1…`), sözleşmesi ve testi (`docs/system-talimat.md`).
- **Agent döngüsü** (`backend/agent.py`): beş bitiş durumu, `MAX_TURNS`, tekrar sınırı; API'siz sahte istemciyle test.
- **`/chat` SSE akışı** (`docs/chat.md`): `tool_call`, `source_chip`, `kpi_card`, `selection_card`, `text_delta`, `done` / `error` olayları.
- Frontend sohbet ekranı (SSE istemcisi, kartlar, kaynak çipleri).
- **Audit**: her soru için JSONL satırı, thumbs down geri bildirimi (`docs/audit.md`).

**Öğrenme çıktıları**
- Sistem talimatını sürümleyip değişiklik günlüğüyle yönetir; talimat değişince testlerin nasıl etkilendiğini görür.
- Agent döngüsünün sonsuz döngüye karşı sınırlarını (iterasyon, tekrar) tasarlar.
- SSE ile akış tasarlar; olay sözleşmesini hem sunucuda hem istemcide doğrular.
- Model hatasında ayrıntıyı istemciye sızdırmama ilkesini uygular.
- Kullanıcıya gösterilen her şeyin denetlenebilir kaydını (kim ne sordu, hangi tool'lar, hangi cevap) tutar.

## M5 — Harita, canlı akış, MQTT

**Yaptıklarımız:** SVG harita (`Map.tsx`), stand verisi (`GET /map/stands`); harita tool'ları ve `map_command` olayı; canlı konum hattı: yayıncı → **Mosquitto (MQTT)** → tüketici → `GET /live/positions` **SSE** → harita (`docs/canli_akis.md`, `docs/harita.md`); bayatlık kuralı (5 dk), simülasyon saati `clock` topic'inden; harita seçiminin sohbete bağlam olarak eklenmesi.

**Öğrenme çıktıları**
- Pub/sub (MQTT) ile istek/yanıt (HTTP) mimarilerini ayırt eder.
- "Sunucu ne diyorsa o çizilir" ilkesini uygular: yaş, bayatlık ve saat istemcide hesaplanmaz.
- Kesinti ve bayat veri durumunda arayüzün dürüst davranmasını (sahte tazelik göstermeme) tasarlar.
- Arayüz durumunu (seçim, harita komutu) modele bağlam olarak taşıyan bir akış kurar.

## M6 — RAG: gömme, arama, hibrit, kaynaklı cevap

**Yaptıklarımız:**
- Belge korpusu ve parçalama (chunking); **Voyage AI** ile gömme; yerel indeks kurucu (atomik yer değiştirme, `docs/rag.md`).
- Vektör arama ve `GET /rag/search`; **BM25**; **hibrit arama (RRF)**; **kaynak önceliği** (belge türü / sürüm), `superseded` belgeler (`docs/hibrit.md`).
- Alaka eşiği (`COPILOT_RAG_ESIK`) ve "bilmiyorum" davranışı.
- `search_documents` tool'u, **atıf** etiketleri (`[D03#02]`), talimat v2 / v3 (`docs/kaynakli.md`).
- Değerlendirme soruları (`eval/arama_sorulari.json`, `eval/kaynakli_sorulari.json`).

**Öğrenme çıktıları**
- RAG hattının her adımını (parçala → göm → indeksle → ara → sırala → atıfla) açıklar ve her adımı ayrı test eder (ağsız, sahte istemciyle).
- Vektör, BM25 ve hibrit aramanın hangi sorgu türünde neden farklı sonuç verdiğini ölçerek gösterir.
- Eski sürüm belgenin yanlış cevaba yol açma riskini, kaynak önceliğiyle nasıl yönettiğini anlatır.
- Eşik altında "kaynak bulunamadı" demenin uydurmaya tercih edildiğini gerekçelendirir.
- Atıfı üretmekle **doğrulamak** arasındaki farkı kavrar: atıf, bu koşuda gerçekten getirilen parçalarla eşlenir.

## M7 — Ölçüm, güvenlik (prompt enjeksiyonu), MCP

**Yaptıklarımız:**
- **RAG ölçümü** (`docs/rag_olcum.md`): recall@5, cevaplanabilirlik, citation precision, eski sürüm kullanımı, atıfsız cümle oranı; ham kayıttan saf skor hesabı.
- **Prompt enjeksiyonu savunması** (`docs/enjeksiyon.md`, E1–E7): tool sonucunun `<belge>` ile sınırlanması, indeks zamanı tarama ve karantina, mesaj uzunluk sınırı, talimat v4, audit işaretleri, saldırı seti ve koşucusu; inceleme düzeltmeleri (Türkçe büyük/küçük harf katlama, ReDoS, gizli Unicode).
- **MCP sunucusu** (`mcp_server/`, `docs/mcp.md`): uçuş tool'ları stdio üzerinden başka istemcilere açıldı.

**Öğrenme çıktıları**
- "İyi görünüyor" yerine metrik tanımlar ve golden set ile ölçer; ölçüm yöntemini (neyin ihlal sayılmadığı dahil) önceden yazar.
- Dolaylı prompt enjeksiyonunun nasıl işlediğini gösterir ve katmanlı savunma kurar (sınırlama, tarama, talimat, denetim izi).
- Saldırı seti ile savunmayı **ölçülebilir** hale getirir; talimat sürümü geçişini ölçüme bağlar.
- Kod incelemesinden çıkan güvenlik düzeltmelerini (ReDoS, Unicode hileleri) test ile kalıcılaştırır.
- Aynı tool'ları HTTP, sohbet ve MCP üzerinden tek kontrattan sunmanın değerini anlatır.

## M8 — Oturum geçmişi ve genel grafik sorgusu

**Yaptıklarımız:**
- **Sunucu tarafı oturum geçmişi** (`backend/session.py`, `docs/chat.md › Oturum`): bellekte, son 6 tur / 12000 karakter; `session_id`, "Yeni konuşma"; talimat v5 (geçmiş ilkesi); audit satırına `session_id` ve `turn_index`. M1'deki durumsuzluk bulgusu burada kapandı.
- **Genel grafik sorgusu** (`get_chart_data`, kontrat 2.0.0): düz uçuş görünümü, sorgu motoru ve tarif denetimi; arayüzde tür başına grafik seçenekleri. Sayı, yüzde ve değişimi tool hesaplar; model ve arayüz hesaplamaz.

**Öğrenme çıktıları**
- Geçmiş yönetiminde "ne saklanır, ne kadarı modele gider, tool sonuçları neden saklanmaz" kararlarını gerekçelendirir.
- Esnek ama güvenli bir sorgu arayüzünü (modelin yazdığı sorgu tarifi → servisin denetleyip çalıştırması) tasarlar.
- Eski bir deney bulgusunu (durumsuzluk) mimari kararla kapatıp belgelere geri işler.

---

## Baştan sona geçen ilkeler

| İlke | Nerede göreceksiniz |
|---|---|
| Sayı ve durumu servis üretir, model uydurmaz | zarf, tool'lar, grafik sorgusu, `unverified_numbers` |
| Önce sözleşme, sonra test, sonra kod | `docs/*.md` ↔ `tests/test_*.py` |
| Gerçek model çağrısı ücretlidir; testler API'siz | sahte istemci, sahte Voyage |
| Hata ayrıntısı istemciye gitmez, sunucu loguna yazılır | `/chat`, `/tools`, `/rag` |
| Her davranış değişikliği ölçülür | `eval/`, `scripts/*_kos.py` |
| Belgeler ve kod birlikte güncellenir | `CLAUDE.md`, değişiklik günlükleri |

## Kendinizi sınayın

1. Neden konuşma geçmişini model değil sunucu tutar? Hangi bulgu bunu gösterdi?
2. Bir tool tanımındaki "ne zaman KULLANILMAZ" cümlesi neden modelin davranışını değiştirir?
3. Zarfta `stale` ve `as_of` alanlarını neden tool değil katman hesaplar?
4. Hibrit arama hangi sorguda vektör aramadan, hangisinde BM25'ten üstündür?
5. Bir belge parçasına gizlenmiş "önceki talimatları unut" metnine karşı hangi dört savunma katmanı vardır?
6. Grafikteki yüzde değişimini kim hesaplar ve neden?
