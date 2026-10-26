# Harita komutları: sözleşme

Agent haritayı iki komutla yönetir: `focus_map_object` ve `highlight_map_set`. Başka komut yoktur. Komutlar iki tool'dur (`docs/tools.md` ortak kurallarına uyar, zarfla döner); `/chat` akışına `map_command` olayı olarak çıkar; arayüz olayı alıp haritaya uygular. Harita ekranı bu belgenin yazıldığı sürümde yoktur (`docs/canli_akis.md` › Kapsam dışı); belge ekranın uyacağı sözleşmedir.

## Nesne tipleri

Tablo kapalıdır. Haritada komutla yönetilebilen iki nesne tipi vardır.

| `object_type` | `id` | Haritadaki karşılığı | Kaynak |
|---|---|---|---|
| `flight` | `flight_no` (ör. `TK2345`) | Canlı konumdaki uçak | Canlı depo: `Flight` = `id` olan görünür konum (`docs/canli_akis.md` › Depo) |
| `stand` | `stand_code` (ör. `C101`) | Stand | `COPILOT_DATA`'daki `stands` (`GET /map/stands` ile aynı kayıtlar) |

`id` kullanıcının yazdığı değil, tool'dan gelen kimliktir (ör. `resolve_flight_identity` › `flight_no`). Eşleşme tam eşitliktir; büyük/küçük harf, boşluk ve sıfır düzeltmesi yoktur.

## Komutlar

| Komut | Giriş | Ne yapar |
|---|---|---|
| `focus_map_object` | `object_type`, `id` | Haritayı tek bir nesneye odaklar ve o nesneyi seçili yapar. |
| `highlight_map_set` | `object_type`, `ids` | Aynı tipten bir nesne kümesini vurgular; önceki vurguyu değiştirir. |

- `focus_map_object` yalnızca bir nesneyi hedefler. Birden fazla nesne gerekiyorsa `highlight_map_set` kullanılır.
- `highlight_map_set` tek tipli kümedir; `flight` ve `stand` bir komutta karışmaz. Karışık vurgu için iki ayrı çağrı gerekir, ikincisi birincinin vurgusunu değiştirir.
- Komut yalnızca haritanın **görünümünü** değiştirir. Veri okumaz, hesaplamaz, sayı üretmez, hiçbir kaydı değiştirmez.
- Vurguyu kaldıran, yakınlaştıran, iz çizen, filtreleyen ya da başka nesne tipine odaklanan komut yoktur (Kapsam dışı).

## Tool doğrulaması

Giriş şemaları `backend/tools/contracts/<tool>.json`'da tanımlanır; argümanlar `run_tool` içinde `input_schema` ile doğrulanır (`docs/tools.md` › Ortak kurallar). Kontrat kuralları geçerlidir: her nesne `additionalProperties: false`, `minLength`/`maxLength`/`minimum`/`maximum`/`multipleOf` yok, biçim `pattern` ile.

**`focus_map_object` girişi**

| Alan | Tip | Kural | Örnek |
|---|---|---|---|
| `object_type` | metin | Zorunlu. `enum`: `flight`, `stand`. | `"flight"` |
| `id` | metin | Zorunlu. `pattern`: `^([A-Z]{2}\d{3,4}\|[A-Z]\d{3})$` (iki biçimden biri; aşağıda › Kimlik biçimi). | `"TK2345"`, `"C101"` |

**`highlight_map_set` girişi**

| Alan | Tip | Kural | Örnek |
|---|---|---|---|
| `object_type` | metin | Zorunlu. `enum`: `flight`, `stand`. | `"stand"` |
| `ids` | metin dizisi | Zorunlu. Her eleman aynı `pattern` (yukarıdaki `id` ile). | `["C101", "C102"]` |

**Kimlik biçimi.** Biçim `object_type`'a göredir; referans veriden (`seed42-2026-10-20.json`) çıkarılmıştır:

| `object_type` | Biçim (`pattern`) | Referans veride |
|---|---|---|
| `flight` | `^[A-Z]{2}\d{3,4}$` (`flight_no`) | 600 uçuşun 540'ı iki harf + 4 rakam, 60'ı iki harf + 3 rakam |
| `stand` | `^[A-Z]\d{3}$` (`stand_code`) | 120 stand'in hepsi bir harf + 3 rakam |

Callsign (`THY2345`) ve tescil (`TC-LSD`) `flight` biçimine uymaz, reddedilir. Tool şemasında üst düzey `oneOf`/`allOf`/`anyOf` kullanılmaz (Anthropic API `input_schema`'da üst düzeyde kabul etmez); bu yüzden kontrat şeması iki biçimin birleşimini (`^([A-Z]{2}\d{3,4}|[A-Z]\d{3})$`) tanımlar, `object_type`'a özel biçim aşağıdaki şema ötesi kurallarla denetlenir.

**Şemanın ötesindeki giriş kuralları** (şemada yazılmaz, `run_tool` şema doğrulamasından sonra, tool çağrılmadan denetler):

- Her iki komutta `id`/`ids` elemanı `object_type`'ın biçimine uymalıdır (`stand` için `TK2345`, `flight` için `C101` reddedilir).
- `highlight_map_set`: `ids` en az 1, en çok 50 eleman içerir.
- `highlight_map_set`: `ids` içinde tekrarlı kimlik olamaz.

Bu kurallardan biri bozulursa sonuç şema hatasıyla aynıdır: `SCHEMA_VALIDATION_FAILED`, `author: layer`, tool çağrılmaz (`docs/tools.md` › Hata eşlemesi; `value`, `source`, `as_of` `null`, `filters` `{}`). Sunucu kimlikleri kendisi kırpmaz, sıralamaz ya da tekilleştirmez.

**Nesne denetimi** (tool içinde, giriş geçerliyse):

- Her kimlik, yukarıdaki tablodaki kaynakta bulunmalıdır. Bulunmayan ilk kimlikte tool `NOT_FOUND` döndürür (`author: tool`, `value: null`); `highlight_map_set`'te tek bir bulunmayan kimlik tüm komutu reddeder, geri kalanlar vurgulanmaz. `filters` doğrulanmış girişi taşır; `message` genel bir metindir ("Haritada bu nesne için konum yok." gibi) ve kimliği içermez.
- `flight` için "bulunur", canlı depoda `LastUpdate` ≤ `operational_now()` olan bir konumun varlığıdır (`docs/tools.md` › `get_flight_details` › Canlı mod ile aynı görünürlük). Konumu olmayan uçuş (iz başlamamış, iptal, kayıt yok) ve canlı mod kapalıyken her uçuş `NOT_FOUND` olur. Uçuş kaydı olması yetmez.
- Bayat ya da final konum bulunmuş sayılır; hata değildir. Bayatlığı zarf değil haritanın kendi görünümü taşır (SSE `stale`; `docs/canli_akis.md` › Bayatlık).
- `stand` için "bulunur", `stands` dizisinde `stand_code` eşitliğidir; `status` (ör. `UNAVAILABLE`) belirleyici değildir.
- Veri okunamaz ya da `stands` bir nesne listesi değilse veri hatası: `SCHEMA_VALIDATION_FAILED`, `author: layer` (`docs/tools.md` › Veri kaynağı).
- `AMBIGUOUS_ENTITY` üretilmez; kimlik tam eşleşmedir.

**Tool'un döndürdüğü `value`** (başarıda; `error` yok):

| Komut | `value` |
|---|---|
| `focus_map_object` | `{"command": "focus_map_object", "object_type": "...", "id": "..."}` |
| `highlight_map_set` | `{"command": "highlight_map_set", "object_type": "...", "ids": ["..."]}` |

`value`, girişin doğrulanmış kopyasına `command` eklenmiş halidir; başka alan yoktur, `ids` sırası girişteki gibidir. `source` `COPILOT_DATA`'nın değeridir, olduğu gibi. `tool_version` `1.0.0`. Tool `data_time` vermez; `stale` her zaman `false`'tur (`max_age` tanımlı değil).

## `map_command` olayı

`docs/chat.md` › Olay tipleri tablosuna sekizinci tip olarak eklenir; çerçeve biçimi aynıdır. Tablodaki tipler dışında olay çıkmaz.

| Tip | Ne zaman | `data` |
|---|---|---|
| `map_command` | Bu belgedeki iki tool'dan birinin zarfında `error` `null` ise, `tool_call`'dan sonra | `{"command": "...", "object_type": "...", "id": "..."}` (`focus_map_object`) ya da `{"command": "...", "object_type": "...", "ids": ["..."]}` (`highlight_map_set`) |

- Olay tool zarfının `value`'sundan, kodda üretilir; modelin metninden değil (`docs/chat.md` › Kod garantileri 1). `value` olduğu gibi taşınır: kısaltma, sıralama, ek alan yok.
- Hata zarfı (`NOT_FOUND`, `SCHEMA_VALIDATION_FAILED`) `map_command` üretmez. Model hatayı kullanıcıya söyler; haritaya dokunulmadığını bilir (`docs/agent.md` › Kurallar'daki zarf akışı değişmez).
- Zarf `source`'u `null` değilse `source_chip` kuralı (Kod garantileri 3) aynen geçerlidir; `map_command` çipin yerine geçmez.
- Aynı koşuda birden fazla komut gelebilir; olaylar tool çağrı sırasıyla çıkar. İstemci sırayla uygular, bu yüzden son `highlight_map_set` etkindir.
- `map_command`, `text_delta`'dan bağımsızdır: cevap metni olmadan da gelir, `tamam` dışı bitişte de komut daha önce çıkmışsa kalır (komut `error`'dan önce geldiyse geri alınmaz).
- Audit kaydı değişmez: tool `value`'su kayda girmez (`docs/audit.md`).

## Arayüz işleyicisi

`frontend/src/chat.ts` olayı doğrular: bilinen bir `command`, `object_type` ∈ {`flight`, `stand`}, `focus_map_object` için metin `id`, `highlight_map_set` için metin dizisi `ids` değilse olay yok sayılır (`docs/chat.md` › Arayüz kuralları 1 ile aynı). Doğrulanan olay işleyiciye verilir; işleyici haritayı sahiplenen ekrandadır.

| Komut | İşleyici |
|---|---|
| `focus_map_object` | Haritayı nesnenin konumuna ortalar ve nesneyi seçili yapar. Önceki seçim kalkar. Vurgu kümesine dokunmaz. |
| `highlight_map_set` | Önceki vurgu kümesini tamamen siler, `ids`'teki nesneleri vurgular. Seçimi değiştirmez. |

- İşleyici konumu ve durumu SSE'den (`flight`) ya da `GET /map/stands`'ten (`stand`) alır; komut koordinat taşımaz. Konum kaydırılmaz, ara değerleme yapılmaz.
- Bayat konum (`stale: true`) olduğu gibi gösterilir ve işaretlenir; komut onu güncelmiş yapmaz.
- İstemcide artık bulunmayan nesne (ör. vurgudan sonra `removed` gelen uçuş, listede olmayan stand) sessizce atlanır; hata gösterilmez, harita çökmez. Kalan nesneler uygulanır.
- Harita `/sohbet`'te sohbetin yanındadır; komutlar o ekranda uygulanır. Harita ekranı yoksa (ör. `/` ya da `/canli`) komutlar uygulanmaz ve kuyruğa alınmaz. Komut kullanıcıya gösterilmez ve metne eklenmez.
- İşleyici kullanıcının elle yaptığı pan/zoom'u engellemez. Komut yalnızca kendi anında uygulanır; sonraki elle hareket komutun etkisini bozmaz.
- Komut işleyicisi `fetch`/`POST` yapmaz; ağ çağrısı yalnızca mevcut SSE ve `/map/stands` yoluyla olur.

## Haritadan sohbete bağlam

Sohbetin belleği yoktur (`docs/sorumluluk-zinciri.md` › Açık soru 1); her mesaj bağımsızdır. Haritada seçili nesne bir sonraki mesaja kimlik olarak eklenir.

- **Seçim:** haritada bir uçağa ya da stand'e tıklamak o nesneyi seçili yapar (`focus_map_object` ile aynı durum). Seçili nesne tektir; boş alana tıklamak ya da seçili nesneye yeniden tıklamak seçimi kaldırır.
- **İstek:** `POST /chat` gövdesi isteğe bağlı `selected` alanı alır: `{"message": "...", "selected": {"object_type": "flight", "id": "TK2345"}}`. `selected` yoksa gövde bugünkü gibidir (`docs/chat.md` › Uç). `object_type` ve `id` yukarıdaki tablodaki değerlerdir; `selected` başka alan içermez, yanlış biçimli `selected` 422 verir.
- **Sunucu:** `selected` model çağrılmadan önce doğrulanır; geçersizse ya da nesne veride yoksa `422` döner, model çağrılmaz, olay ve audit satırı üretilmez (`docs/chat.md` › Uç). Biçim `docs/harita.md` › Tool doğrulaması › Kimlik biçimi gibi `object_type`'a göredir. "Veride yok" tool'larla aynı kuraldır (`backend/tools/harita.py` › `exists`): stand için `stands`'te `stand_code` eşitliği, uçuş için canlı depoda görünür konum (`LastUpdate` ≤ operasyonel saat); canlı mod kapalıyken her uçuş için `422`. Veri okunamazsa `503`. Geçerliyse not, kodda üretilen sabit biçimle tek satır olarak modele giden mesajın başına eklenir: `Haritada seçili: flight TK2345` + satır sonu + kullanıcı mesajı. Audit'e orijinal mesaj yazılır, not girmez. Mesajda başka bir uçuş anılıyorsa mesaj geçerlidir, seçim yalnızca bağlamdır.
- **Model:** seçili nesne bir tool girişi olarak yalnızca kullanıcının mesajı onu ima ediyorsa ("burası", "bu uçak") kullanılır. Seçili nesneyle ilgili veri sorusu yine tool'la cevaplanır; model seçimden operasyonel bilgi çıkarmaz.
- **Arayüz:** `Chat.tsx` açık harita ekranında seçimi bir sonraki gönderiye ekler; gönderim sonrası seçim kalkmaz (kullanıcı kaldırana kadar sürer). Seçim yoksa `selected` alanı gönderilmez. Seçili nesne yazı alanının üstünde `Bağlam: <id> ×` çipi olarak görünür (× seçimi kaldırır); gönderilen her turun sorusunun altında o mesajla giden bağlam çipi kalıcı kalır ve sonradan değişen seçimden etkilenmez.

## Etkilenen belgeler

Bu belge yalnızca sözleşmedir. Uygulama sırasında şu belgeler birlikte güncellenir:

- `docs/tools.md`: tool sayısı üçten beşe çıkar; iki yeni tool bölümü, `CAPABILITY_NOT_IN_SCOPE` tool adı listesi ve `tool_definitions` sırası.
- `docs/chat.md`: olay tablosuna `map_command`; Uç bölümüne `selected`; Arayüz kuralları 1'deki "yedi tip" sekiz olur.
- `docs/system-talimat.md`: talimat metni değişirse sürüm ve Değişiklik günlüğü birlikte artar.
- `docs/canli_akis.md`: › Ekran ve › Kapsam dışı (harita ekranı).

## Kapsam dışı

- Üçüncü bir komut (vurguyu kaldırma, yakınlaştırma, iz çizme, filtre, katman, ölçü).
- `flight` ve `stand` dışında nesne tipi (gate, olay, kaynak).
- Komutlarda koordinat, renk, yakınlaştırma düzeyi ya da başka görünüm alanı.
- Karışık tipli küme; kimlik yerine kriterle (ör. "gecikmesi 15 dakikadan fazla olanlar") küme tanımlama.
- Birden fazla seçili nesne; haritanın görünür sınırının ya da yakınlaştırma düzeyinin sohbete gönderilmesi.
- Komutun kuyruğa alınması ya da harita ekranı kapalıyken sonradan uygulanması.
