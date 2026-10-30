# Genel Grafik Sorgusu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `get_chart_data` uçuş listesinin herhangi bir alanına göre gruplama, süzme ve ölçme yapsın; sohbet dokuz grafik türünden istenenini çizsin.

**Architecture:** Düz uçuş görünümü (`chart_fields.py` › `FIELDS` + `build_rows`) üzerinde saf bir sorgu motoru (`chart_query.py`) çalışır; `get_chart_data` ikisini kontratla (`2.0.0`) birleştirir. `chart_card` zarfın `value`'sunu olduğu gibi taşır (kod değişmez). Arayüzde saf `chartOptions.ts` tür başına ECharts seçeneği üretir; `Chart.tsx` yalnızca çizer.

**Tech Stack:** Python 3.13, jsonschema, pytest; Vite + React + TypeScript, Apache ECharts.

**Spec:** `docs/superpowers/specs/2026-10-30-chat-gecmisi-ve-genel-grafik-design.md` (bölüm B). Bölüm A (oturum geçmişi) uygulandı ve `main`'dedir; "tür sorusuna kısa cevap" akışı ona dayanır.

## Global Constraints

- Tanımlayıcılar İngilizce; yorumlar, docstring'ler, kullanıcıya dönen mesajlar ve test isimleri Türkçe.
- Tool zarf sözleşmesi (`docs/zarf.md`): tool yalnızca `{value, source}` döndürür; saati okumaz; veri hatası `DataError` (`run_tool` bunu `SCHEMA_VALIDATION_FAILED`, author `layer` yapar). Kaynakta `null` olan alan `value`'ya yazılmaz.
- Kontrat kuralları (CLAUDE.md): her object `additionalProperties: false`; `minLength`/`maxLength`/`minimum`/`maximum`/`multipleOf`/`maxItems` kullanılmaz; sınırlar `enum`/`pattern` ya da kodda. Tek doğruluk kaynağı `backend/tools/contracts/get_chart_data.json`; `version` `2.0.0`.
- Model hesap yapmaz, seri yazmaz: sayı yalnızca tool'dan gelir. Arayüz toplam, yüzde ya da sıralama türetmez; pasta grafiğinde ECharts'ın yüzde etiketi **kapalıdır**.
- Sabitler (spec): gruplama `limit` ∈ {5, 10, 20, 50} (varsayılan 10); en çok 8 seri; hücre (grup × seri) üst sınırı 200; `in` değer dizisi en çok 20 öğe; `avg` bir ondalığa yuvarlanır (tek yuvarlama noktası).
- Süzgeç işleçleri: `eq`, `ne`, `in`, `gt`, `ge`, `lt`, `le`. Zaman alanlarında değer ISO 8601 (saat dilimi zorunlu) ya da tarihsiz `"HH:MM"`; ikincisi kaydın yerel saat bölümüyle, tarihe bakmadan karşılaştırılır.
- Türetilmiş değişim: `derive: "pct_change_vs_previous"` (yalnızca zaman kovasıyla), aynı seride hemen önceki kova varsa ve değeri sıfırdan büyükse `items` satırına `change_pct` (bir ondalık) ve `trend` (`up`/`down`/`flat`) eklenir; yoksa bu alanlar yazılmaz. `plot: "change_pct"` grafiğin değişimi çizmesini sağlar (yalnızca `bar_horizontal`, `bar_vertical`, `grouped_bar`, `line`, `area`).
- Test günü sabit: `2026-10-20` (`COPILOT_DATA=data/referans/seed42-2026-10-20.json`, `COPILOT_NOW=2026-10-20T16:22:00+03:00`). Kodda tarih varsayımı yoktur.
- Grafik türleri (dokuz): `bar_horizontal`, `bar_vertical`, `stacked_bar`, `grouped_bar`, `pie`, `doughnut`, `line`, `area`, `heatmap`.
- Zaman kovası etiketi: `hour` → `"14:00"`, `half_hour` → `"14:00"`/`"14:30"` (dakika < 30 → `:00`, değilse `:30`). Etiketler sözlük sırasıyla zaman sırasındadır.
- Talimat metni değişmez (tür sorma kuralı tool açıklamasındadır).
- Satır uzunluğu en çok 88 (elle uyulur). **Tam `pytest` ve `ruff` (check/format) bu planda hiç çalıştırılmaz** (kullanıcı kararı); yalnızca adı geçen test dosyaları ve frontend `build`/`lint` koşulur. Sistem saati `backend/clock.py` dışında okunmaz.
- Commit mesajı `M8.3 - ...` önekiyle ve `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` satırıyla biter. Çalışma `grafik-sorgusu` dalında yapılır (main'den).

## Review Focus

0. Q2 kabul senaryosu: "gelen-giden 18:00 vs 17:00 değişimi, yukarı/aşağı ok ve % ile yatay çubuk": tarihsiz saat süzgeci, `derive` ve `plot change_pct` birlikte doğru değerleri verir; 17:00 satırında değişim yoktur, ok/yüzde uydurulmaz. (Task 2, 3, 4)
1. Süzgeç hiçbir uçuşu bırakmaz: hata değil; `flights` 0, `items` boş; arayüz boş grafikle çökmez. (Task 2, 4)
2. Zaman süzgeci: ISO değer farklı saat dilimiyle kronolojik doğru karşılaştırılır; `"24:00"`, `"7:5"`, saat dilimsiz ISO biçimsizdir ve `SCHEMA_VALIDATION_FAILED` verir. (Task 2)
2b. Önceki kova sıfır ya da yok (ilk saat, uçuşsuz saat, süzgeç dışı saat): `change_pct`/`trend` yazılmaz, sıfıra bölme ya da sonsuz yüzde çıkmaz; seri başına ayrı hesaplanır. (Task 2)
3. `in` boş dizi ya da 21 öğe, sayısal alana metin değer, `gt` kategorik alanda: reddedilir. (Task 2)
4. `avg_delay` gibi ölçülerde gecikmesiz uçuş gruba katkı vermez; `count` tüm süzgeçli uçuşu sayar. (Task 2)
5. Dokuzuncu ve sonraki seriler: en büyük 8 kalır, `series_truncated` doğru, kalan seriler hücre sayısını bozmaz. (Task 2)
6. Modelin ek alan (`series`, `pax` gibi bilinmeyen `field`) göndermesi şema hatasıdır, veri okunmaz. (Task 3)
7. `stacked_bar`/`grouped_bar`/`heatmap` `series_by` olmadan, `line`/`area` zaman dışı alanla: reddedilir. (Task 2)

---

### Task 1: Düz uçuş görünümü (`FIELDS`, `build_rows`)

**Files:**
- Create: `backend/tools/chart_fields.py`
- Test: `tests/test_chart_fields.py`

**Interfaces:**
- Produces (Task 2 ve 3 kullanır):
  - `class Field(NamedTuple)`: `name: str`, `kind: Literal["categorical", "time", "numeric"]`.
  - `FIELDS: dict[str, Field]` — spec tablosundaki alanlar: kategorik `airline`, `flight_no`, `callsign`, `registration`, `aircraft_type`, `origin`, `destination`, `code_letter`, `operator_iata`, `movement_type`, `stand_code`, `gate_code`, `stand_type`, `max_code_letter`, `delay_code`, `delay_category`, `cancelled`, `status`; zaman `scheduled_time`, `estimated_time`, `actual_runway_time`, `actual_block_time`; sayısal `delay_minutes`.
  - `CATEGORICAL`, `TIME`, `NUMERIC: tuple[str, ...]` — `FIELDS`'ten türetilen ad demetleri (kontrat enum sırası bu sıradır).
  - `DATA_KEYS = ("meta", "flights", "movements", "delays", "aircraft", "stands")`.
  - `build_rows(data: dict) -> list[dict]`: uçuş başına bir satır (`flights` sırasıyla); satırda yalnızca kaynakta değeri olan alanlar bulunur; `cancelled` `"true"`/`"false"` metnidir; `status` `cancelled` ise `"cancelled"`, gecikme kaydı varsa `"delayed"`, değilse `"on_time"`; `airline` `flight_no`'nun ilk iki karakteri (büyük harf). Birleştirme: `movements` `flight_id` ile (hareketi olmayan uçuş **dışarıda**), `delays` `flight_id` ile, `aircraft` `registration` ile, `stands` `movements.stand_code` ile. `flights`'ta karşılığı olmayan (yetim) hareket/gecikme satırları kullanılmaz. Zorunlu alan (`flight_id`, `cancelled` flights'ta; `flight_id`, `movement_type` movements'ta; `flight_id`, `delay_minutes` delays'te) eksikse `DataError`.

- [ ] **Step 1: Failing testleri yaz** (`tests/test_chart_fields.py`; küçük elle yazılmış `data` sözlüğü ve referans dosya):
  - `test_modul_var`: `importlib.util.find_spec("backend.tools.chart_fields") is not None`.
  - `test_alan_listesi_spec_tablosuyla_birebir`: `CATEGORICAL`, `TIME`, `NUMERIC` demetleri yukarıdaki adlarla eşit (sıra dahil).
  - `test_airline_sefer_numarasinin_ilk_iki_karakteri`: `flight_no "tk2345"` → satır `airline == "TK"`.
  - `test_hareketi_olmayan_ucus_satir_olmaz_yetim_hareket_kullanilmaz`.
  - `test_kaynakta_null_olan_alan_satirda_yok`: iptal edilen uçuşun `stand_code: None`'u satırda anahtar olarak **yok** (ve `stand_type` de yok).
  - `test_status_cancelled_delayed_on_time`: üç uçuş, üç durum.
  - `test_cancelled_metin_true_false`.
  - `test_aircraft_ve_stand_birlesimi`: `registration` ile `code_letter`/`operator_iata`; `stand_code` ile `stand_type`/`max_code_letter`; eşleşme yoksa o alanlar satırda yok.
  - `test_zorunlu_alan_eksikse_veri_hatasi` (parametreli: `flights`'ta `cancelled`, `movements`'ta `movement_type`, `delays`'te `delay_minutes`): `DataError`.
  - `test_referans_gunde_satir_sayisi_ve_havayolu_dagilimi`: `data/referans/seed42-2026-10-20.json` ile `len(rows) == 600`; gelen (`movement_type == "ARRIVAL"`) uçuşların `airline` sayımı `[TK 154, AJ 34, QR 25, PC 23, AF 15, KL 13, LX 13, BA 10, LH 7, EK 6]`.

- [ ] **Step 2: Kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chart_fields.py -q`
Expected: tümü FAIL/ERROR (modül yok).

- [ ] **Step 3: `chart_fields.py`'yi yaz.** İndeksleri (`flights`, `delays`, `aircraft`, `stands`) önce sözlüğe çevir; satırları `flights` sırasıyla üret. Eksik/boş (`None`, `""`) değerli alan satıra yazılmaz.

- [ ] **Step 4: Yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chart_fields.py -q`
Expected: tümü PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/chart_fields.py tests/test_chart_fields.py
git commit -m "M8.3 - grafik için düz uçuş görünümü"
```

---

### Task 2: Sorgu motoru ve tarif denetimi (`chart_query.py`)

**Files:**
- Create: `backend/tools/chart_query.py`
- Test: `tests/test_chart_query.py`

**Interfaces:**
- Consumes: `FIELDS`, `CATEGORICAL`, `TIME`, `NUMERIC` (Task 1).
- Produces (Task 3 kullanır):
  - Sabitler: `MAX_SERIES = 8`, `MAX_CELLS = 200`, `MAX_IN_VALUES = 20`, `LIMITS = (5, 10, 20, 50)`, `BUCKETS = ("hour", "half_hour")`.
  - `check_query(args: dict) -> str | None`: şemanın anlatamadığı kuralları denetler (ihlalde Türkçe genel mesaj, yoksa `None`). Kurallar: `line`/`area` → `group_by.field` zaman alanı ve `bucket` var; `stacked_bar`/`grouped_bar`/`heatmap` → `series_by` var; `pie`/`doughnut` → `series_by` yok; `series_by.field != group_by.field`; `bucket` yalnızca zaman alanıyla, zaman alanı `bucket`'sız gruplanamaz; `series_by` kategorik alan ya da zaman alanı + `bucket`; `measure.agg == "count"` → `field` yok, diğer agg → `field` sayısal alan; her `filters[]`: `op` `in` ise `value` boş olmayan dizi ve en çok `MAX_IN_VALUES` öğeli, diğerlerinde dizi değil; `gt`/`ge`/`lt`/`le` yalnızca sayısal ve zaman alanlarında; sayısal alana yalnızca sayı, zaman alanına yalnızca geçerli ISO 8601 zaman (`datetime.fromisoformat`, saat dilimi zorunlu) ya da tarihsiz `"HH:MM"` (`^([01]\d|2[0-3]):[0-5]\d$`), kategorik alana metin ya da mantıksal (`cancelled` için mantıksal `true`/`false` ya da `"true"`/`"false"` metni kabul edilir); `derive` yalnızca `group_by` zaman alanı ve `bucket` ile; `plot == "change_pct"` ise `derive` zorunlu ve `chart_type` ∈ {`bar_horizontal`, `bar_vertical`, `grouped_bar`, `line`, `area`}; hücre üst sınırı: `series_by` varsa (grup üst sınırı × `MAX_SERIES`) ≤ `MAX_CELLS` — grup üst sınırı `hour` için 24, `half_hour` için 48, `status` için 3, diğerleri için `limit`. `args` şemadan geçmiş (varsayılanlar dolu) varsayılır.
  - `run_query(rows: list[dict], *, group_by: dict, series_by: dict | None, measure: dict, filters: list[dict], sort: str, limit: int, derive: str | None = None) -> dict`: `{"flights": int, "groups_total": int, "unclassified": int, "series_truncated": int (yalnızca series_by varsa), "items": [{"label": str, "series"?: str, "value": number, "change_pct"?: number, "trend"?: "up"|"down"|"flat"}]}`.

Davranış (spec B): süzgeçler VE ile uygulanır; `eq`/`ne`/`in`/`gt`/`ge`/`lt`/`le` (ISO zaman karşılaştırması `datetime.fromisoformat` ile kronolojik, tarihsiz `"HH:MM"` kaydın yerel saat bölümüyle; alanı satırda olmayan uçuş koşulu sağlamaz, `ne` dahil). `flights` = süzgeçten geçen satır sayısı. Etiket: kategorik alan değeri; zaman alanı + `bucket` kovası (Global Constraints). `unclassified` = süzgeçli satırlardan `group_by` ya da `series_by` alanı olmayanlar (bir kez sayılır). Grup/seri değeri = ölçünün o grubun (ya da serinin) **tüm** satırları üzerindeki toplulaştırması; hücre değeri grup×seri satırlarındandır. `count` tüm satırları; `sum`/`avg`/`min`/`max` yalnızca `field` değeri olan satırları kullanır, hiç satırı olmayan grup/hücre `items`'ta yer almaz. `avg` bir ondalığa yuvarlanır. Sıra: zaman kovası → etiket artan; `group_by.field == "status"` → `cancelled`, `delayed`, `on_time`; diğerleri `sort` (`value_desc` varsayılan, eşitlikte etiket artan; `value_asc`; `label`). `limit` yalnızca zaman kovası ve `status` dışında en büyük grupları tutar; `groups_total` kesilmeden önceki grup sayısı. `derive` verilmişse (yalnızca zaman kovasıyla): her satır için aynı seride hemen önceki kova (kova adımı kadar önceki etiket) `items`'ta varsa ve değeri sıfırdan büyükse `change_pct = round((v - önceki) / önceki * 100, 1)` ve `trend` (`up`: `v > önceki`, `down`: `v < önceki`, `flat`: eşit; ham değerlerle) eklenir, yoksa iki alan da yazılmaz. Seri: değere göre en büyük `MAX_SERIES` kalır (eşitlikte etiket), kalan sayısı `series_truncated`; `items` grup sırasıyla, grup içinde seri sırasıyla.

- [ ] **Step 1: Failing testleri yaz** (`tests/test_chart_query.py`; küçük elle satırlar, dosya okunmaz; her test beklenen listeyi tam değeriyle assert eder, önce türün/sayının var olduğunu doğrular):
  - `test_modul_var`.
  - Gruplama: `test_kategorik_alana_gore_sayim_degere_gore_azalan_etikete_gore_eşitlik`; `test_value_asc_ve_label_siralari`; `test_limit_kirpar_groups_total_kalir`.
  - Kova: `test_hour_kovasi_etiketi_HH_00_ve_zaman_sirasi_limitsiz`; `test_half_hour_kovasi_29_dakika_00_30_dakika_30`.
  - `test_status_siralamasi_sabit`.
  - Ölçüler: `test_sum_avg_min_max_delay_minutes`; `test_avg_bir_ondalik_yuvarlanir`; `test_gecikmesiz_ucus_ortalamaya_girmez_ve_bos_grup_items_ta_yok`; `test_count_tum_suzgecli_ucuslari_sayar`.
  - Süzgeç: `test_eq_ne_in`; `test_ge_le_dahil_gt_lt_haric`; `test_tarihsiz_saat_suzgeci_yerel_saat_bolumuyle_karsilastirir` (`"17:00"` ≤ kayıt < `"19:00"`; kayıt `+03:00`); `test_tarihsiz_saat_ve_iso_ayni_alanda_birlikte`; `test_ne_alani_olmayan_ucusu_gecirmez`; `test_gt_lt_sayisal`; `test_gt_lt_zaman_farkli_saat_diliminde_kronolojik` (aynı anı `+00:00` ve `+03:00` yazımıyla); `test_birden_cok_suzgec_ve_ile`; `test_hicbir_ucus_kalmazsa_items_bos_flights_sifir`.
  - Değişim (`derive`): `test_change_pct_onceki_saate_gore_bir_ondalik_ve_trend`; `test_ilk_kovada_degisim_yok`; `test_onceki_kova_yoksa_ya_da_sifirsa_alan_yazilmaz`; `test_degisim_seri_basina_ayri_hesaplanir`; `test_flat_esit_deger`; `test_derive_yoksa_change_pct_ve_trend_yok`.
  - İkinci boyut: `test_series_by_duz_satirlar_grup_sirasiyla`; `test_dokuzuncu_seri_series_truncated`; `test_series_by_yoksa_series_anahtari_ve_series_truncated_yok`.
  - `test_unclassified_group_ya_da_series_alani_eksik_bir_kez_sayilir`.
  - `check_query`: parametreli geçersizler (her biri tek ihlal, Review Focus 2/3/7): `line`+kategorik; `line`+`bucket`sız zaman; `stacked_bar` `series_by`sız; `heatmap` `series_by`sız; `pie`+`series_by`; `series_by` = `group_by`; `bucket` kategorik alanla; `count`+`field`; `sum` `field`sız; `sum`+kategorik alan; `in`+`[]`; `in`+21 öğe; `eq`+dizi; `gt`+kategorik; sayısal alana metin; zaman alanına `"dün"`; zaman alanına saat dilimsiz ISO; zaman alanına `"24:00"` ve `"7:5"`; `derive` kategorik gruplamayla; `derive` `bucket`sız zamanla; `plot change_pct` `derive`'sız; `plot change_pct` + `pie`/`stacked_bar`/`heatmap`; hücre sınırı (`series_by` + `half_hour`; `series_by` + `limit 50`); geçerli kontrol: `series_by` + `hour` + `limit` 10 `None` döner; `cancelled eq true` (mantıksal) ve `"true"` kabul edilir.

- [ ] **Step 2: Kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chart_query.py -q`
Expected: tümü FAIL/ERROR.

- [ ] **Step 3: `chart_query.py`'yi yaz.** Etiket üretimi tek fonksiyonda; toplulaştırma küçük bir `aggregate(rows, measure) -> number | None` yardımcısı (`None` = değer yok). Süzgeç değeri zaman alanında bir kez `fromisoformat`'la ayrıştırılır.

- [ ] **Step 4: Yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chart_query.py -q`
Expected: tümü PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/chart_query.py tests/test_chart_query.py
git commit -m "M8.3 - grafik sorgu motoru ve tarif denetimi"
```

---

### Task 3: Kontrat `2.0.0` ve `get_chart_data` yeniden bağlanır

**Files:**
- Modify: `backend/tools/contracts/get_chart_data.json` (baştan), `backend/tools/get_chart_data.py` (baştan), `backend/tools/__init__.py` (import ve `ARG_CHECKS`: `check_chart` → `check_query`)
- Test: `tests/test_chart.py` (baştan; mevcut kart testleri korunur)

**Interfaces:**
- Consumes: `build_rows`, `DATA_KEYS`, `CATEGORICAL`, `TIME`, `NUMERIC` (Task 1); `run_query`, `check_query`, `LIMITS`, `BUCKETS` (Task 2).
- Produces:
  - Kontrat `input_schema` (`additionalProperties: false`): `chart_type` (enum dokuz tür, zorunlu); `group_by` (`{"field": enum(CATEGORICAL + TIME), "bucket": enum(BUCKETS)}`, `field` zorunlu, zorunlu); `series_by` (aynı biçim); `measure` (`{"agg": enum(count,sum,avg,min,max), "field": enum(NUMERIC)}`, `agg` zorunlu, varsayılan `{"agg": "count"}`); `filters` (dizi; öğe `{"field": enum(tüm alanlar), "op": enum(eq,ne,in,gt,ge,lt,le), "value": tek değer ya da dizi}`, üç alan zorunlu, varsayılan `[]`); `sort` (enum, varsayılan `value_desc`); `limit` (enum `LIMITS`, varsayılan `10`); `derive` (enum `["pct_change_vs_previous"]`, isteğe bağlı); `plot` (enum `["value","change_pct"]`, varsayılan `"value"`).
  - Kontrat `value_schema`: spec B `value` (`date`, `chart_type`, `group_by`, `series_by?`, `measure`, `derive?`, `plot`, `flights`, `groups_total`, `unclassified`, `series_truncated?`, `items`; `items[]` `label`, `series?`, `value`, `change_pct?`, `trend?`).
  - Açıklama: ne döndürür / ne zaman kullanılır / ne zaman KULLANILMAZ; 5-6 satırlık doğal dil → tarif örneği ("gelen ve giden" → `group_by movement_type`; "saat saat gelen/giden yığılmış çubuk" → zaman alanı + `bucket hour` + `series_by movement_type`; "tip bazında ortalama gecikme"; "60 dakikadan fazla gecikenler" → `delay_minutes gt 60`; "18:00'deki sayının 17:00'ye göre değişimi, ok ve % ile yatay çubuk" → `scheduled_time ge "17:00"` + `lt "19:00"`, `group_by scheduled_time + hour`, `series_by movement_type`, `derive pct_change_vs_previous`, `plot change_pct`, `bar_horizontal`); `chart_type` kullanıcıdan gelir, belirtilmediyse tool çağrılmadan **"ÇAĞIRMA; önce hangi türü"** diye sorulur ve türler sayılır; veride olmayan istek (yolcu, doluluk, çok günlü trend) için çağrılmaz; sayıları kendin toplama/seri yazma.
  - `get_chart_data(chart_type: str, group_by: dict, series_by: dict | None = None, measure: dict | None = None, filters: list | None = None, sort: str = "value_desc", limit: int = 10, derive: str | None = None, plot: str = "value") -> dict` → `{"value", "source"}`; `value` `date` (`meta.date`) ve doğrulanmış argümanlar artı `run_query` sonucu.

- [ ] **Step 1: Failing testleri yaz** (`tests/test_chart.py`; `COPILOT_DATA`/`COPILOT_NOW` autouse; beklenenler dosyadan bağımsız hesaplanır, ayrıca sabit literal):
  - `test_tool_kayitli_ve_son_sirada` (korunur) ve `test_kontrat_aciklamasi_sorma_kuralini_ve_uc_soruyu_icerir` (korunur).
  - `test_kontrat_surumu_ve_semalari_gecerli`: `version == "2.0.0"`, iki şema `Draft202012Validator.check_schema`'dan geçer; kontrat dosyası `minLength|maxLength|minimum|maximum|multipleOf|maxItems` kelimelerini içermez; her `object` düğümünde `additionalProperties is False`.
  - `test_kontrat_alan_enumlari_FIELDS_ile_birebir_ayni`: `group_by.field` enum'u == `CATEGORICAL + TIME`, `measure.field` enum'u == `NUMERIC`, `filters[].field` enum'u == tüm alanlar (sıra dahil), `chart_type` enum'u dokuz tür.
  - `test_gelen_ve_giden_pasta_iki_dilim`: `{chart_type: pie, group_by: {field: movement_type}}` → `items == [("ARRIVAL", 300), ("DEPARTURE", 300)]` (eşitlikte etiket artan), `flights == 600`, `groups_total == 2`.
  - `test_gelen_ucuslar_havayoluna_gore`: `bar_horizontal`, `group_by airline`, `filters [{movement_type eq ARRIVAL}]` → `[TK 154, AJ 34, QR 25, PC 23, AF 15, KL 13, LX 13, BA 10, LH 7, EK 6]`, `flights == 300`.
  - `test_saat_x_yon_yigilmis_toplami_ucus_sayisina_esit`: `stacked_bar`, `group_by scheduled_time + hour`, `series_by movement_type` → `sum(value) == 600`, `series_truncated == 0`, her öğede `series` var.
  - `test_ortalama_gecikme_ucak_tipine_gore`: `measure {avg, delay_minutes}`; değerler testte `data/referans` üzerinden bağımsız hesaplanan ortalamalarla (bir ondalık) eşit.
  - `test_gecikme_60_dakikadan_fazla_suzgeci`: `delay_minutes gt 60` → `flights ==` bağımsız hesaplanan sayı; `status` boyutuyla `delayed` dışında öğe yok.
  - `test_tum_alanlar_gruplanabilir`: `CATEGORICAL + TIME` her biri için (zaman alanları `bucket hour` ile) çağrı hatasız döner ve `groups_total >= 1` (her alanda en az bir değer olduğundan emin olmak için `stand_type`, `max_code_letter`, `operator_iata` dahil).
  - `test_q2_gelen_giden_18_00_17_00_degisimi_yatay_cubuk` (kabul testi, test günü `2026-10-20`): tarif `{chart_type: bar_horizontal, group_by: {field: scheduled_time, bucket: hour}, series_by: {field: movement_type}, filters: [{scheduled_time ge "17:00"}, {scheduled_time lt "19:00"}], derive: pct_change_vs_previous, plot: change_pct}`. Beklenen, referans dosyadan bağımsız hesaplanır (17 ve 18 saatindeki ARRIVAL/DEPARTURE `scheduled_time` sayıları): `items` dört satır (17:00 ve 18:00 × iki seri); 17:00 satırlarında `change_pct`/`trend` yok; 18:00 satırlarında `change_pct == round((c18 - c17) / c17 * 100, 1)` ve `trend` işarete göre; `plot == "change_pct"`; `error is None`.
  - `test_degisim_tarifi_kart_olarak_tasinir`: aynı tarifin zarfından `CardBuilder` `chart_card`'ı, `items`'ta `change_pct`/`trend` ve `plot`'u aynen taşır.
  - `test_ek_alan_ve_bilinmeyen_alan_sema_hatasi_veriyi_okumaz` (parametreli, `COPILOT_DATA=yok.json`): `series: [1, 2]`; `group_by {field: pax}`; `measure {sum, field: airline}`; `chart_type donut`; `limit 7`; `filters [{field: airline, op: like, value: x}]`; `group_by` eksik; `author == "layer"`, `value is None`.
  - `test_gecersiz_tarif_kurallari_sema_hatasi_verir`: `check_query` ihlallerinden üçü (`line`+`airline`, `stacked_bar` `series_by`sız, `pie`+`series_by`) `run_tool` üzerinden `SCHEMA_VALIDATION_FAILED`, veri okunmaz.
  - `test_hicbir_ucus_kalmazsa_hata_degil_bos_items`: `filters [{airline eq ZZ}]` → `error is None`, `flights == 0`, `items == []`.
  - `test_veri_okunamazsa_genel_hata_doner` (korunur; yol sızmaz).
  - Kart testleri (korunur): `test_chart_karti_zarfin_alanlarini_oldugu_gibi_tasir` (kart `value`'yu, `filters`'ı, `source`/`as_of`'u aynen taşır; `items` düz satırlar), `test_hatali_zarftan_chart_karti_cikmaz`, `test_baska_tool_chart_karti_uretmez`.
  - `tests/test_tools.py` › `test_tool_definitions_kontratlarla_birebir_aynidir` kontrattan okuduğu için değişmeden geçer.

- [ ] **Step 2: Kırmızı doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chart.py -q`
Expected: yeni testler FAIL; korunan kart testleri eski kontratla geçebilir (bunlar regresyon korumasıdır, kırmızı sayısıyla birlikte raporla).

- [ ] **Step 3: Kontratı ve `get_chart_data.py`'yi yaz.** Kontrat JSON'u elle yazılır (enum'lar `FIELDS` ile aynı olmak zorunda; test denetler). Fonksiyon: `load_data(DATA_KEYS)` → `build_rows` → `run_query`; `meta.date` yoksa `DataError`. `check_chart` kaldırılır, `__init__.py` `check_query`'ye bağlanır.

- [ ] **Step 4: Yeşil doğrula**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chart.py tests\test_chart_fields.py tests\test_chart_query.py tests\test_tools.py -q`
Expected: tümü PASS (`test_tools.py` ~25 sn).

- [ ] **Step 5: Commit**

```bash
git add backend/tools backend/tools/contracts/get_chart_data.json tests/test_chart.py
git commit -m "M8.3 - get_chart_data genel sorgu (kontrat 2.0.0)"
```

---

### Task 4: Arayüz: tür başına seçenek üreticileri ve çizim

**Files:**
- Create: `frontend/src/chartOptions.ts`
- Modify: `frontend/src/chat.ts` (`ChartCard` tipi, `CHART_TYPES`, `isChart`), `frontend/src/Chart.tsx` (seçenekleri `chartOptions.ts`'ten alır, başlık, tablo, notlar)

**Interfaces:**
- Consumes: `chart_card` olayı = zarfın `value`'su + `tool`, `filters`, `source`, `as_of` (Task 3).
- Produces:
  - `chat.ts`: `CHART_TYPES` dokuz tür; `ChartItem = { label: string; series?: string; value: number; change_pct?: number; trend?: "up" | "down" | "flat" }`; `ChartCard = { tool; chart_type: ChartType; group_by: { field: string; bucket?: string }; series_by?: { field: string; bucket?: string }; measure: { agg: string; field?: string }; derive?: string; plot: "value" | "change_pct"; date: string; flights: number; groups_total: number; unclassified: number; series_truncated?: number; items: ChartItem[]; filters: Record<string, unknown>; source: string; as_of: string | null }`. `isChart` bunların hepsini doğrular; bilinmeyen tür ya da bozuk `items` kartı atlar.
  - `chartOptions.ts` (React/ECharts import'u **yok**, saf): `chartOption(card: ChartCard): Record<string, unknown>` — tür başına üretici kaydı `CHART_RENDERERS: Record<ChartType, (card: ChartCard) => Record<string, unknown>>`. Kurallar: `bar_horizontal` kategori ekseni ters (en büyük üstte), tek seri; `bar_vertical` tek seri; `stacked_bar` her `series` bir `bar` dizisi, hepsi `stack: "toplam"`; `grouped_bar` aynı dizi, `stack` yok; `line`/`area` her `series` bir `line` (area'da `areaStyle: {}`), x ekseni etiketler; `pie`/`doughnut` tek dilim dizisi (`doughnut`'ta `radius: ["40%", "65%"]`), `label.formatter` yalnızca ad (`"{b}"`), `tooltip.formatter` ad ve değer (`"{b}: {c}"`) — `{d}` yüzde **yok**; `heatmap` `group_by` etiketleri x, `series` etiketleri y, veri `[xIndex, yIndex, value]`, `visualMap` min/max kartın `items` değerlerinden (ECharts'a ölçek verir, yeni sayı olarak gösterilmez). `plot == "change_pct"` iken yalnızca `change_pct` taşıyan satırlar çizilir ve çizilen değer `change_pct`'dir (negatif olabilir); her noktanın etiketi sunucunun `trend` ve `change_pct`'sinden metin olarak kurulur (`"▲ 12,5%"`, `"▼ 3,0%"`, `"▬ 0,0%"`; ondalık ayracı yalnızca görünümdür, değer yeniden hesaplanmaz) ve rengi `trend`'e bağlıdır; satırı olmayan kova çizilmez. Etiketler ve seri adları `items`'tan, ilk geçiş sırasıyla.
  - `chartTitle(card: ChartCard): string` — "ölçü · grup[ × seri] · süzgeçler · tarih" görünüm metni; ad eşlemeleri yalnızca görünümdür, bilinmeyen kod olduğu gibi gösterilir.

- [ ] **Step 1: `chat.ts` tiplerini ve `isChart`'ı güncelle.**
- [ ] **Step 2: `chartOptions.ts`'yi yaz** (saf fonksiyonlar, tür başına bir üretici).
- [ ] **Step 3: `Chart.tsx`'i `chartOption`/`chartTitle` ile bağla:** başlık `chartTitle`, altında düz `items` tablosu (`series` varsa üç sütun; `change_pct`/`trend` varsa ek sütun), `groups_total > distinct grup sayısı`, `unclassified > 0` ve `series_truncated > 0` notları, `flights` notu; `items` boşsa grafik yerine "Süzgeçle eşleşen uçuş yok." notu (ECharts çağrılmaz).
- [ ] **Step 4: Doğrula**

Run (frontend/): `npm run build; npm run lint`
Expected: derleme geçer, yeni lint uyarısı yok (`Map.tsx` uyarısı önceden vardır).

- [ ] **Step 5: `chat.ts` ve `chartOptions.ts` mantığını node ile sına** (CLAUDE.md: scratchpad'e kopya, import'lara `.ts`; `chartOptions.ts` ECharts import etmediğinden doğrudan çalışır; `chat.ts`'ten yalnızca tip import edildiği için `chartOptions` kopyasındaki tip import'u `import type` ile yazılmalıdır). Sınanacaklar: gerçek bir `chart_card` (Python'dan `CardBuilder` ile üretilmiş JSON) `dispatch`'ten geçer; `chart_type: "donut"` atlanır; her dokuz tür için `chartOption` hatasız döner ve `JSON.stringify` edilebilir; `plot: "change_pct"` ile `bar_horizontal` yalnızca `change_pct` taşıyan satırları çizer, çizilen değerler `change_pct` değerleridir, etiketler `▲`/`▼`/`▬` ile başlar ve değerle aynı sayıyı içerir (Q2 kartından: 17:00 satırı çizilmez); `pie`'da `{d}` geçmez; `stacked_bar` serilerinin hepsi aynı `stack` değerini taşır, `grouped_bar`'da hiçbiri taşımaz; `heatmap` veri satırları `[x, y, value]` ve her değer `items`'taki bir değerdir; boş `items` ile `chartOption` çağrılmaz (`Chart.tsx` kolu).
- [ ] **Step 6: Commit**

```bash
git add frontend/src/chat.ts frontend/src/chartOptions.ts frontend/src/Chart.tsx
git commit -m "M8.3 - arayüzde tür başına grafik seçenekleri"
```

---

### Task 5: Belgeler ve son doğrulama

**Files:**
- Modify: `docs/tools.md` (`get_chart_data` bölümü baştan), `docs/chat.md` (`chart_card` satırı ve Arayüz kuralları 8), `CLAUDE.md` (`backend/tools/` satırına `get_chart_data`, `chart_fields.py`, `chart_query.py` ve `Chart.tsx`/`chartOptions.ts` bir cümleyle)

- [ ] **Step 1: Belgeleri spec B'yle tutarlı güncelle.** `docs/tools.md`: düz görünüm tablosu, argümanlar, `value`, hata eşlemesi, spec'teki örnek (`movement_type` iki dilim; havayolu dağılımı 300). `docs/chat.md`: `chart_card` verisinin yeni biçimi (`group_by`, `series_by?`, `measure`, `items` düz satırlar), kural 8 (dokuz tür, pasta yüzdesi yok, boş `items` notu).
- [ ] **Step 2: Doğrulama**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_chart.py tests\test_chart_fields.py tests\test_chart_query.py tests\test_tools.py tests\test_chat.py tests\test_citation.py -q`
Expected: testler PASS. **Tam `pytest` ve `ruff` çalıştırılmaz.** Raporda tam suite'in ve ruff'ın koşulmadığı açıkça yazılır.

- [ ] **Step 3: Commit**

```bash
git add docs CLAUDE.md
git commit -m "M8.3 - genel grafik sorgusu belgeleri"
```
