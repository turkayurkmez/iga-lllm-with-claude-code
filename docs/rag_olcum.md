# RAG ölçümü (M7.2)

RAG golden set'ini agent'a gerçek modelle koşan ve skor raporu üreten katmanın sözleşmesi. Agent ve atıf davranışı `docs/kaynakli.md`, arama `docs/hibrit.md`, olaylar `docs/chat.md`, genel eval düzeni `docs/eval.md`.

## Girdi

`eval/kaynakli_sorulari.json` (eğitmenden). On soru: S1–S7 cevaplanabilir, U1–U3 cevaplanamaz. Alanlar: `id`, `soru`, `cevaplanabilir`, `beklenen_belgeler`, `include_superseded`. Dosya değiştirilmez, yeni golden set yazılmaz.

## Koşu

1. Sorular sırayla, gerçek model ve gerçek `search_documents` ile agent'a sorulur. Agent'ın davranışı değiştirilmez; koşucu yalnızca agent'ın zaten ürettiği olaylardan ve sonuçlardan okur.
2. Her soru için ham kayıt tutulur: soru, cevap metni, agent durumu, `search_documents` çağrıları (argümanlar ve her çağrının sonucunda dönen belgelerin sırası), cevaptaki atıflar: `citation` olaylarından (`docs/chat.md › Atıf olayı`) `chunk_id`, `dogrulandi`, `status`; belge (`doc_id`) `chunk_id`'nin eşleştiği `search_documents` parçasından okunur, doğrulanamayan atıfın belgesi yoktur.
3. Kayıtlar `eval/out/` altına yazılır; bu klasör git'e girmez (`.gitignore`).
4. Skorlar yalnızca ham kayıttan hesaplanır. Hesap saftır ve ağa çıkmaz; testleri uydurma kayıtlarla koşar.

## Metrikler

| Metrik | Hesap |
|---|---|
| recall@5 | Yalnızca S1–S7. Agent'ın `search_documents` çağrılarının her birinde ilk beş sonuçtaki belgelerin birleşimi alınır. `beklenen_belgeler`'in **hepsi** bu kümedeyse soru 1, değilse 0. Kısmi doğru tam puan almaz. Agent hiç arama yapmadıysa 0 |
| Cevaplanabilirlik | U1–U3'te ret beklenir; S1–S7'de ret (gereksiz ret) olmamalı. Ret: cevap kaynak bulunamadığını söylüyor ve atıf taşımıyor (talimat v3'ün "bilmiyorum" davranışı, `docs/kaynakli.md › Bilmiyorum`). Her cevap üç sınıftan birine girer: ret, cevap, belirsiz. Belirsiz ne doğru ne yanlış sayılır, raporda ayrı gösterilir. Raporda: U'da ret sayısı (x/3), S'de gereksiz ret sayısı (y/7), belirsiz sayısı |
| Citation precision | Belge düzeyinde. S1–S7'deki tüm atıflar havuzlanır: `beklenen_belgeler` içindeki belgeye yapılan atıf sayısı / toplam atıf sayısı. Bölüm düzeyi ölçülmez (golden set'te bölüm bilgisi yok) |
| Eski sürüm kullanımı | `include_superseded: false` olan sorularda eski sürüm (superseded) belgeye yapılan atıf sayısı; atıfın `status` değerinden (`superseded`) bakılır, hedef 0. `include_superseded: true` olan soruda (S2) eski sürüm atfı beklenir; ayrı satırda gösterilir, skora girmez |
| Atıfsız cümle / doğrulanamayan atıf oranı | İki ayrı sayı, tek başlık altında: (a) ret olmayan cevaplarda atıf taşımayan cümle sayısı / toplam cümle sayısı; (b) atıf denetiminin (`docs/kaynakli.md › Atıf`, `citation` olayında `dogrulandi: false`) doğrulayamadığı atıf sayısı / toplam atıf sayısı. Cümle bölme basittir. Atıfın cümleyi gerçekten desteklediği denetlenmez |

Rapor ve skor tablosunda bu son metrik **"atıfsız cümle / doğrulanamayan atıf oranı"** adıyla yazılır; "unsupported claim rate" denmez.

## Skor raporu

1. Beş metriğin özet tablosu.
2. Soru bazında satırlar: soru numarası, recall tam mı, ret sınıfı, atıf yapılan belgeler, eski sürüm atfı var mı.
3. Raporun en altında sabit not:
   - "Cümle düzeyinde destek denetimi bu eğitimde ölçülmemiştir, sonraki adım olarak LLM ile notlama önerilir."
   - "Skor on soruda hesaplanmıştır; her cevaplanabilir soru recall'ı yaklaşık 14 puan oynatır. Küçük farklar değil belirgin düşüşler okunmalıdır."

## Kurallar

1. Hesap ham kayıttan çalışır; koşu sırasında hesaplanmış skor saklanmaz.
2. Mevcut `eval/` dosyalarına (`golden.py`, `expected.py`, `criteria.py`, `run.py`, `golden.json`; `docs/eval.md`) dokunulmaz.
3. Model ve anahtarlar `.env`'den okunur; koda gömülmez, `.env`'e dokunulmaz.
4. Model olasılıksaldır: iki koşu aynı çıkmayabilir. Ölçüt, çalışan koşu ve sözleşmeye uygun rapordur.

## Kapsam dışı (bu modülde)

Cümle düzeyinde destek denetimi, LLM ile notlama, bölüm düzeyinde atıf ölçümü, çapraz dil sorusu, operasyonel hafıza koleksiyonunun kurulması.