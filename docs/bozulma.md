# Bozulma enjeksiyonu: sözleşme

`synth.corruption`, üretecin çıktısını (`docs/spec.md` §8) bilinçli olarak bozar. Amaç, agent'ın eksik, eski, belirsiz veya tutarsız veriyle karşılaştığında sayı/durum uydurmadığını eval'de sınamaktır. Bu belge yalnızca sözleşmedir; kod ve testler ayrı işte yazılır.

## Komut

```
python -m synth.corruption --in girdi.json --scenario S --out çıktı.json [--flight-no TK2345] [--field tablo.alan]
```

| Argüman | Zorunlu | Açıklama |
|---|---|---|
| `--in` | evet | `synth.generator` çıktısı. **Hiçbir koşulda değiştirilmez.** |
| `--scenario` | evet | `stale_position`, `duplicate_callsign`, `missing_field`, `undefined_flight`; bir çalıştırmada tek senaryo. Zincirlemek için çıktı bir sonraki çalıştırmanın girdisi olur. |
| `--out` | evet | Çıktı dosyası; `--in` ile aynı yol olamaz. Klasörü yoksa oluşturulur. |
| `--flight-no` | hayır | Hedef uçuşun sefer no'su. Varsayılan `TK2345` (§9 sabit kaydı; her seed'de vardır). |
| `--field` | yalnızca `missing_field` | `tablo.alan` biçiminde. Varsayılan `flights.estimated_time`. Diğer senaryolarda verilirse hata. |

**Belirlenimcilik.** Rastgelelik yoktur; hedef ve ikincil kayıtlar kurallarla seçilir. Aynı girdi ve aynı argümanlar byte byte aynı çıktıyı verir. Yazım biçimi üreteçle aynıdır: UTF-8, `ensure_ascii=False`, `indent=2`, `\n` satır sonu. Kayıtların sırası korunur.

**İz.** Çıktıya bozulma izi eklenmez; `meta` girdiyle aynı kalır. Eval neyin bozulduğunu komut argümanlarından bilir. stdout'a tek satır özet yazılır: senaryo, hedef `flight_id`, hedef `flight_no`, etkilenen kayıt sayısı.

**Hata durumları.** Aşağıdaki durumlarda komut sıfırdan farklı bir kodla çıkar, stderr'e Türkçe neden yazar ve **çıktı dosyası yazılmaz**:

- `--flight-no` ile eşleşen uçuş yok ya da birden fazla var.
- `stale_position` için hedef iptal edilmiş, yani konum izi yok.
- `duplicate_callsign` için uygun ikinci departure yok.
- `--field` geçersiz: biçim yanlış, tablo `flights`/`movements`/`delays` dışında, alan o tabloda yok ya da hedefin o tabloda kaydı yok (ör. gecikmesiz uçuş için `delays.*`).
- `--field`, kaydın anahtarı (`flight_id`) olarak verilmiş.

## Senaryolar

"Hedef" `--flight-no` ile seçilen uçuştur.

| Senaryo | Neyi bozar | Neyi değiştirmez | Agent'ın doğru davranışı |
|---|---|---|---|
| `stale_position` | Hedefin konum izinde son konumdan bu yana 10 dakika içindeki noktalar silinir (`ts > son_ts − 10 dk`). 30 sn çözünürlüklü 41 noktalık izden ilk 21 nokta kalır; son konum 10 dakika eskir. | `flights`, `movements` (block ve pist zamanları dahil), `delays`, diğer uçuşların izleri. | Kalan son konumu **zaman damgasıyla** verir ve verinin eski olduğunu söyler. Güncel konumu ara değerleme ya da tahminle üretmez; hareket kaydındaki block zamanından konum çıkarmaz. |
| `duplicate_callsign` | Hedef dışındaki, iptal edilmemiş ve `flight_id` sırasına göre ilk departure'ın `callsign`'ı hedefin `callsign`'ıyla değiştirilir (varsayılan hedefte `THY2345`). Hedefin kendisi departure değilse de kural aynıdır. | O ikinci uçuşun `flight_no`'su, tescili ve diğer tüm alanları; hedefin tüm kayıtları; diğer tüm tablolar. | Callsign ile sorulduğunda **eşleşen iki uçuşu da** sefer no, tescil ve tarifeyle listeler. Birini kendisi seçmez; sefer no ya da tescille netleştirme ister. Sefer no ile sorulursa (tekil) normal yanıt verir. |
| `missing_field` | `--field` ile verilen alan hedefin kaydından **anahtarıyla birlikte** kaldırılır (`null` değil, anahtar yok). Varsayılan: `flights.estimated_time`. | Hedefin aynı kaydındaki diğer alanlar; hedefin diğer tablolardaki kayıtları (ör. `delays.delay_minutes` durur); diğer uçuşlar. | Alanın veride bulunmadığını söyler. Değeri başka alanlardan **kendisi hesaplamaz** (ör. tahmini zamanı tarife + gecikmeden çıkarmaz). Var olan diğer alanlarla yanıt verir. |
| `undefined_flight` | Hedefin `flights` kaydı silinir. | Hedefe ait `movements`, `positions` ve `delays` kayıtları **kalır** (yetim kayıt olurlar); diğer tüm uçuşlar. | Uçuş kaydının bulunamadığını söyler. Yetim kayıtlardan sefer no, tarife ya da durum bilgisi **kurmaz**. Uygunsa veri tutarsızlığı olduğunu belirtir. Sefer no veya callsign ile yapılan aramada sonuç yoktur; durum §9'daki `ZZ9999` ile aynıdır. |

## Ortak kurallar

- Bozulma yalnızca tabloda "Neyi bozar" sütununda yazanı değiştirir. Çıktı ile girdi arasındaki fark, eval'in beklediği farkın tamamıdır; başka hiçbir alan, kayıt ya da sıra değişmez.
- Agent davranışları `backend/prompts.py`'deki ilkeye dayanır: doğrulanmış veri yoksa bunu söyler, sayı/durum uydurmaz, hesabı servise bırakır.
- Kod `synth/corruption.py`'de yazılacak. Testleri, `tests/test_generator.py` gibi koddan önce yazılır ve gevşetilmez.

## Akış

`synth.stream`, bir üreteç ya da bozulma çıktısındaki `positions` kayıtlarını simüle zamanla stdout'a akıtır. Amaç, agent'ı ve arayüzü canlı veri gelir gibi beslemektir. Bu bölüm yalnızca sözleşmedir; kod ve testler ayrı işte yazılır.

### Komut

```
python -m synth.stream --in girdi.json --from HH:MM [--speed 60] [--no-wait]
```

| Argüman | Zorunlu | Açıklama |
|---|---|---|
| `--in` | evet | `synth.generator` ya da `synth.corruption` çıktısı. Yalnızca okunur. |
| `--from` | evet | Simüle saatin başlangıcı, `HH:MM` (00:00–23:59). Gün girdinin `meta.date` alanından gelir, saat dilimi `+03:00`'tür. |
| `--speed` | hayır | Gerçek bir saniyede geçen simüle saniye sayısı; varsayılan `60` (gerçek 1 sn = simüle 1 dk). `0`'dan büyük bir sayı olmalı. |
| `--no-wait` | hayır | Hiç beklemeden tüm satırları hemen yazar. |

### Çıktı

- stdout'a **NDJSON** yazılır: her satır tek bir konum kaydıdır. Kayıt girdideki haliyle, alan sırası korunarak `json.dumps(kayıt, ensure_ascii=False)` ile yazılır; satır sonu `\n`'dir. stdout'ta konum satırları dışında hiçbir şey yoktur.
- **Seçim:** `ts`'si `--from`'dan önce olan kayıtlar atlanır; `ts == from` olanlar yayınlanır. Akış son kayıtla biter.
- **Sıra:** `(ts, flight_id)`, artan. `ts` metin olarak değil, zaman damgası olarak karşılaştırılır.
- Bitişte stderr'e tek satır özet yazılır: yayınlanan satır sayısı, ilk ve son `ts`. `--from`'dan sonra hiç kayıt yoksa bu hata değildir: stdout boş kalır, özette sayı `0` olur ve komut `0` koduyla çıkar.

### Belirlenimcilik ve bekleme

- stdout'taki çıktı **yalnızca girdiden ve `--from`'dan** türer. Aynı girdi ve aynı `--from` ile çıktı, `--speed` ve `--no-wait` ne olursa olsun byte byte aynıdır. Sistem saati ve rastgelelik çıktıyı etkilemez.
- Bekleme yalnızca satırların **ne zaman** yazıldığını belirler, neyin yazıldığını değil. Aynı `ts`'ye sahip satırlar tek grup olarak birlikte yazılır ve her gruptan sonra stdout boşaltılır (`flush`).
- Grup *i*'nin yazılma anı: başlangıç + (`ts_i − from`) / `speed` gerçek saniye. Süre her grup için başlangıçtan hesaplanır; bekleme süreleri art arda toplanmadığı için zaman kayması birikmez. İlk grup da `--from`'dan itibaren bekler.
- `--no-wait` verildiğinde hiç beklenmez; çıktı yine aynıdır.

### Bozulmuş girdiyle davranış

`synth.stream` referans bütünlüğünü denetlemez ve kayıtları düzeltmez; girdide ne varsa onu akıtır:

- `stale_position` çıktısında hedefin izi 10 dakika erken biter.
- `undefined_flight` çıktısındaki yetim konumlar da akıtılır.

Bozulmayı fark etmek tüketicinin, yani agent'ın işidir (bkz. Senaryolar tablosu).

### Hata durumları

Aşağıdaki durumlarda komut sıfırdan farklı bir kodla çıkar, stderr'e Türkçe neden yazar ve **stdout'a hiç satır yazmaz**. Doğrulama, ilk satır yazılmadan önce yapılır:

- `--in` okunamıyor ya da geçerli JSON değil.
- `meta.date` yok ya da `YYYY-MM-DD` biçiminde değil.
- `--from` `HH:MM` biçiminde değil ya da 00:00–23:59 dışında.
- `--speed` sayı değil ya da `0`'dan büyük değil.
