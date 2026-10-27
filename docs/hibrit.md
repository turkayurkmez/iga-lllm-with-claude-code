# Hibrit arama (M5.2)

`backend/rag/` içindeki aramanın sözleşmesi. M5.1'in vektör araması değişmez; BM25, hibrit ve kaynak önceliği onun yanına eklenir. Parça ve metadata biçimi `docs/rag.md`'dedir.

## Yöntemler

| `yontem` | Ne yapar |
|---|---|
| `vektor` | M5.1'deki arama. Varsayılan. |
| `bm25` | Anahtar kelime araması (aşağıda). |
| `hibrit` | İki yöntemin sıralarını RRF ile birleştirir. |

`GET /rag/search` ve `scripts/rag_ara.py` aynı `yontem` seçeneğini alır. Durum, dil ve tür filtreleri üç yöntemde de aynı çalışır. M5.1'in sonuç alanları değişmez; `skor` alanı yöntemin kendi skorudur (hibritte birleşik skor).

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

Okapi BM25, `k1 = 1.5`, `b = 0.75`. `idf = ln(1 + (N − n + 0.5) / (n + 0.5))`; `N` indeksteki parça sayısı, `n` sözcüğün geçtiği parça sayısı. `idf` ve ortalama parça uzunluğu indeksteki tüm parçalardan hesaplanır; filtreye uyan parçalar arasında sıralama yapılır. Skoru 0 olan parça sonuç değildir; hiçbir sözcük eşleşmezse liste boştur. İndeks bellekte, ilk aramada kurulur; diske yazılmaz.

## Hibrit

Her iki yöntemden, filtreye uyan ilk 20 aday alınır. Birleşik skor: `skor = Σ 1 / (60 + sıra)`; sıra 1'den başlar, parça bir listede yoksa o listenin terimi eklenmez. Eşit skorda vektör sırası önce gelir. İlk 5 parça döner. Aday sayısı (20) ve sabit (60) ayarlanabilir; varsayılanlar bunlardır.

## Kaynak önceliği

`oncelik` seçeneği yalnızca hibritte vardır ve varsayılan kapalıdır; kapalıyken sıralama hiç değişmez. Açıkken: `skor = birleşik skor × çarpan`, `çarpan = 1.00 − 0.03 × (düzey − 1)`. Düzey, belgenin `type` değerinden gelir; aşağıdaki belgelerin hangi düzeyde olduğu sabittir, `type` → düzey eşlemesi korpusun metadata'sına bakılarak yazılır.

| Düzey | Çarpan | Belgeler |
|---|---|---|
| 1 | 1.00 | korpusta yok (yürürlükteki bağlayıcı düzenleme) |
| 2 | 0.97 | D07 |
| 3 | 0.94 | D01, D02, D03 |
| 4 | 0.91 | D04, D05, D06, D08, D10, D11, D12 |
| 5 | 0.88 | D09, D13, D14, D15 |

Çarpan filtre değildir: yalnızca düşük öncelikli bir belgenin cevap verdiği soruda o belge yine görünür. Çarpan yalnızca birbirine yakın skorları ayırır.

## Ölçüt

- **recall@5:** sorunun `beklenen_belge` listesinden, ilk 5 parçada görünen belgelerin oranı. Belge düzeyinde; aynı belgenin birden çok parçası bir kez sayılır. Soru tipi başına ortalama alınır.
- **İlk sıra doğru:** yalnızca `oncelik` tipindeki sorularda: ilk parçanın belgesi `ilk_beklenen` ile aynı mı. Sonuç `n/3` olarak yazılır.

Tablo biçimi (`scripts/rag_karsilastir.py` yazar, `eval/sonuc/` altına da kaydeder):

| Yöntem | Kelime | Anlam | Çapraz dil | Öncelik | Tümü | İlk sıra doğru |
|---|---|---|---|---|---|---|

Satırlar: `bm25`, `vektor`, `hibrit`; `oncelik` uygulanmışsa `hibrit + oncelik`. Sütunlar 0.00–1.00 arası recall@5.

## Önbellek ve istek sayısı

Sorgu vektörleri `data/indeks/sorgu_onbellegi.json` içinde, model ve sorgu metni anahtarıyla tutulur. Önbellekte olmayan sorgular tek istekle gömülür. Testler ağa çıkmaz, `.env`'e ihtiyaç duymaz.

## Kapsam dışı (bu modülde)

Agent'a bağlama ve tool zarfı, citation, "bilmiyorum" eşiği, sürüm farkı ve çelişki yönetimi (M5.3), reranker.