# Olaylar ve akan chat

`/chat` ucunun sözleşmesi. Agent döngüsü olay üretir, `/chat` bu olayları SSE çerçevesi olarak akıtır, arayüz çizer. Zarf `docs/zarf.md`, döngü `docs/agent.md`, talimat `docs/system-talimat.md`, HTTP `docs/http.md`, tool'lar `docs/tools.md`.

## Uç

`POST /chat`, gövde `{"message": "..."}` ya da haritada seçili nesneyle `{"message": "...", "selected": {"object_type": "flight", "id": "TK2345"}}` (`selected` isteğe bağlıdır; sözleşmesi `docs/harita.md` › Haritadan sohbete bağlam). Cevap `text/event-stream; charset=utf-8`. Konuşma geçmişini **sunucu** tutar (oturum, aşağıda › Oturum); istemci geçmiş gönderemez.

Gövdeye isteğe bağlı `"session_id": "<32 hex>"` eklenebilir. Yoksa ya da sunucuda bulunamıyorsa (süre doldu, sunucu yeniden başladı) yeni oturum açılır; bu hata değildir ve `done` olayında bildirilir. Biçimsiz `session_id` ve tabloda olmayan her gövde alanı (ör. `history`) 422 verir.

Akış başlamadan önceki hatalar HTTP durum koduyla döner, olay üretilmez, model çağrılmaz:

| Durum | Kod | Gövde |
|---|---|---|
| Mesaj boş ya da yalnızca boşluk | `422` | FastAPI doğrulama gövdesi |
| Mesaj kırpıldıktan sonra 2000 karakterden (kod noktası) uzun (`backend/main.py` › `MAX_MESSAGE_CHARS`; `docs/enjeksiyon.md` E4) | `422` | FastAPI doğrulama gövdesi |
| `session_id` biçimsiz (32 küçük harfli hex değil, açık olmayan tür) ya da gövdede tanımsız alan | `422` | FastAPI doğrulama gövdesi |
| `selected` yanlış biçimli (açık `null`, bilinmeyen `object_type`, `object_type`'a uymayan `id`, fazla alan) | `422` | FastAPI doğrulama gövdesi |
| `selected` nesnesi veride yok (`docs/harita.md` › Haritadan sohbete bağlam) | `422` | `{"detail": [{"type": "value_error", "loc": ["body", "selected"], "msg": "..."}]}` |
| `selected` doğrulanırken veri okunamadı | `503` | `{"detail": SELECTED_UNAVAILABLE_MESSAGE}` (`backend/main.py`) |
| `ANTHROPIC_*` eksik (`ConfigError`) | `503` | `{"detail": CONFIG_ERROR_MESSAGE}` (`backend/main.py`) |
| Bilinmeyen talimat sürümü (`COPILOT_INSTRUCTION`) | `503` | Aynı genel ayar mesajı |

`selected` doğrulaması `ANTHROPIC_*` denetiminden önce yapılır; `selected` yokken bu satırlar geçerli değildir. Geçerli `selected` modele gidecek mesajın başına, ayrı bir satır olarak `Haritada seçili: flight TK2345` notunu ekler. Audit satırına giren soru orijinal mesajdır (`docs/audit.md`).

Akış başladıktan sonra durum kodu her zaman `200`'dür; hatalar `error` olayıyla bildirilir.

## Çerçeve

Her olay üç parçadır: `event: <tip>` satırı, `data: <tek satır JSON>` satırı, boş satır. UTF-8; Türkçe karakterler kaçışsız (`ensure_ascii=False`). Mevcut `/chat`'in `delta`/`done`/`error` olaylarının yerine geçer; `frontend/src/chat.ts` ve `Chat.tsx` birlikte güncellenir.

## Olay tipleri

Alan adları `AgentResult` ile aynıdır (`docs/agent.md` › Sonuç). Tablo kapalıdır.

| Tip | Ne zaman | `data` |
|---|---|---|
| `tool_call` | Döngü bir tool'u çalıştıracakken, çalıştırmadan önce | `{"id": "...", "name": "...", "input": {...}}` |
| `source_chip` | Kaynağı olan her tool sonucundan sonra (Kod garantileri 3) | `{"tool": "...", "source": "...", "as_of": "...", "stale": false, "error_code": null}` |
| `kpi_card` | `get_flight_summary` zarfında `error` `null` ise | `{"tool": "...", "items": [{"field": "...", "description": "...", "value": 0}], "source": "...", "as_of": "..."}` |
| `chart_card` | `get_chart_data` zarfında `error` `null` ise (`docs/tools.md` › `get_chart_data`) | `{"tool": "get_chart_data", "chart_type": "...", "group_by": "...", "metric": "...", "date": "...", "flights": 0, "groups_total": 0, "unclassified": 0, "items": [{"label": "...", "value": 0}], "filters": {...}, "source": "...", "as_of": "..."}` |
| `selection_card` | Zarf `AMBIGUOUS_ENTITY` ise | `{"query": "...", "message": "...", "candidates": [<aday>, ...], "source": "...", "as_of": "..."}` |
| `map_command` | `focus_map_object` ya da `highlight_map_set` zarfında `error` `null` ise (`docs/harita.md` › `map_command` olayı) | Zarfın `value`'su olduğu gibi: `{"command": "...", "object_type": "...", "id": "..."}` ya da `{"command": "...", "object_type": "...", "ids": ["..."]}` |
| `text_delta` | Döngü `tamam` ile bitince, nihai cevabın metni | `{"text": "..."}` |
| `citation` | Döngü `tamam` ile bitince, nihai cevapta geçen her ayrık parça etiketi için (Atıf olayı) | Eşleşen etiket: `{"chunk_id": "...", "dogrulandi": true, "title": "...", "section": "...", "revision": "...", "effective_from": "...", "status": "..."}`; eşleşmeyen: `{"chunk_id": "...", "dogrulandi": false}` |
| `error` | Döngü `tamam` dışı bir durumla bitti ya da model çağrısı başarısız | `{"code": "...", "message": "..."}` |
| `done` | Döngü beş bitiş durumundan biriyle bitti | `{"status": "...", "reason": null, "turns": 0, "instruction": {"name": "...", "version": "...", "summary": "..."}, "audit_id": "...", "session_id": "...", "session_reset": false}` |

- `tool_call.id`, `name`, `input`: `turns[].tool_calls[]`'taki aynı alanlar, olduğu gibi.
- `chart_card`: zarfın `value`'su olduğu gibi (`items` dahil) artı `tool`, `filters`, `source`, `as_of`. Noktaları tool hesaplar; kod ve arayüz toplam, yüzde ya da sıralama türetmez.
- `selection_card`: `query` zarfın `filters.query`'si, `message` `error.message`'ı, `candidates` `value` dizisinin kendisi (`resolve_flight_identity` › `value_schema`, `flight_id`'ye göre artan).
- `kpi_card.items`: `value`'daki tamsayı alanlar, kontrattaki `value_schema` sırasıyla (`total`, `cancelled`, `delayed`); `description` kontrattaki alan açıklamasıdır (`backend/tools/contracts/get_flight_summary.json`).
- `error`: döngü durumlarında `code` `status`'tur, `message` `AgentResult.reason`'dır (`docs/agent.md` › Durumlar'daki metin). Model çağrısı başarısızsa `code` `model_error`, `message` `ERROR_MESSAGE`'dır (`backend/main.py`).
- `citation`: alanların anlamı ve eşleme kuralları aşağıda, Atıf olayı'ndadır.
- `done`: `status`, `reason`, `instruction` `AgentResult`'tan; `turns` `len(AgentResult.turns)`; `audit_id` bu sorunun audit satırının kimliği; satır akış bittikten sonra yazılır (`docs/audit.md`). `session_id` oturumun kimliği (her `done`'da vardır); `session_reset` istek bir `session_id` taşıyıp oturum bulunamadığı için yenisi açıldıysa `true`, aksi halde `false`.

## Sıra

Model çağrıları `docs/agent.md`'deki gibi `messages.create`'tir; bir turun metni tur bitip `stop_reason` belli olana kadar tutulur.

Döngü sürerken (tur `tool_use` ile bitti, sınır aşılmadı) bir turda: her tool isteği için, yanıttaki sırayla `tool_call`; sonra her sonuç için (istek sırasıyla) `source_chip` (varsa), ardından varsa `kpi_card`, `chart_card`, `selection_card` ya da `map_command`. Sonraki tur aynı biçimde sürer.

Döngü bitince:

```text
tamam                : text_delta+ (metin boş değilse), citation*, done
diğer dört durum     : error, done
model çağrısı hatası : error            (done yok)
```

- Zamanlama: olaylar `run_agent`'a verilen saran bir istemciden (`backend/main.py` › `EventingClient`) üretilir. Bir turun `tool_call` ve kart olayları, tool'lar çalıştıktan sonra, bir sonraki model çağrısının başında (o isteğin `tool_result`'larından) yazılır; olay sırası yukarıdaki gibidir. "Çalıştırmadan önce" olayın akıştaki yerini anlatır, yazılma anını değil.
- `tool_use` ile biten turun metni (ör. "Kontrol ediyorum") operatöre gitmez; yalnızca döngünün mesaj geçmişinde kalır.
- Bitiş turundaki çalıştırılmayan istekler (`executed: false`; `docs/agent.md` › Durumlar) için `tool_call` çıkmaz.
- Akış tam olarak bir son olayla biter: `done` ya da (model çağrısı hatasında) `error`. Ondan sonra olay yazılmaz.

## Kod garantileri

1. `source_chip`, `kpi_card` ve `selection_card` yalnızca tool zarfından, kodda üretilir; modelin metninden değil. Model hangi cümleyi kurarsa kursun kartlar zarfa uyar.
2. Kartlar zarfı yorumlamaz: alanlar olduğu gibi taşınır; hesap, yuvarlama, saat dönüşümü yoktur. `source` zarftan, `description` kontrattan gelir; kodda sabit metin yazılmaz.
3. Çip yalnızca `source`'u `null` olmayan zarftan çıkar. Kapsam dışı istek ve şema/veri hatası (`source: null`; `docs/tools.md` › Hata eşlemesi) çip üretmez. Aynı `source`, `as_of`, `stale` ve `error_code` dörtlüsü bir koşuda tek çip olur.
4. `stale: true` olan zarf bayat işaretli çip üretir; `value`'daki son bilinen değer ve `as_of` olduğu gibi kalır.
5. `AMBIGUOUS_ENTITY` döngüyü durdurmaz: `selection_card` çıkar, zarf `docs/agent.md` › Kurallar'daki gibi modele gider ve model talimata göre adayları listeleyip netleştirme ister (v1 ilke 5). Model aday seçemez; kod da seçmez.
6. `tool_call` tool isteği tamamlandıktan sonra çıkar; yarım argüman gösterilmez.
7. Döngü `run_agent`'tır; `/chat` döngüyü kopyalamaz. Olaylar döngüden bir bildirim yoluyla (ör. geri çağırma) alınır; `AgentResult`, `docs/agent.md`, `scripts/agent_run.py` ve `tests/test_agent.py` değişmez. Olaylar `AgentResult` ile tutarlıdır: `tool_call` dizisi `executed: true` çağrılardır, `done` alanları sonuçtakidir.
8. Kısmi cevap üretilmez: `text_delta` yalnızca `tamam`'da çıkar; `text_delta`'ların birleşimi `AgentResult.text`'e eşittir. Diğer durumlarda kesik ya da ara metin operatöre gitmez (`docs/agent.md` › Sonuç).
9. Hata ayrıntısı (exception metni, API yanıtı, request id) hiçbir olaya girmez; `logger.exception` ile sunucu loguna yazılır.
10. Senkron döngü olay döngüsünü bloklamaz (thread havuzunda çalışır); olaylar üretildikçe yazılır.
11. Testler sahte modelle koşar, ağa çıkmaz.
12. `citation` yalnızca kodda üretilir. Cevap metninden yalnızca etiketin `chunk_id`'si okunur; belge alanları `search_documents` zarfından olduğu gibi taşınır, model bunları yazmaz (`docs/kaynakli.md › Atıf`).

## Atıf olayı

Sözleşmenin kaynağı `docs/kaynakli.md › Atıf`'tır; burada yalnızca akıştaki biçimi tanımlanır.

- **Etiket:** nihai cevapta (`AgentResult.text`) köşeli parantez içinde yazılmış, `search_documents` kontratındaki `chunk_id` biçimine (`D03#02`) uyan kimlik: `[D03#02]`. Başka biçimli köşeli parantez içeriği etiket sayılmaz. Etiketler metinden değiştirilmeden okunur; metin `text_delta`'larda olduğu gibi kalır.
- **Sıra ve sayı:** etiket başına bir `citation`, cevaptaki ilk geçiş sırasıyla. Aynı `chunk_id` cevapta birden çok geçse de tek olay çıkar. Olaylar `text_delta`'lardan sonra, `done`'dan önce gelir ve yalnızca `tamam`'da çıkar (Kod garantileri 8).
- **Eşleme:** etiket, bu koşuda çalışan `search_documents` çağrılarından `error` `null` olanların `value` parçalarıyla `chunk_id` üzerinden eşleşir. Birden çok çağrıda aynı `chunk_id` gelirse ilk çağrıdaki parça kullanılır.
- **Eşleşen etiket:** `dogrulandi: true`; `title`, `section`, `revision`, `effective_from` ve `status` parçadan olduğu gibi taşınır (yorum, çeviri, saat dönüşümü yok). `status` arayüzün eski sürümü işaretlemesi içindir.
- **Eşleşmeyen etiket:** `dogrulandi: false`, belge alanları yoktur. Tool hiç çağrılmadıysa ya da çağrılan arama parça getirmediyse, cevaptaki her etiket bu durumdadır.
- **Etiket yoksa olay yoktur.** Tool çağrılmadıysa da öyledir (atıf borcu yoktur).
- **Kapsam dışı:** `atifsiz` (tool çağrıldı, parça geldi, cevapta etiket yok) bu olayla taşınmaz; yeri `docs/agent.md` ve `docs/audit.md`'de netleşecektir (`docs/kaynakli.md › Atıf`).

## Durum ve olay eşlemesi

`reason` metinleri `docs/agent.md` › Durumlar'dadır; burada tekrar edilmez.

| Durum | Olay |
|---|---|
| `tamam` | `text_delta`'lar, `citation`'lar (etiket varsa), `done` |
| `iterasyon_siniri` | `error` (`code: iterasyon_siniri`, `message: reason`), `done` |
| `tekrar_siniri` | `error` (`code: tekrar_siniri`, `message: reason`), `done` |
| `max_tokens` | `error` (`code: max_tokens`, `message: reason`), `done` |
| `durduruldu` | `error` (`code: durduruldu`, `message: reason`), `done` |
| Model çağrısı başarısız | `error` (`code: model_error`, `message: ERROR_MESSAGE`); `done` yok, ayrıntı yalnızca sunucu logunda |
| Döngüde beklenmeyen hata | Model hatasıyla aynı: `error` (`code: model_error`), `done` yok; ayrıntı yalnızca sunucu logunda |

Zarf hata kodlarına (sabit beş) yeni kod eklenmez; akış hataları zarftan ayrıdır.

## Bozulma davranışları

Senaryolar `docs/bozulma.md`'de; zarf biçimleri `docs/zarf.md` ve `docs/tools.md`'de. Tool hata kodları ve bozuk veri akışı kesmez.

| Bozulma | Zarf | Kod | Model (talimat v2) |
|---|---|---|---|
| `stale_position` | Şu an başarı: `error: null`, `stale: false`, `value.position` 10 dk eski `ts` taşır. Üç tool'da `max_age` tanımlı olmadığı için `STALE_DATA` dönmez (`docs/tools.md` › Giriş noktaları); `get_flight_details`'e eşik eklenince `stale: true`, `STALE_DATA` olur. | Şu an normal çip; eşik eklenince bayat işaretli çip | Konumu kendi zaman damgasıyla verir; ara değerleme ya da tahmin yapmaz. `stale: true` geldiğinde eski olduğunu açıkça söyler, "şu an", "güncel" demez. |
| `duplicate_callsign` | `AMBIGUOUS_ENTITY`, `value` aday dizisi | Normal çip + seçim kartı; döngü sürer | Adayların hepsini listeler, netleştirme ister; birini seçmez. |
| `missing_field` | Hata yok; alan `value`'da yok (anahtar yok, `null` da değil; `docs/zarf.md` › Eksik alan hata değildir) | Normal çip | "Bu alan için veri yok" der, elindeki diğer bilgiyi verir; değeri türetmez. |
| `undefined_flight` | `NOT_FOUND`, `value: null`, `filters` dolu | Hata kodlu çip | Aranan değeri ve bulunamadığını söyler; sefer no, callsign ya da tescille yeniden aramayı önerir, benzer kayıt önermez. |

## Oturum

Sözleşmenin kaynağı `docs/superpowers/specs/2026-10-30-chat-gecmisi-ve-genel-grafik-design.md` bölüm A'dır, kod `backend/session.py`'dedir.

- **Ne saklanır:** her `tamam` turun `{question, answer, tool_calls}` kaydı (`tool_calls` yalnızca çalıştırılan çağrıların `name` ve `input`'u). Tool sonuçları, zarflar, kart ve grafik verisi saklanmaz; yeni sayı yalnızca o turun tool çağrısından gelir. `tamam` olmayan tur ve haritadan seçim notu geçmişe girmez. İstemci akışı kesse de döngü sürerse tur tamamlanınca eklenir.
- **Modele nasıl gider:** önceki turlar, bu mesajdan önce düz metin `user`/`assistant` turları olarak. Çağrılan araçlar asistan metninin sonuna `[Önceki turda çağrılan araçlar: ad {json}; …]` notuyla eklenir; `tool_use`/`tool_result` bloğu geçmişe taşınmaz.
- **Sınırlar** (`backend/session.py`): modele son 6 tur ve en çok 12000 karakter (eskiden başlayarak tur bölünmeden atılır; tek başına bütçeyi aşan tur hiç gitmez); en çok 100 oturum (en eski kullanılan atılır); oturum başına 20 tur; 2 saat hareketsizlikte oturum dolar.
- **Talimat:** `v5` (v4 + ilke 14) geçmişe nasıl davranılacağını söyler; varsayılan sürüm değişmedi.

## Talimat v2

`backend/instructions/v2.md`, `VERSIONS["v2"] = "2.0.0"` (yazıldı; testleri `tests/test_instruction_v2.py`). Etkin sürüm v3'tür: `backend/instructions/v3.md` v2'nin tüm değişikliklerini içerir ve üstüne kaynaklı cevap ilkelerini ekler (`docs/kaynakli.md`). Cevap yapısının bir parçası kalktığı için değişiklik MAJOR'dur; dosya açma, sürüm, Değişiklik günlüğü ve ölçüm kuralları `docs/system-talimat.md` › Versiyonlama'daki gibidir. `/chat` sürümü `default_version()` ile okur; v2'ye geçiş `COPILOT_INSTRUCTION=v2` ile yapılır.

v1'in sekiz çekirdek ilkesi kalır. Değişenler:

1. **Dayanak parçası kalkar.** Cevap yapısı üç parçadır: doğrudan cevap, ayrıntı, uyarı. Model "Kaynak: …, … itibarıyla." satırını yazmaz; kaynak ve veri zamanı `source_chip` ile kodda gösterilir. Neden: dayanağın tek kaynağı zarftır; modelin kopyası yanlış ya da eksik olabilir ve çiple birlikte iki kez görünür.
2. **İlke 6 netleşir (eski veri).** Sonuç eski işaretliyse son değeri veri zamanıyla ver; "şu an", "şimdi", "güncel" deme. Neden: eski konum güncel gibi okunursa operasyon kararı yanlış verilir.
3. **İlke 5 netleşir (bulunamadı).** Kayıt bulunamadığında aranan değeri söyle ve sefer no, callsign ya da tescille yeniden aramayı öner; benzer kayıt önerme. Neden: "yok" demek yetmez, operatör bir sonraki adımı bilmeli.

Eksik alan kuralı (ilke 6'nın ilk yarısı) ve belirsizlik kuralı (ilke 5) v1'deki gibi kalır. Yazım kuralları aynen geçerlidir: metinde zarf alan adları (`as_of`, `stale`, `filters`) geçmez, "veri zamanı", "eski işaretli" gibi Türkçe adlarla anılır; `snake_case` yalnızca tool adlarında (`docs/system-talimat.md` › Talimat metni).

## Arayüz kuralları

`docs/http.md` › Arayüz kuralları'ndaki zarf kuralları burada da geçerlidir.

1. Akış `fetch` ile okunur (POST gövdesi gerekir); çerçeveler `event:` ve `data:` satırlarından ayrıştırılır. Tablodaki on tip dışındaki olay yok sayılır (`map_command`'ı işleyen kod `docs/harita.md` › Arayüz işleyicisi'ndedir; `citation` madde 7'de). Oturum kimliği `done` olayından alınır ve sonraki mesajla gönderilir; "Yeni konuşma" kimliği bırakır ve ekrandaki turları temizler. `session_reset` `true` ise o turda "Önceki konuşma sıfırlandı; bu soru bağımsız yanıtlandı." notu çıkar.
2. `text_delta` geldiği sırayla eklenir; `tool_call` küçük bir satır (tool adı ve ham `input` gösterilmez; `docs/system-talimat.md` › Cevap metni); çip ve kartlar olay verisini olduğu gibi gösterir. `as_of` `+03:00` saatiyle gösterilir, tarayıcı saatine çevrilmez; yaş hesaplanmaz, `stale` yeniden türetilmez.
3. Seçim kartındaki bir aday seçilince yeni bir soru gönderilir: orijinal soru ile seçilen adayın `flight_no` ve `registration`'ı, zarftaki yazımıyla. Seçim kartı yeni bir mesaj olduğu ve sunucu yalnızca tamamlanan turları hatırladığı için orijinal soru yeni mesajda yine tekrar edilir.
4. `error` olayı kullanıcıya `message` alanıyla gösterilir; `code` ve teknik ayrıntı gösterilmez. `error`'dan önce gelen çip ve kartlar cevap sayılmaz.
5. `tamam` ama `text_delta` yoksa genel bir "Cevap üretilmedi." mesajı gösterilir.
6. Doğrulama sayfası (`/`, `frontend/src/App.tsx`) değişmez.
7. `citation` her etiket için bir chip olarak, `source_chip`'lerden önce çizilir (`Chat.tsx` › `Citations`); `error` olan turda gösterilmez (madde 4). Eşleşen chip `[chunk_id] title › section · rev revision · effective_from` alanlarını olduğu gibi yazar; `status` `superseded` ise "ESKİ SÜRÜM" rozeti ekler (durum olaydan okunur, türetilmez). `dogrulandi: false` chip kırmızıdır ve yalnızca kimlikle "doğrulanamadı" der. Turda `search_documents` için `tool_call` geldiyse, döngü `tamam` ile bittiyse ve hiç `citation` gelmediyse tek satırlık uyarı çıkar ("Cevap belge kaynağına atıf yapmıyor; doğrulanamaz."). Uçuş soruları bu uyarıyı almaz. Tool adı yalnızca bu koşul için istemcide sabittir; `atifsiz` kodlanınca uyarı ona bağlanmalıdır (`Kapsam dışı`, Atıf olayı).

8. `chart_card` Apache ECharts ile (`Chart.tsx`) cevabın altında satır içi çizilir: `chart_type` `bar_horizontal`, `bar_vertical`, `pie` ya da `line`. Grafiğin altında aynı noktaların tablosu, kesilme (`groups_total` > `items`) ve `unclassified` notu vardır. Sayılar, sıra ve etiketler olaydan olduğu gibi çizilir; başlıktaki ad eşlemesi yalnızca görünümdür. Grafik türünü kullanıcı belirler; belirtmediyse modelin türü sorması `get_chart_data` açıklamasındadır (talimat sürümü değişmedi).

## Kapsam dışı

- Geçmişin kalıcılığı (disk, veritabanı), çoklu backend örneği ve oturum paylaşımı: oturumlar bellekte tutulur.
- Canlı metin akışı: cevap tur bitince gelir.
- Token sayıları: `AgentResult`'ta yoktur; ölçüm `scripts/agent_run.py`'deki istemci sarmalayıcısıyla yapılır.
- İstemcinin bağlantıyı kesmesiyle döngünün durdurulması (`docs/agent.md` › Kapsam dışı).
- `get_flight_details` için tazelik eşiği (`max_age`): ayrı iş.
