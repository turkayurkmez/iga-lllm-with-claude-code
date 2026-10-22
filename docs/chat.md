# Olaylar ve akan chat (M3.3)

`/chat` ucunun sözleşmesi. Agent döngüsü olay üretir, `/chat` bu olayları SSE çerçevesi olarak akıtır, arayüz çizer. Zarf `docs/zarf.md`, döngü `docs/agent.md`, talimat `docs/talimat.md`, HTTP `docs/http.md`.

## Uç

`POST /chat`, gövde `{"message": "..."}`; boş mesaj 422. Cevap `text/event-stream`. Chat belleği yoktur: her istek tek, kendi kendine yeten bir sorudur.

## Çerçeve

Her olay üç parçadır: `event: <tip>` satırı, `data: <tek satır JSON>` satırı, boş satır. UTF-8; Türkçe karakterler kaçışsız. (M1.1'in adsız `data:` çerçevelerinin yerine geçer.)

## Olay tipleri

| Tip | Ne zaman | `data` |
|---|---|---|
| `text_delta` | Model metin üretirken, parça başına | `{"text": "..."}` |
| `tool_call` | Model bir tool istedi (istek tamamlanınca), tool çalışmadan önce | `{"call_id": "...", "name": "...", "arguments": {...}}` |
| `source_chip` | Her tool sonucundan sonra | `{"tool": "...", "source": "...", "as_of": "...", "stale": false, "error_code": null}` |
| `kpi_card` | `get_flight_summary` başarılı olunca | `{"tool": "...", "items": [{"label": "...", "value": 0}], "source": "...", "as_of": "..."}` |
| `selection_card` | Zarf `AMBIGUOUS_ENTITY` ise | `{"query": "...", "message": "...", "candidates": [<entity>, ...], "source": "...", "as_of": "..."}` |
| `error` | Döngü `tamam`/`secim_bekleniyor` dışı bir durumla bitti veya model çağrısı başarısız | `{"kod": "...", "mesaj": "..."}` |
| `done` | Akışın sonu | `{"durum": "...", "neden": null, "tur": 0, "input_tokens": 0, "output_tokens": 0, "talimat": {"surum": "...", "ozet": "..."}}` |

## Sıra

Bir model turunda: `text_delta`'lar; model cevabı bitince her tool isteği için `tool_call`; sonra her sonuç için (istek sırasıyla) `source_chip`, ardından varsa `kpi_card` veya `selection_card`. Sonraki tur aynı biçimde sürer. Akış `done` ile biter. Model çağrısı başarısız olursa `error` gelir ve akış `done` olmadan biter.

## Kod garantileri

1. `source_chip`, `kpi_card` ve `selection_card` yalnızca tool zarfından, kodda üretilir; modelin metninden değil. Model hangi cümleyi kurarsa kursun kartlar zarfa uyar.
2. Kartlar zarfı yorumlamaz: alanlar olduğu gibi taşınır; hesap, yuvarlama, saat dönüşümü yoktur. `source` zarftan gelir, kodda sabit yazılmaz.
3. Aynı `source`, `as_of`, `stale` ve `error_code` dörtlüsü bir koşuda tek çip olur.
4. `stale: true` olan zarf bayat işaretli çip üretir; `value`'daki son bilinen değer ve `as_of` olduğu gibi kalır.
5. Bir turda herhangi bir sonuç `AMBIGUOUS_ENTITY` ise o turun tüm istekleri çalıştırılır, kartlar çıkar ve koşu `secim_bekleniyor` durumuyla biter; yeni model çağrısı yapılmaz. Model aday seçemez.
6. `tool_call` tool isteği tamamlandıktan sonra çıkar; yarım argüman gösterilmez.
7. Model cevabı geçmişe akışsız sürümle aynı biçimde eklenir; M3.1'in sonuç nesnesi korunur, `scripts/agent_dene.py` ve M3.1 testleri onu kullanmaya devam eder.
8. Testler sahte modelle koşar, ağa çıkmaz.

## Durum ve olay eşlemesi

| Durum | Olay |
|---|---|
| `tamam` | `done` |
| `secim_bekleniyor` | `selection_card` (yukarıdaki sırada), `done`; `error` yok |
| `iterasyon_siniri` | `error` (`iterasyon_siniri`: "Soru çok adımlı çıktı ve adım sınırına ulaşıldı. Soruyu daraltın."), `done` |
| `tekrar_siniri` | `error` (`tekrar_siniri`: "Aynı sorgu tekrar edildi, işlem durduruldu."), `done` |
| `max_tokens` | `error` (`max_tokens`: "Cevap uzunluk sınırında kesildi."), `done` |
| `durduruldu` | `error` (`durduruldu`: "Model isteği tamamlamadı."), `done` |
| Model çağrısı başarısız | `error` (`model_hatasi`: "Model çağrısı başarısız oldu."); ayrıntı yalnızca sunucu konsoluna |

Zarf hata kodlarına (sabit beş) yeni kod eklenmez; akış hataları zarftan ayrıdır. Kısmi cevap üretilmez.

## Bozulma davranışları

| Bozulma | Zarf | Kod | Model (talimat v2) |
|---|---|---|---|
| `stale_position` | `STALE_DATA`, `value.last_position` dolu, `stale: true` | Bayat işaretli çip | Son bilinen konumu ve veri zamanını söyler; güncel demez |
| `duplicate_callsign` | `AMBIGUOUS_ENTITY`, `value.candidates` | Seçim kartı; koşu biter | Yok: kodda |
| `missing_field` | Hata yok; `value` içinde `null` alan ve `missing_fields` | Normal çip | "Bu alan için veri yok" der, elindeki bilgiyi verir |
| `undefined_flight` | `NOT_FOUND`, `filters` dolu | Hata kodlu çip | Aranan değeri ve bulunamadığını söyler, farklı bir arama önerir |

## Talimat v2

`backend/talimat/v2.md`: v1'in beş ilkesi aynen kalır. Üç ilke eklenir, her biri nedeniyle yazılır:

6. **Bayat veri.** Zarfta `stale: true` veya `STALE_DATA` varsa son bilinen değeri ve `as_of` zamanını söyle; "şu an", "şimdi", "güncel" deme. Neden: eski konum güncel gibi okunursa operasyon kararı yanlış verilir.
7. **Eksik alan.** `value` içinde `null` alan ve `missing_fields` varsa "bu alan için veri yok" de ve elindeki diğer bilgiyi ver. Neden: boş alanı tahminle doldurmak veri uydurmaktır.
8. **Bulunamadı.** `NOT_FOUND`'da `filters`'taki aramayı ve bulunamadığını söyle; sefer numarası, callsign veya tescille yeniden aramayı öner. Neden: "yok" demek yetmez, kullanıcı bir sonraki adımı bilmeli.

Belirsizlik (`AMBIGUOUS_ENTITY`) talimatta değil kodda: bkz. Kod garantileri 5. Sürüm kuralı `docs/talimat.md`'deki gibidir: yayımlanmış dosya yerinde değişmez. `/chat` v2 ile çalışır.

## Arayüz kuralları

1. Akış `fetch` ile okunur (POST gövdesi gerekir); çerçeveler `event:` ve `data:` satırlarından ayrıştırılır.
2. `text_delta` parça parça eklenir; `tool_call` küçük bir satır; çip ve kartlar olay verisini olduğu gibi gösterir. `as_of` tarayıcı saatine çevrilmez, yaş hesaplanmaz, `stale` yeniden türetilmez.
3. Seçim kartındaki bir aday seçilince yeni bir soru gönderilir; soru uçuş kimliğini içerir (chat belleği yoktur).
4. `error` olayı kullanıcıya `mesaj` alanıyla gösterilir; teknik ayrıntı gösterilmez.
5. Doğrulama sayfası (M2.4) değişmez.