# Sorumluluk Zinciri

## Hedef

Hangi işlerin LLM'e, hangilerinin servise (deterministik kod) ait olduğunu
deneylerle belirlemek. Her bulgu bir deneye dayanır; **GÖZLEM** deneyde ne
görüldüğünü, **KARAR** bundan çıkan sorumluluk paylaşımını kaydeder.

## Bulgular

| # | Bulgu | Deney | GÖZLEM | KARAR |
|---|---|---|---|---|
| 1 | Durumsuzluk | `scripts/stateless.py` | Model 1. çağrıda "Türkay" adını hatırlayacağını söyledi; 2. çağrıda geçmiş gönderilmeyince adı bilmedi. Geçmiş yeniden gönderildiğinde bildi, ama input token 17'den 279'a çıktı. | Geçmişi sunucu tutar; modele yalnızca son 6 tur ve 12000 karakter gider (`docs/chat.md` › Oturum). Sayı yalnızca o turun tool çağrısından gelir, tool sonuçları saklanmaz. |
| 2 | Hesaplama | `scripts/calc_number.py` | 12 sayının toplamı beş kez soruldu; beşinde de doğru sonuç (165980) geldi. Model "yalnızca sayı yaz" talimatına uymadı, her seferinde ara adımları da yazdı. | |
| 3 | Sıcaklık | `scripts/temperature.py` | `claude-sonnet-4-6` ile T=0.2'de aynı sloganlar tekrar etti, T=1.0'da çeşitlilik arttı. Model "4 kelime" kuralına her zaman uymadı. `claude-sonnet-5-5` T=0.2 ve 0.7'yi 400 hatasıyla reddetti. | |

## Açık sorular

| # | Soru | İlgili bulgu |
|---|---|---|
| 1 | ~~Konuşma geçmişini kim tutacak, nerede saklanacak ve ne kadarı modele gönderilecek?~~ Kapandı (2026-10-30): sunucu oturumu, bellekte, son 6 tur / 12000 karakter; ayrıntı `docs/chat.md` › Oturum. | 1 |
| 2 | Model hesabı doğru yapsa bile hesaplamalar her durumda servise mi bırakılmalı? | 2 |
| 3 | Çıktı formatı (tek sayı, 4 kelime) prompt ile mi, yoksa yapılandırılmış çıktı ya da servis tarafı doğrulamayla mı garanti edilmeli? | 2, 3 |
| 4 | Sıcaklığı desteklemeyen güncel modellerde tutarlılık ve çeşitlilik nasıl yönetilecek? | 3 |
