# Sohbet geçmişi ve genel grafik sorgusu: tasarım

Tarih: 2026-10-30. Durum: onay bekliyor. İki alt iş, tek spec; her biri ayrı plan ve ayrı uygulama döngüsüdür. Sıra: **A (oturum geçmişi)**, sonra **B (genel grafik sorgusu)**; B'nin "tür sorusuna kısa cevap" akışı A'ya dayanır.

## Amaç ve başarı ölçütleri

Kullanıcı sohbette (1) önceki cevaba yaslanan takip mesajları yazabilir, (2) uçuş listesinin herhangi bir alanına göre gruplanmış, istediği türde grafik isteyebilir. Operasyonel sayıyı model üretmez; sayı yalnızca o turun tool sonucundan gelir.

| # | Ölçüt | Nasıl sınanır |
|---|---|---|
| 1 | "Bugünkü gelenleri havayoluna göre grafiğe dök" → model türü sorar → kullanıcı "pasta" der → pasta çizilir. | `/chat` testi: iki istek, aynı `session_id`; ikinci istekte model isteğine önceki tur girer, `get_chart_data` çağrılır. |
| 2 | "Gelen ve giden uçakları pasta grafikte göster" → iki dilim (`ARRIVAL`, `DEPARTURE`). | `get_chart_data` testi: `group_by movement_type`, sonuç iki öğe, toplam 600. |
| 3 | Listedeki her alan gruplanabilir, süzülebilir, uygun alan ölçülebilir. | `FIELDS` kaydı ile kontrat enum'ları eşit; her alan için en az bir sorgu testi. |
| 4 | İstemci geçmiş gönderemez; sahte asistan turu enjekte edilemez. | `ChatRequest` fazla alanı reddeder; geçmiş yalnızca sunucu belleğinden gelir. |
| 5 | Veride olmayan istek (yolcu, doluluk, çok günlü trend) çizilmez. | Tool açıklaması + talimat; model "mevcut verilerle çizilemiyor" der. |

Değişmeyenler: model hesap yapmaz (CLAUDE.md › Yasaklar), tool zarf sözleşmesi (`docs/zarf.md`), kartlar zarfı yorumlamaz (`docs/chat.md` › Kod garantileri), hata ayrıntısı istemciye gitmez.

## A. Oturum geçmişi

### Karar

Geçmişi **sunucu** tutar (bellekte, kalıcılık yok). İstemci yalnızca `session_id` taşır. Seçilmeyen: istemcinin geçmişi göndermesi (sahte "asistan" turu enjeksiyon yoludur, `docs/enjeksiyon.md` yüzeyi büyür) ve karma yol (gereksiz karmaşa).

### İstek ve yanıt

- `POST /chat` gövdesi: `{"message": "...", "session_id": "...", "selected": {...}}`. `session_id` isteğe bağlıdır; ek alan 422.
- `session_id` yok ya da sunucuda yoksa (süre doldu, sunucu yeniden başladı, bilinmeyen id) yeni oturum açılır. Hata değildir.
- `done` olayına iki alan eklenir: `session_id` (oturumun kimliği) ve `session_reset` (istek bir `session_id` taşıyordu ama oturum bulunamadığı için yenisi açıldıysa `true`, aksi halde `false`).
- `session_id` biçimi: sunucunun ürettiği 32 hex (`secrets.token_hex(16)`). Biçime uymayan değer 422 (uyduruk id denemesi). Tahmin edilemez olduğu için tek koruma budur; kimlik doğrulama bu işin kapsamı dışındadır (`docs/spec.md` §1).

### Ne saklanır

Her tamamlanan tur için bir kayıt: `{question, answer, tool_calls: [{name, input}]}`.

- `question`: orijinal kullanıcı mesajı (`Haritada seçili: …` notu hariç).
- `answer`: `AgentResult.text`, yani yalnızca `tamam` turlarında. `tamam` olmayan tur (hata, sınır) geçmişe **girmez**; kısmi cevap kaydedilmez (`docs/chat.md` › Kod garantileri 8).
- `tool_calls`: yalnızca `executed: true` çağrıların `name` ve `input`'u. Tool **sonuçları, zarflar, grafik noktaları saklanmaz**. Sebep: yeni sayı yalnızca bu turun tool çağrısından gelmelidir; eski tarif ise ("pasta yap" diyen kullanıcı hangi `group_by`'ı kastediyor) takip sorusu için gerekir.

### Modele nasıl gider

Önceki turlar, bu turun mesajından önce düz metin `user`/`assistant` turları olarak eklenir. Asistan metninin sonuna tool çağrılarının kısa notu eklenir:

```text
<cevap metni>

[Önceki turda çağrılan araçlar: get_chart_data {"chart_type": "pie", ...}]
```

- `tool_use`/`tool_result` blokları **kullanılmaz**: döngünün `response.content` kuralı (thinking blokları dahil) yalnızca o turun içindir ve geçmişe taşınmaz.
- Not satırı ve cevap metni modele **veri** olarak gider; `agent._execute`'un `search_documents` çevrelemesi (`<belge id>`, `docs/enjeksiyon.md`) geçmiş için gerekmez, çünkü geçmiş yalnızca sunucunun kendi ürettiği cevaplardır, belge parçası ham olarak girmez.
- `run_agent(question, client=None, instruction_version=None, history=None)`: `history`, `[{"question": ..., "answer": ..., "tool_calls": [...]}]` ya da `None`. `None` ve boş liste bugünkü davranışla birebir aynıdır (`tests/test_agent.py` değişmez). `AgentResult`'a geçmişle ilgili alan eklenmez.

### Sınırlar

| Sınır | Değer | Aşılınca |
|---|---|---|
| Modele giden tur sayısı | son 6 | Eski turlar modele gitmez, bellekte kalır |
| Modele giden toplam karakter (cevaplar + notlar) | 12000 | En eski turdan başlayarak atılır, hiçbir tur ortadan kesilmez |
| Bellekteki oturum sayısı | 100 | En eski kullanılan oturum atılır (LRU) |
| Oturum başına saklanan tur | 20 | En eski tur atılır |
| Hareketsizlik süresi | 2 saat | Oturum bir sonraki istekte bulunamaz sayılır |

Saat okuması yalnızca `backend/clock.py` içindedir (`tests/test_clock.py` tarar); sona erme `now()` ile hesaplanır ve testte `COPILOT_NOW` ile sabitlenir. Değerler `backend/session.py` içinde sabittir, `.env`'e açılmaz (YAGNI).

### Eşzamanlılık ve yazma anı

- Oturum deposu kilitlidir; `/chat` thread havuzunda çalıştığı için depo erişimi `threading.Lock` ile korunur.
- Aynı oturuma aynı anda iki istek gelirse ikisi de o ana kadarki geçmişi okur; turlar tamamlanma sırasıyla eklenir. Sıralama garantisi verilmez (tek kullanıcılı arayüz).
- Tur, akış bitince `ChatStream` bitişinde (audit satırının yazıldığı yerde) `tamam` ise geçmişe eklenir. İstemci kopsa bile döngü sürüyorsa tur tamamlanınca eklenir (audit ile aynı kural).

### Talimat

Yeni sürüm `v5` (`backend/instructions/v5.md`): **v4**'ün üstüne tek yeni ilke (14), geçmişe nasıl davranılacağı. `v4`, enjeksiyon ilkesini (13) içerdiği için temel o seçilir; varsayılan sürüm değişmez (`v3` kalır), geçiş kullanıcının kararıdır ve ölçüme bağlıdır. İlke 14'ün içeriği:

- Önceki turlardaki sayı ve durumlar yalnızca bağlamdır; bu turun cevabı için sayı gerekiyorsa tool'u yeniden çağır, önceki cevaptan sayı verme. (Mevcut ilke 2'yi geçmiş durumuna uygular.)
- Kullanıcının kısa cevabı ("pasta", "evet", "gelenler") önceki turdaki sorunun cevabıdır; önceki araç notundaki tarifi koruyup yalnızca değişen kısmı güncelle.
- Önceki turdan emin olamıyorsan kullanıcıya sor, tahmin etme.

Metin kuralları aynen geçerlidir (`docs/system-talimat.md`): rakam, `{}`, model adı yok; `snake_case` yalnızca kayıtlı tool adlarında; dosya ≤ 40 satır; Değişiklik günlüğüne `5.0.0` satırı ve `VERSIONS["v5"]` birlikte eklenir. Sürümlü testler (`tests/test_instruction_v3.py` parametreleri) `v5`'i de kapsar.

### Audit

Soru satırına iki alan eklenir: `session_id` ve `turn_index` (oturumdaki bu turun sırası, 1'den). Eski satırlarda yoktur; okuyan kod `record.get(...)` kullanır (CLAUDE.md › Kurallar). Geçmişin içeriği audit'e girmez; `question` ve `answer` kaydı bugünkü gibidir.

### Arayüz

- `Chat.tsx` `session_id`'yi `done`'dan alıp bir sonraki mesajla gönderir. `session_reset: true` ise ekranda tek satırlık not: "Önceki konuşma sıfırlandı; bu soru bağımsız yanıtlandı."
- "Yeni konuşma" düğmesi `session_id`'yi bırakır ve ekrandaki turları temizler.
- Mesajla birlikte giden `selected` yalnızca o mesaja özgü kalır ve geçmişe girmez.
- "Her soru bağımsız gönderilir" notu (`Chat.tsx` başlığı) kalkar, yerine oturum açıklaması gelir.
- `chat.ts` `streamChat` `sessionId` alır; `isDone` yeni alanları doğrular.

### Belgeler

`docs/chat.md` (Uç, `done` olayı, Talimat, Arayüz kuralları), `docs/agent.md` (Girdi; "konuşma geçmişi" kapsam dışından çıkar), `docs/system-talimat.md` (günlük), `docs/audit.md`, `docs/sorumluluk-zinciri.md` (Açık soru 1 kapanır ve karar tabloya işlenir), CLAUDE.md (`backend/main.py` ve `chat.ts` özetleri).

## B. Genel grafik sorgusu

### Karar

`get_chart_data` kapalı bir enum listesinden **düz uçuş görünümü** üzerinde genel bir sorguya döner. Kontrat sürümü `1.0.0` → `2.0.0`; eski argümanlar (`group_by: airline`, `metric`, `direction`, `include_cancelled`) yeni şemanın alt kümesi değildir, mevcut testler (`tests/test_chart.py`) yeni şemaya taşınır.

### Düz uçuş görünümü

Her uçuş için bir satır; `backend/tools/chart_fields.py`'deki **tek** `FIELDS` kaydıyla tanımlanır. Kontrattaki alan enum'ları bu kayıtla birebir eşit tutulur (kontrat elle yazılır, test eşitliği denetler) (`importlib.util.find_spec` ile modülün varlığı da sınanır).

Birleştirme (yetim kayıtlar kullanılmaz, `docs/tools.md` › Veri kaynağı):

- `flights` temel satırdır (`flight_id`).
- `movements` `flight_id` ile (uçuş başına bir hareket; yoksa uçuş kapsam dışı).
- `delays` `flight_id` ile; yoksa gecikme alanları satırda yoktur.
- `aircraft` `registration` ile (`type_icao` yalnızca doğrulama için, `aircraft_type` `flights`'tan gelir; `code_letter`, `operator_iata` buradan).
- `stands` `movements.stand_code` ile (`stand_type`, `max_code_letter`).

| Alan | Tür | Kaynak |
|---|---|---|
| `airline` | kategorik | `flights.flight_no`'nun ilk iki karakteri (büyük harf) |
| `flight_no`, `callsign`, `registration` | kategorik | `flights` |
| `aircraft_type`, `origin`, `destination` | kategorik | `flights` |
| `code_letter`, `operator_iata` | kategorik | `aircraft` |
| `movement_type` | kategorik | `movements` (`ARRIVAL`, `DEPARTURE`) |
| `stand_code`, `gate_code` | kategorik | `movements` |
| `stand_type`, `max_code_letter` | kategorik | `stands` |
| `delay_code`, `delay_category` | kategorik | `delays` |
| `cancelled` | kategorik | `flights.cancelled` (`true`/`false`, metin olarak) |
| `status` | kategorik | `cancelled` ise `cancelled`; gecikme kaydı varsa `delayed`; yoksa `on_time` |
| `scheduled_time`, `estimated_time` | zaman | `flights` |
| `actual_runway_time`, `actual_block_time` | zaman | `movements` |
| `delay_minutes` | sayısal | `delays.delay_minutes` |

- Kaynakta değeri olmayan alan (`null` ya da kayıt yok) satırda yoktur; o alana göre gruplamada uçuş `unclassified` sayılır, süzgeçte o alana bağlı koşul sağlanmaz.
- `origin`/`destination` kayıttaki IATA koddur (yerel havalimanı `XXXX`); dönüştürülmez.
- `airline` kodu havayolu adına çevrilmez (veride ad tablosu yok).

### Argümanlar (`input_schema`)

| Alan | Zorunlu | Değerler | Varsayılan |
|---|---|---|---|
| `chart_type` | evet | `bar_horizontal`, `bar_vertical`, `stacked_bar`, `grouped_bar`, `pie`, `doughnut`, `line`, `area`, `heatmap` | — |
| `group_by` | evet | `{"field": <alan>, "bucket": "hour"\|"half_hour"}`; `bucket` yalnızca zaman alanıyla | — |
| `series_by` | hayır | `group_by` ile aynı biçim; kategorik alan | yok |
| `measure` | hayır | `{"agg": "count"\|"sum"\|"avg"\|"min"\|"max", "field": <sayısal alan>}`; `count`'ta `field` yok | `{"agg": "count"}` |
| `filters` | hayır | `[{"field": <alan>, "op": "eq"\|"ne"\|"in"\|"gt"\|"ge"\|"lt"\|"le", "value": ...}]` | `[]` |
| `sort` | hayır | `value_desc`, `value_asc`, `label` | `value_desc` (zaman bucket'ı varsa `label`) |
| `limit` | hayır | `5`, `10`, `20`, `50` | `10` |
| `derive` | hayır | `"pct_change_vs_previous"` (yalnızca `group_by` zaman kovasıyla) | yok |
| `plot` | hayır | `"value"`, `"change_pct"` | `"value"` |

- Kontrat kuralı (CLAUDE.md): her object `additionalProperties: false`; `minLength`/`maxLength`/`minimum`/`maximum`/`multipleOf` kullanılmaz, biçim `pattern`/`enum` ile.
- `filters[].value`: `eq`/`ne`/`gt`/`lt` için tek değer (metin, sayı ya da mantıksal); `in` için en az bir öğeli dizi (en çok 20 öğe, `maxItems` yasağı nedeniyle kodda denetlenir). `gt`/`ge`/`lt`/`le` yalnızca sayısal ve zaman alanlarında. Zaman alanlarında değer iki biçimden biridir: (a) ISO 8601 zaman (saat dilimi zorunlu; karşılaştırma kronolojik) ya da (b) tarihsiz `"HH:MM"` (`^([01]\d|2[0-3]):[0-5]\d$`; kaydın yerel saat bölümüyle, tarihe bakmadan karşılaştırılır). (b) modelin günün tarihini bilmesini gerektirmez; veri tek günlük olduğu için gün süzgecine gerek yoktur (çok günlü veri kapsam dışıdır). `eq`/`ne`/`in` zaman alanlarında yine yalnızca bu iki biçimle çalışır.
- `sort` ve `limit` `bucket`'lı (zaman) ve `status` gruplamasında **yok sayılır**: tüm gruplar saat artan sırayla (`status`: `cancelled`, `delayed`, `on_time`) gelir.
- `series_by` varsa `limit` yalnızca `group_by`'ın kategorilerine uygulanır; seri sayısı en çok 8 (en büyük 8 seri, sırası toplam değere göre, eşitlikte etiket); kalan seriler `series_truncated` sayısına yazılır.
- Şemanın anlatamadığı kurallar `ARG_CHECKS` ile (ihlal `SCHEMA_VALIDATION_FAILED`, author `layer`, mesaj genel):
  - `line`/`area`: `group_by` zaman alanı ve `bucket` ile.
  - `stacked_bar`/`grouped_bar`/`heatmap`: `series_by` zorunlu.
  - `pie`/`doughnut`: `series_by` olmaz.
  - `series_by` ≠ `group_by.field`.
  - `sum`/`avg`/`min`/`max`: `field` sayısal alan; `count`: `field` yok.
  - `gt`/`ge`/`lt`/`le`: alan sayısal ya da zaman; `in`: dizi, diğerleri: dizi değil.
  - `derive` yalnızca `group_by` zaman alanı ve `bucket` ile; `plot` `change_pct` ise `derive` zorunlu ve `chart_type` yalnızca `bar_horizontal`, `bar_vertical`, `grouped_bar`, `line`, `area` olabilir (`pie`, `doughnut`, `stacked_bar`, `heatmap` ile negatif değerler anlamsızdır).
  - `value`'nun türü alana uyar (sayısal alana metin yok vb.).
  - Hücre sayısı (grup × seri) en çok 200.

### `value` (`value_schema`)

```text
date              : meta.date
chart_type        : doğrulanmış argüman
group_by          : {"field", "bucket"?}
series_by         : {"field", "bucket"?}   (yoksa anahtar yok)
measure           : {"agg", "field"?}
flights           : süzgeçten geçen uçuş sayısı
groups_total      : kesilmeden önce grup sayısı
unclassified      : group_by (ya da series_by) alanı kayıtta olmadığı için gruba girmeyen uçuş
series_truncated  : kesilen seri sayısı (series_by varsa)
derive            : "pct_change_vs_previous" (yoksa anahtar yok)
plot              : "value" | "change_pct"
items             : [{"label": "...", "series"?: "...", "value": sayı, "change_pct"?: sayı, "trend"?: "up"|"down"|"flat"}]
```

- `items` düz satırlardır. Sıra: önce grup sırası (yukarıdaki kurallar), grup içinde seri sırası. `series` yalnızca `series_by` varsa vardır.
- **Türetilmiş değişim (`derive`).** Her `items` satırı için, **aynı seride hemen önceki kova** (saat için bir önceki saat, `half_hour` için bir önceki yarım saat) varsa ve değeri sıfırdan büyükse `change_pct` = (bu − önceki) / önceki × 100 (bir ondalığa yuvarlanır, tek yuvarlama noktası) ve `trend` (`up` ham değer önceki değerden büyükse, `down` küçükse, `flat` eşitse) eklenir. Önceki kova yoksa (o saatte uçuş yok, süzgeç dışında kaldı ya da ilk kova) ya da değeri sıfırsa bu iki alan satıra **hiç yazılmaz**: sıfıra bölme, sonsuz ya da uydurma yüzde olmaz. `plot` `change_pct` ise grafik yalnızca `change_pct` taşıyan satırları çizer; satırın `value`'su (ham sayı) yine `items`'ta ve tabloda vardır.
- `measure.agg` `avg` ise değer bir ondalığa yuvarlanır (tek yuvarlama noktası, tool içinde); `sum`/`min`/`max` tamsayıdır (`delay_minutes` tamsayı).
- Gecikme ölçüleri (`delay_minutes` üzerinden) yalnızca gecikme kaydı olan uçuşlardan hesaplanır; gecikmeli uçuşu olmayan hücre `items`'ta yer almaz. `count` bütün süzgeçli uçuşları sayar.
- Hiçbir hücre boş değerle (`null`) yazılmaz (`docs/tools.md` › Veri kaynağı).
- `unclassified` hem `group_by` hem `series_by` alanı eksik olan uçuşları bir kez sayar.

### Hata eşlemesi

`docs/tools.md` › Hata eşlemesi geçerlidir: geçersiz tarif `SCHEMA_VALIDATION_FAILED` (author `layer`); veri okunamazsa genel mesaj; hiçbir kombinasyon `NOT_FOUND` üretmez (süzgeç sonucu boşsa `items` boş, `flights` 0 olur, hata değildir).

### `chart_card` ve arayüz

- `chart_card`: zarfın `value`'su olduğu gibi artı `tool`, `filters`, `source`, `as_of` (bugünkü kural, `docs/chat.md`).
- `Chart.tsx` tür başına bir `option()` üreticisi kaydıdır (`CHART_RENDERERS`); yeni tür = üretici + enum girişi + test.
  - `bar_horizontal`/`bar_vertical`: tek seri, `series` yok.
  - `stacked_bar`/`grouped_bar`/`area`/`line`: `items` `series`'e göre bölünür, her seri bir çizgi/çubuk dizisi (bu bir **yerleştirmedir**, toplam ya da yüzde hesaplanmaz).
  - `pie`/`doughnut`: tek dilim dizisi; ECharts'ın otomatik yüzde etiketi **kapalıdır** (`label.formatter` yalnızca ad, tooltip yalnızca değer).
  - `heatmap`: `group_by` x ekseni, `series_by` y ekseni, `value` renk ölçeği.
- Grafik başlığı `measure`, `group_by`, `series_by` ve `filters`'tan **görünüm metni** olarak kurulur (ör. "Uçuş sayısı · movement_type · saat"); alan adlarının Türkçe karşılıkları `Chart.tsx`'te yalnızca görünümdür, bilinmeyen kod olduğu gibi gösterilir.
- `plot` `change_pct` iken çubuk/çizgi `change_pct` değerini çizer; her noktanın etiketi sunucunun verdiği `trend` ve `change_pct`'den kurulur (`▲ 12,5%`, `▼ 3,0%`, `▬ 0,0%`; ondalık ayracı yalnızca görünümdür) ve renk `trend`'e göre seçilir. Arayüz değişimi kendisi hesaplamaz.
- Altındaki tablo düz `items` satırlarıdır (denetlenebilirlik; `change_pct`/`trend` varsa ek sütun); kesilme ve `unclassified` notları bugünkü gibi, `series_truncated` eklenir.

### Tool açıklaması

Kural: ne döndürür / ne zaman kullanılır / ne zaman KULLANILMAZ, örnek ve enum (CLAUDE.md › Kurallar). Ek olarak:

- Doğal dil eşlemesi için kısa tarif örnekleri (5-6 satır): "gelen ve giden" → `group_by movement_type`; "saat saat gelen/giden yığılmış çubuk" → zaman alanı + `bucket hour` + `series_by movement_type`; "tip bazında ortalama gecikme" → `aircraft_type` + `avg delay_minutes`; "60 dakikadan fazla gecikenler" → `delay_minutes gt 60`.
- `chart_type` kullanıcıdan gelir; belirtmediyse tool çağrılmadan önce tür sorulur (A ile birlikte kısa cevap çözülür).
- Veride olmayan istek (yolcu, doluluk, çok günlü trend) için çağrılmaz.
- Açıklamanın uzunluğu tool tanımı kuralıyla uyumlu kalır; ayrıntı alan açıklamalarındadır.

### Belgeler

`docs/tools.md` (`get_chart_data` bölümü baştan), `docs/chat.md` (`chart_card`, Arayüz kuralları 8), kontrat JSON, CLAUDE.md özeti.

## Test planı

| Dosya | Kapsam |
|---|---|
| `tests/test_session.py` (yeni) | Depo: ekleme, LRU, 20 tur, 2 saat sona erme (`COPILOT_NOW`), 6 tur / 12000 karakter kırpma; `tamam` dışı tur kaydedilmez; kilit altında eşzamanlı ekleme. |
| `tests/test_chat.py` | `session_id` olmadan yeni oturum; ikinci istekte model isteğinde önceki turlar (metin turları + araç notu); ek alan 422; biçimsiz id 422; `done` alanları; bilinmeyen id → `session_reset`. Kesilen akış: tur yine eklenir. |
| `tests/test_agent.py` | `history=None` / boş liste davranışı aynı; geçmiş mesajları sırayla; `response.content` kuralı bu tura özgü kalır. |
| `tests/test_audit.py` | `session_id` / `turn_index` alanları; eski satırlar okunur. |
| `tests/test_instruction_v5.py` (yeni) | v5 = v4 + ilke 14; yazım kuralları; günlük; `VERSIONS`. |
| `tests/test_chart.py` | `FIELDS` ↔ kontrat enum eşitliği; her alan için gruplama; birleştirme (aircraft, stands); `movement_type` iki dilim (300/300); saat × yön yığılmış toplamı; süzgeç `eq`/`ne`/`in`/`gt`/`lt` (sayısal ve zaman); `unclassified`; `series_truncated`; hücre sınırı; tüm `ARG_CHECKS` ihlalleri veriyi okumadan reddedilir; beklenen sayılar test içinde bağımsız hesaplanır (CLAUDE.md: olay/liste üzerinde gezen testte önce türün var olduğu assert edilir). |
| `tests/test_chart.py` (Q2 kabul testi) | Test günü `2026-10-20` (`COPILOT_DATA` referans dosya, `COPILOT_NOW` aynı gün): "gelen-giden uçuşların 18:00'deki sayısının 17:00'ye göre değişimi" tarifi (`scheduled_time ge "17:00"` ve `lt "19:00"`, `group_by` saat kovası, `series_by movement_type`, `derive pct_change_vs_previous`, `plot change_pct`, `bar_horizontal`) için `items`, dosyadan bağımsız hesaplanan 17 ve 18 sayılarıyla `change_pct`/`trend` değerlerini eşler; 17:00 satırında `change_pct` yoktur. |
| Frontend | Test çalıştırıcı yok (CLAUDE.md); `chat.ts` doğrulayıcıları `node` ile, `Chart.tsx` tarayıcıda elle denenir. |

Ağ ve ücretli çağrı yok; tüm testler sahte istemciyle çalışır. Gerçek model denemesi (tür sorusu, takip cevabı) bu işin dışındadır; istenirse tek elle deneme olarak ayrıca onaylanır.

## Kapsam dışı

- Oturum kalıcılığı (disk/veritabanı), çoklu backend örneği, oturum paylaşımı.
- Kimlik doğrulama ve kullanıcıya göre oturum (`docs/spec.md` §1).
- Geçmiş özetleme/sıkıştırma (token optimizasyonu); yalnızca son 6 tur ve karakter sınırı.
- Tool sonucu/zarf saklama ve geçmişten yeniden sunma.
- Radar, ağaç haritası, dağılım grafiği, huni vb. türler (kayıt genişletilebilir tasarlanır, eklenmez).
- Sırt sırta (butterfly) çubuk düzeni: iki seriyi ortak eksenin iki yanına çizen tür eklenmez; `grouped_bar` aynı yöne çizer.
- Tarihe göre süzme/çok günlü veri: tarihsiz `"HH:MM"` süzgeci veri tek günlük olduğu sürece geçerlidir.
- Uçuş listesi dışı veriler (yolcu, stand doluluğu, çok günlü trend) ve başka tool'ların sonuçlarının grafiğe bağlanması.
- `v5`'e varsayılan geçiş ve enjeksiyon saldırı seti ölçümü (ücretli, ayrı karar).
- Kalan 3 bilinen kırmızı test (`test_http`, `test_map_tools`, `test_prompts`) ve talimatın harita/grafik tool'larına yetişmesi.

## Riskler

| Risk | Önlem |
|---|---|
| Oturum belleği büyür | 100 oturum × 20 tur × birkaç KB; LRU ve sona erme. |
| Geçmişteki eski sayı yeni cevaba sızar | Talimat ilkesi 14 + yalnızca sunucunun kendi cevapları; tool sonucu saklanmaz. Ölçüm ücretli ve ayrı. |
| Model geçersiz tarif üretir | `SCHEMA_VALIDATION_FAILED` ile bir kez düzeltme (ilke 5); hata mesajı genel kalır. |
| Alan kaydı ile kontrat ayrışır | Eşitlik testi: kontrat enum'ları `FIELDS` ile birebir aynı olmak zorunda. |
| Büyük sorgu (200+ hücre) ekranı bozar | Hücre sınırı, `limit`, `series_truncated`. |
