# Kaynaklı Cevap Sözleşmesi

Bu belge `search_documents` tool'unun, atıf denetiminin ve talimat v3'ün tek kaynağıdır. Talimat sürümleri: v1 yürürlükte, v2 `docs/chat.md › Talimat v2`'de planlı, v3 bu belgeye göre yazılır. Eşik değeri burada yazılmaz: `.env`'den okunur (`COPILOT_RAG_ESIK`; `.env.example`'a tool kodlanırken eklenir).

## Tool

`search_documents` korpustaki belgelerde (Aerodrome Manual, SOP, yerel talimat, sözleşme özeti, SLA eki, eğitim materyali vb.; `docs/rag.md` §1) arama yapar.

| Girdi | Tür | Zorunlu | Açıklama |
|---|---|---|---|
| `query` | string | evet | Doğal dil sorgusu |
| `include_superseded` | bool | hayır (varsayılan `false`) | `true` ise eski sürümler de gelir |

**Açıklama (tool'a yazılacak, üç soru):**
- Ne döndürür: ilgili belge parçaları ve her parçanın belge, bölüm, revizyon, yürürlük tarihi, durum bilgisi.
- Ne zaman kullanılır: prosedür, kural, sınır ve politika soruları; "ne değişti" soruları (`include_superseded: true` ile).
- Ne zaman kullanılmaz: canlı uçuş, stand ya da konum bilgisi (bunlar uçuş tool'larının işi); sayıyı hesaplamak.

**Çıktı:** ortak zarf (sekiz alan: `value, source, as_of, filters, stale, tool_version, error, author`; `docs/zarf.md`). `source` değeri `data/korpus`.
`value` en fazla 5 parçanın listesi (`include_superseded: true` ise 8); sonuç yoksa `null`. Her parçada:

| Alan | Açıklama |
|---|---|
| `chunk_id` | `D03#02` biçiminde |
| `doc_id`, `title`, `section` | Belge ve bölüm |
| `revision`, `effective_from`, `status` | Sürüm bilgisi; `status`: `active` / `superseded` |
| `supersedes`, `superseded_by` | Kod hesaplar, model çıkarmaz |
| `authority`, `priority_level` | Kaynak düzeyi (`docs/hibrit.md › Kaynak önceliği`; düzey belgenin `type`'ından `TYPE_LEVELS` ile gelir) |
| `language`, `text` | Dil ve parça metni |

`search()` çıktısı `chunk_id, doc_id, revision, status, language, section, text` alanlarını taşır; tool `title`, `effective_from`, `authority`'yi ve `priority_level`'i hesaplamak için `type`'ı `chunk_id` ile `chunks.json`'dan ekler. `search()` çıktısı bu alanlar için değişmez.

**Skor modele gönderilmez.** Eşik için `search()` (M5.3'te) `vector` ve `hybrid` sonuçlarına ham vektör skorunu `vector_score` olarak ekler (iç çarpım; `bm25` sonucunda yoktur). Hibritte `score` RRF skoru olarak kalır, `vector_score` ayrıdır. Tool eşiği uyguladıktan sonra `vector_score`'u `value`'dan çıkarır. Kod henüz yok; ekleme `docs/hibrit.md › Yöntemler`'deki sonuç alanları paragrafında da belirtilir.

**Eşik:** dönen parçaların en yüksek `vector_score`'u `COPILOT_RAG_ESIK` değerinin altındaysa `value` `null`, `error.code` = `NOT_FOUND` döner. Eşik hibritin `score`'una (RRF) uygulanmaz. `bm25`'te `vector_score` olmadığı için tool `vector` ya da `hybrid` ile arar.

**Hatalar:**

| Kod | Yazan | Ne zaman |
|---|---|---|
| `NOT_FOUND` | `tool` | Eşik altı ya da sonuç yok. |
| `SCHEMA_VALIDATION_FAILED` | `layer` | Boş ya da eksik `query`; ek alan. |
| `SCHEMA_VALIDATION_FAILED` | `layer` | İndeks yok ya da okunamıyor, indeks modeli ayarlı modelden farklı, gömme isteği başarısız. `value: null`, `source: null`; ayrıntı yalnızca sunucu loguna yazılır (`docs/tools.md › Veri kaynağı`). `INDEX_NOT_READY` ve `INDEX_MODEL_MISMATCH` HTTP kodlarıdır, zarf kodu değildir. |

## Atıf

- Kaynağa dayanan her cümlenin sonuna parçanın `chunk_id` değeri köşeli parantezle yazılır: `[D03#02]`. Talimat metni rakam taşıyamadığı için (`docs/system-talimat.md › Yazım kuralları`) örneği `[<chunk_id>]` yer tutucusuyla verir.
- Model yalnızca tool'dan gelen kimlikleri yazar. Belge adı, bölüm, revizyon ve tarihi **yazmaz**; bunları kod ekler.
- Sayı, süre ve mesafe yalnızca parça metninden alınır.
- Kod, cevaptaki etiketleri bu koşuda getirilen parçalarla eşleştirir. Eşleşmeyen etiket `dogrulandi: false` olur.
- Tool çağrılmış, parçalar gelmiş ve cevapta hiç etiket yoksa `atifsiz: true`.
- Tool hiç çağrılmadıysa atıf borcu yoktur.
- `dogrulandi` ve `atifsiz` alanlarının yeri (agent sonucu, audit satırı) `docs/agent.md` ve `docs/audit.md`'de netleştirilecek; bu belge yer belirlemez.

## Sürüm

- Varsayılan arama yalnızca `status: active` parçaları getirir.
- Kullanıcı eski sürümü ya da değişikliği soruyorsa model `include_superseded: true` ile arar.
- Cevapta `superseded` bir parça kullanılıyorsa açıkça "eski sürüm" diye anılır; güncel kural olarak sunulmaz.
- Değişiklik sorusunda iki sürüm yan yana anlatılır; ikisi de atıflıdır.

## Çelişki ve öncelik

- İki kaynak aynı soruya farklı cevap veriyorsa model sessizce birini seçmez.
- Cevap: (1) iki kaynağı da gösterir, her biri için belge, revizyon, yürürlük tarihi ve kaynak düzeyi; (2) üst düzey kaynağı söyler; (3) "teyit gerekir" der.
- Bağlayıcı olmayan rehberler (eğitim materyali) bağlayıcı belgeyle çelişirse bağlayıcı belge esas alınır; rehber "bağlayıcı olmayan rehber" diye anılır.

## Bilmiyorum

- Tool `NOT_FOUND` döndürürse cevap: "Belgelerde bu konuda kaynak bulamadım." Tahmin yok, hafızadan cevap yok.
- Parçalar geldi ama soruyu cevaplamıyorsa aynı cümle kullanılır.
- Cevap dili Türkçedir. İngilizce kaynak kullanılırsa özeti Türkçe verilir, etiket korunur.
