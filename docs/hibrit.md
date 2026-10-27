# Hibrit arama (M5.2)

`backend/rag/` içindeki aramanın sözleşmesi. M5.1'in vektör araması değişmez; BM25, hibrit ve kaynak önceliği onun yanına eklenir. Parça ve metadata biçimi `docs/rag.md`'dedir.

## Yöntemler

| `method` | Ne yapar |
|---|---|
| `vector` | M5.1'deki arama. Varsayılan. |
| `bm25` | Anahtar kelime araması (aşağıda). Gömme çağrısı yapmaz, model uyuşmazlığına bakmaz. |
| `hybrid` | İki yöntemin sıralarını RRF ile birleştirir. Vektör tarafı için gömme çağrısı yapar ve model uyuşmazlığında `vector` gibi reddeder. |

`search()`, `GET /rag/search` ve `scripts/rag_ara.py` (`--method`) aynı `method` seçeneğini alır; geçersiz değer `ValueError`, HTTP'de 422 olur. `status`, `language`, `type` ve `doc_id` filtreleri üç yöntemde de aynı çalışır. M5.1'in sonuç alanları değişmez; `score` alanı yöntemin kendi skorudur (hibritte birleşik skor). `vector` ve `hybrid` sonuçları ayrıca ham vektör skorunu `vector_score` olarak taşır (`bm25`'te yok; `docs/kaynakli.md › Tool`). Üç yöntemde de eşit skorda `chunk_id` artan sıralanır (`docs/rag.md` §6); hibritte bunun önüne "vektör sırası önce" kuralı geçer (aşağıda).

## BM25 için metin hazırlama

Parça metni ve sorgu aynı adımlardan geçer:

1. Kesme işaretinden sonraki ek atılır, düz (`'`) ve kıvrık (`’`) ikisi de: `stand'ına` → `stand`, `TK2345'in` → `tk2345`.
2. Harf ve rakam dizileri sözcüktür.
3. Türkçe-duyarlı küçük harf ve ASCII'ye indirme: `İ`, `I`, `ı` → `i`; `ç ş ğ ü ö` → `c s g u o`. `İSTANBUL` ile `istanbul` aynı sözcüktür.
4. Rakam içermeyen sözcüklerde yalnızca ilk 5 harf alınır: `arızası` → `ariza`, `köprüsü` → `kopru`. Rakam içeren sözcükler kısaltılmaz: `TK2345` ile `TK2346` farklı seferlerdir.
5. Durdurma listesi yok.

Bilinen sınır: 4 harfli kökler ekli halleriyle eşleşmez (`uçuş` ile `uçuşlarda`).

Testlerin kapsayacağı örnekler:

| Girdi | Sonuç |
|---|---|
| `İSTANBUL` ve `istanbul` | aynı sözcük |
| `arıza` ve `arızası` | aynı sözcük |
| `stand'ına` ve `stand` | aynı sözcük |
| `TK2345` ve `TK2346` | farklı sözcük |
| `Düşük görüş` | `dusuk`, `gorus` |
| Hiç ortak sözcük | sonuç listesi boş |

## BM25 skoru

Okapi BM25, `k1 = 1.5`, `b = 0.75`. `idf = ln(1 + (N − n + 0.5) / (n + 0.5))`; `N` indeksteki parça sayısı, `n` sözcüğün geçtiği parça sayısı. `idf` ve ortalama parça uzunluğu indeksteki tüm parçalardan hesaplanır; filtreye uyan parçalar arasında sıralama yapılır. Skoru 0 olan parça sonuç değildir; hiçbir sözcük eşleşmezse liste boştur. BM25 tablosu her aramada, `search()`'ün o çağrıda okuduğu parçalardan bellekte kurulur; süreç önbelleği ve diske yazılan dosya yoktur (vektör araması da indeksi her çağrıda okur; `rag_indeksle.py` sunucu çalışırken indeksi yenilese bile arama eski veriye bakmaz).

## Hibrit

Her iki yöntemden, filtreye uyan ilk 20 aday alınır. Birleşik skor: `score = Σ 1 / (60 + sıra)`; sıra 1'den başlar, parça bir listede yoksa o listenin terimi eklenmez. Eşit skorda vektör sırası önce gelir; vektör listesinde olmayanlar kendi aralarında `chunk_id` artan sıralanır. İlk `k` parça döner (`k` varsayılan 5, en çok 20). Aday sayısı (20) ve sabit (60) `search()` argümanlarıyla ayarlanabilir; varsayılanlar bunlardır.

## Kaynak önceliği

`priority` seçeneği yalnızca `hybrid`'de vardır ve varsayılan kapalıdır (`false`); kapalıyken sıralama hiç değişmez. `vector` ya da `bm25` ile açılırsa `ValueError` (HTTP'de 422, `scripts/rag_ara.py --priority` için `Hata:` ve çıkış kodu 1) olur; gömme çağrısı yapılmaz. `false` her yöntemde kabul edilir. Açıkken: `score = birleşik skor × çarpan`, `çarpan = 1.00 − 0.03 × (düzey − 1)`; çarpan uygulandıktan sonra liste yeniden sıralanır, `k` bu sıralamadan sonra uygulanır. Eşit skorda hibritteki kural sürer (vektör sırası önce, sonra `chunk_id`). Düzey, belgenin `type` değerinden gelir (`backend/rag/search.py › TYPE_LEVELS`):

| `type` | Düzey |
|---|---|
| `aerodrome_restrictions` | 2 |
| `aerodrome_manual` | 3 |
| `sop`, `local_instruction`, `temporary_note`, `sla_annex`, `agreement_summary` | 4 |
| `training_material`, `operational_memory`, `facility_rules` | 5 |

Listede olmayan `type` düzey 1 sayılır (çarpan 1.00): yeni bir tür sessizce cezalanmaz ya da öne alınmaz; tabloya eklenene kadar öncelik farkı yoktur.

| Düzey | Çarpan | Belgeler |
|---|---|---|
| 1 | 1.00 | korpusta yok (yürürlükteki bağlayıcı düzenleme) |
| 2 | 0.97 | D07 |
| 3 | 0.94 | D01, D02, D03 |
| 4 | 0.91 | D04, D05, D06, D08, D10, D11, D12 |
| 5 | 0.88 | D09, D13, D14, D15 |

Çarpan filtre değildir: yalnızca düşük öncelikli bir belgenin cevap verdiği soruda o belge yine görünür. Çarpan yalnızca birbirine yakın skorları ayırır.

## HTTP

`GET /rag/search` (`docs/rag.md` §7) iki sorgu parametresi alır: `method` (`vector`, `bm25`, `hybrid`; varsayılan `vector`) ve `priority` (`true`/`false`). Geçersiz `method` ya da `hybrid` dışında `priority=true` 422 döner. 200 gövdesine `method` ve `priority` eklenir: `{"query", "k", "method", "priority", "filters", "results"}`. M5.1 gövdesi (`vector`) değişmez: `method` yalnızca `vector` dışında, `priority` yalnızca `hybrid` gövdesinde bulunur (`bm25` gövdesinde `method` var, `priority` yok). `bm25` gömme çağrısı yapmadığı için `INDEX_MODEL_MISMATCH` ve gömme hatası üretmez; `INDEX_NOT_READY` yine olur.

## Ölçüt

- **recall@5:** sorunun `beklenen_belge` listesinden, ilk 5 parçada görünen belgelerin oranı. Belge düzeyinde; aynı belgenin birden çok parçası bir kez sayılır. Soru tipi başına ortalama alınır.
- **İlk sıra doğru:** yalnızca `oncelik` tipindeki sorularda: ilk parçanın belgesi `ilk_beklenen` ile aynı mı. Sonuç `n/3` olarak yazılır.

Sorular `eval/arama_sorulari.json`'dadır; bu dosya ölçümler karşılaştırılabilir kalsın diye değiştirilmez.

Tablo biçimi (`scripts/rag_karsilastir.py` yazar, `eval/out/` altına da kaydeder; `eval/out/` `.gitignore`'dadır ve var olan sonuç dosyasının üzerine yazılmaz, `eval.run` gibi):

| Yöntem | Kelime | Anlam | Çapraz dil | Öncelik | Tümü | İlk sıra doğru |
|---|---|---|---|---|---|---|
| `bm25` | | | | | | |
| `vector` | | | | | | |
| `hybrid` | | | | | | |
| `hybrid + priority` | | | | | | |

Satırlar bu dört yöntemdir; `hybrid + priority` satırı `hybrid`'in `priority` açık halidir (`hybrid` satırı kapalı halidir). Değerleri `rag_karsilastir.py` ölçer, belgeye elle yazılmaz. Sütunlar 0.00–1.00 arası recall@5; `Tümü`, tüm soruların ortalamasıdır (tip ortalamalarının ortalaması değil). Tipte soru yoksa hücre `-` olur. `rag_karsilastir.py` gerçek Voyage çağrısı yapar (ücretli), `rag_ara.py` gibi docstring'inde bunu belirtir.

`rag_karsilastir.py` tabloyu stdout'a, gömme özetini ve sonuç yolunu stderr'e yazar; sonuç dosyası (`--out`, varsayılan `eval/out/arama_karsilastirma.json`) `model`, `k`, `satirlar` ve soru başına ilk 5 `chunk_id` (`sonuclar`) içerir. Ücretli istekten önce soru dosyası, `--out` ve indeks (hazır mı, modeli ayarlı modelle aynı mı) denetlenir; biri bozuksa istek yapılmaz. Dört satır da aynı vektörleri kullanır: gömme yalnızca bir kez, önbellekte olmayan sorgular için ve tek istekle yapılır.

## Önbellek ve istek sayısı

Sorgu vektörleri `data/sorgu_onbellegi.json` içinde, model ve sorgu metni anahtarıyla tutulur. Dosya indeks klasörünün **dışındadır**: arama indeksi değiştirmez ve `build_index` klasörü yerine koyarken önbellek silinmez. `.gitignore`'a eklenir. Yolu `INDEX_DIR`'den bağımsız bir modül değişkenidir, testler tmp'ye yönlendirir. Gömme yalnızca `backend/rag/embed.py`'den çağrılır; önbellek ve toplu sorgu gömme (en çok 128 sorgu bir istekte, `BATCH_SIZE`) orada durur. Önbellekte olmayan sorgular tek istekle gömülür: `embed.embed_queries(texts, client=None, model=None, cache_path=None)` benzersiz sorguları dedupe eder, yalnızca eksikleri gönderir (`QueryVectors.fetched` kaç sorgunun gittiğini söyler), hepsi önbellekteyse istemci kurmaz. Dosya biçimi `{model: {sorgu: [vektör]}}`; `embed_query` (tek soru, `search()` yolu) önbelleği kullanmaz, `rag_karsilastir.py` kullanır. Dosya zaman damgası taşımaz (`docs/rag.md` §4). Yazma geçici dosya + `os.replace` ile yapılır ve `index.py › _replace` gibi `PermissionError`'da 5 kez yeniden dener (`/rag/search` thread havuzunda çalışır). Önbellek bozuksa ya da okunamıyorsa yok sayılır ve sorgu yeniden gömülür; yazılamıyorsa arama yine de sonuç döner. Testler ağa çıkmaz, `.env`'e ihtiyaç duymaz.

## Kapsam dışı (bu modülde)

Agent'a bağlama ve tool zarfı, citation, "bilmiyorum" eşiği, sürüm farkı ve çelişki yönetimi (M5.3), reranker.
