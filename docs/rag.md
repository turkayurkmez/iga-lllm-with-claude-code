# RAG hattı (M5.1)

Belge korpusunu parçalayan, gömen ve arayan hattın sözleşmesi. Bu modülde yalnızca **arama** vardır: modele hiçbir parça gönderilmez, cevap üretilmez. Agent'a bağlama, citation ve sürüm/çelişki yönetimi M5.3'tedir.

## 1. Kapsam

Korpus: `data/korpus/` altında 15 kurgusal belge. Kod: `backend/rag/`. Komutlar: `scripts/rag_parcala.py`, `scripts/rag_indeksle.py`, `scripts/rag_ara.py`. İndeks: `data/indeks/` (git'e girmez).

## 2. Belge biçimi

Her belge `data/korpus/Dnn.md`, UTF-8 (BOM'suz). Dosyanın başında `---` satırları arasında tek satırlık `anahtar: değer` çiftleri bulunur (iç içe yapı ve liste yoktur). Zorunlu anahtarlar: `doc_id`, `title`, `type`, `authority`, `airport`, `language` (`tr` veya `en`), `revision`, `effective_from` (YYYY-MM-DD), `status` (`active` veya `superseded`). Başka anahtarlar (örneğin `supersedes`) olabilir. Gövde Markdown'dır: `#` ile `###` arası başlıklar, düz paragraflar, Markdown tabloları, numaralı listeler (`1.`, `2.`). Gövdenin ilk ve son satırı `**KURGUSAL — EĞİTİM AMAÇLI**` damgasıdır (front matter dosyanın en başında kalır); damga satırları parça metnine girmez.

## 3. Parçalama (chunk) kuralları

1. Belge başlıklara göre bölünür; her bölüm ayrı bir parça adayıdır. Bölümün yolu (`Ana başlık > Alt başlık`) parçanın `section` alanıdır.
2. Hedef üst sınır **1200 karakter**. Sınırı aşan düz metin bölümü paragraf sınırlarından bölünür; paragraf ortasından bölünmez; tek paragraf sınırı aşarsa cümle sınırından bölünür.
3. **Markdown tablosu bölünmez:** başlık satırı, ayırıcı satır ve tüm satırlar tek parçada kalır. Parça 1200'ü aşabilir.
4. **Numaralı prosedür bölünmez:** art arda gelen numaralı adımların tamamı tek parçada kalır. Parça 1200'ü aşabilir.
5. Tablonun ya da prosedürün hemen öncesindeki tanıtıcı paragraf onunla aynı parçada kalır.
6. Örtüşme yoktur.
7. Her parça belgenin front matter alanlarını aynı adlarla taşır, ayrıca: `chunk_id` (`<doc_id>#<nn>`, belge içinde iki haneli sıra numarası, deterministik), `section`, `text` (yalnızca gövde) ve `context` (`[<doc_id> · <title> · <section>]`).
8. Gömülen metin `context`, bir satır sonu ve `text`'in birleşimidir; arama sonucunda `text` ve `context` ayrı gösterilir.
9. Aynı belge iki kez bölününce aynı parçaları ve aynı kimlikleri verir.

## 4. Gömme (embedding)

- Sağlayıcı: Voyage AI. Anahtar `.env`'de `VOYAGE_API_KEY`, model adı `.env`'de `COPILOT_EMBED_MODEL` (koda gömülmez).
- Gömme **tek bir yerden** çağrılır; sağlayıcıyı yalnızca o katman bilir.
- Belge parçaları `input_type="document"`, sorular `input_type="query"` ile gömülür.
- İstekler en çok 128 metinlik gruplarla gönderilir. Hız sınırında (429) bekleyip yeniden dener, en çok 5 deneme. Başarısız olursa indeks **yazılmaz** (yarım indeks yok; yazma geçici dosya + yeniden adlandırma ile yapılır).
- Vektörler birim uzunluktadır; benzerlik iç çarpımdır.
- Sistem saati okunmaz (M2.2 kuralı): `meta.json`'da zaman damgası yoktur.

## 5. İndeks dosyaları (`data/indeks/`)

| Dosya | İçerik |
|---|---|
| `chunks.json` | Parça listesi (§3 alanları), sıra `vektorler.npy` ile aynı |
| `vektorler.npy` | float32, şekil (parça sayısı, boyut) |
| `meta.json` | `model`, `dimension`, `chunk_count`, `corpus_sha256` (korpus dosyalarının birleşik özeti), varsa `total_tokens` |

## 6. Arama

Girdi: soru metni, `k` (varsayılan 5), isteğe bağlı filtreler: `status`, `language`, `type`, `doc_id`. Filtre benzerlikten **önce** uygulanır. Soru `input_type="query"` ile gömülür. Sonuç: skor (iç çarpım, azalan; eşitlikte `chunk_id` artan), `chunk_id`, `doc_id`, `revision`, `status`, `language`, `section`, `text`. Filtre hiçbir parça bırakmazsa boş liste döner (hata değil). İndeksin `model` değeri `.env`'deki modelden farklıysa arama **reddedilir.** Skor eşiği yoktur (M5.3).

## 7. HTTP

`GET /rag/search?q=&k=&status=&language=&type=&doc_id=`

| Durum | HTTP | Gövde |
|---|---|---|
| Başarılı | 200 | `{"query", "k", "filters", "results": [...]}` (§6 alanları) |
| `q` boş ya da `k` 1–20 dışında | 422 | doğrulama hatası |
| İndeks yok | 503 | `{"error": {"code": "INDEX_NOT_READY", "message": "..."}}` |
| İndeks modeli farklı | 503 | `{"error": {"code": "INDEX_MODEL_MISMATCH", "message": "..."}}` |

Bu uç zarf değildir; M5.3'te tool olurken zarfa girer.

## 8. Kurallar

1. Testler ağa çıkmaz ve `.env`'e ihtiyaç duymaz; gömme sahte vektörlerle test edilir.
2. Korpus yalnızca eğitmen tarafından değiştirilir; kod ona dokunmaz.
3. `.env` okunmaz, içeriği yazdırılmaz, günlüğe girmez.
4. Model değişince indeks yeniden kurulur.

## Kapsam dışı (bu modülde)

Anahtar kelime ve hibrit arama, reranker, kaynak önceliği (M5.2); modele parça göndermek, citation, "bilmiyorum", sürüm ve çelişki yönetimi (M5.3); operasyonel hafıza, emsal arama, RAG ölçümü (M5.4); injection savunması (Gün 6); vektör veritabanı.
