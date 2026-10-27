# Eval: golden set sözleşmesi

Bu belge, agent'ı (`docs/agent.md`) sabit 20 soruyla ölçen golden set'in sözleşmesidir. Amaç, sistem talimatı, tool tanımı ya da model değiştiğinde agent'ın doğru tool'u seçip seçmediğini, değeri tool sonucundan doğru aktarıp aktarmadığını ve eksik, eski, belirsiz veride sayı/durum uydurup uydurmadığını aynı ölçütle karşılaştırmaktır.

**Golden set dosyasında beklenen değer yazılmaz.** Sayı, saat, dakika, stand/gate kodu, `flight_id` gibi her beklenen değer, koşum anında ham veriden adı belli bir hesapla (bkz. Hesap adları) bulunur. Böylece aynı golden set her seed ve tarihte çalışır (`docs/spec.md` §9 son paragraf); dosyadaki sorular yalnızca §9 sabit kayıtlarına (`TC-LSD`, `TK2344`/`TK2345`, `THY2345`, `ZZ9999`) dayanır.

Sözleşme testleri koddan önce yazıldı ve gevşetilmez; kod `eval/` paketindedir (bkz. Dosyalar).

## Dosyalar

| Dosya | Durum | İçerik |
|---|---|---|
| `docs/eval.md` | bu belge | Sözleşme. |
| `eval/golden.json` | var | 20 soru, soru biçimi aşağıda. Elle düzenlenir; değişince `version` artar (bkz. Kurallar). |
| `eval/expected.py` | var | Hesap adlarının uygulaması. Giriş noktası `compute(ref, base, data, now) -> Value`; değer bulunamazsa `ExpectedError`. `backend/`'i import etmez. |
| `eval/criteria.py` | var | Ölçütler, metne çevirme ve eşleşme. `evaluate(question, expect, forbid, result)` koşum başına ölçütleri (`criteria`, `missing`, `found_forbidden`, `passed`), `summarize(runs)` özeti verir. `expect`/`forbid` çözülmüş `(ref, değer)` çiftleridir; hesap yapmaz. |
| `eval/golden.py` | var | `validate(golden) -> list[str]`: golden set'in bu sözleşmeye uyduğunu denetler; boş liste geçerli demektir. Hata metinleri soru `id`'siyle başlar. |
| `eval/run.py` | var | Koşucu, `python -m eval.run`; testler `main(argv, client=None) -> int`'i süreç içinde çağırır. Bkz. Koşucu. |
| `eval/out/` | — | Koşum sonuçları. Git'e girmez (`.gitignore`). |
| `tests/test_eval_golden.py` | var | `golden.json`'un bu sözleşmeye uyduğunu ve her kuralın bozulmuş kopyada yakalandığını denetler (API'siz). |
| `tests/test_eval_expected.py` | var | Hesap adlarını küçük, elle kurulmuş veriyle sınar (API'siz). |
| `tests/test_eval_criteria.py` | var | Ölçütleri ve özeti sahte koşu kayıtlarıyla sınar (API'siz). |
| `tests/test_eval_run.py` | var | Koşucuyu soruya göre senaryolu sahte istemciyle ve `--kuru` ile sınar; tool'lar referans veride gerçek çalışır (API'siz, ~40 sn). |

Veri dosyaları:

- **Temel veri (`base`)**: `synth.generator` çıktısı. Varsayılan `data/referans/seed42-2026-10-20.json`.
- **Eval verisi (`data`)**: agent'ın gördüğü dosya. Soruda `corruption` yoksa temel verinin kendisidir; varsa koşucunun temel veriden `synth.corruption` ile geçici klasörde ürettiği dosyadır (`docs/bozulma.md`). Bozuk veri her koşumda yeniden üretilir, repoya yazılmaz.

## Soru biçimi

`eval/golden.json` tek bir nesnedir:

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `version` | metin, `MAJOR.MINOR.PATCH` | evet | Golden set sürümü. Sonuç dosyasına yazılır; farklı sürümlerin sonuçları karşılaştırılmaz. |
| `now` | hesap referansı | evet | Sorunun `now`'u yoksa kullanılan `COPILOT_NOW`. Saat dilimli tam zaman damgası üreten bir hesap olmalıdır (`position.track_end`). |
| `questions` | liste | evet | Tam 20 soru, `id` sırasıyla. |

Soru nesnesi (`additionalProperties` yok; bilinmeyen alan golden set hatasıdır):

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `id` | metin, `G01`–`G20` | evet | Tekil. Sonuçlar bu adla eşlenir; bir sorunun anlamı değişirse yeni `id` alır. |
| `category` | metin | evet | `ozet`, `ucus`, `belirsizlik`, `bozulma`, `kapsam_disi`. Raporda gruplama içindir. |
| `behavior` | metin | evet | Beklenen davranışın etiketi: `cevap`, `hesap_yok`, `netlestirme`, `bulunamadi`, `eski_veri`, `veride_yok`, `veri_okunamadi`, `kapsam_disi`. Yalnızca rapordur; ölçütleri `tools`, `args`, `expect`, `forbid`, `asks` belirler. |
| `question` | metin | evet | Operatörün sorusu. `{ad}` yer tutucuları `slots` ile doldurulur; başka `{`/`}` olamaz. Doldurulmuş metin `run_agent`'a olduğu gibi gider. |
| `slots` | nesne, ad → hesap referansı | hayır | Sorudaki her `{ad}` için tek değer üreten bir hesap. Seed'e göre değişen bir kaydı (ör. iptal edilen bir uçuş) soruda kullanmanın tek yolu. Yer tutucu ile `slots` anahtarları birebir eşleşir. |
| `corruption` | nesne | hayır | `{"scenario", "flight_no", "field"?}`; `synth.corruption`'ın `--scenario`, `--flight-no`, `--field` argümanlarıyla aynı anlam ve kısıtlar. Yoksa eval verisi temel veridir. |
| `now` | hesap referansı | hayır | Bu soru için `COPILOT_NOW`. Yoksa üst düzeydeki `now`. |
| `tools` | metin listesi | evet | Çalışan (`executed: true`) tool adlarının **tam kümesi**. Boş liste: hiçbir tool çalışmamalı. Sıra ve tekrar sayısı önemsizdir. Yalnızca `docs/tools.md`'deki üç tool adı geçerlidir. |
| `args` | liste | hayır | `{"name", "input"}`; her öğe için aynı ad ve kanonik JSON'da aynı `input`'la çalışmış en az bir çağrı olmalı. Yalnızca modelin tek doğru argümanı olduğu durumda yazılır (enum). |
| `expect` | değer referansı listesi | hayır | Cevap metninde **bulunması** gereken değerler. |
| `forbid` | değer referansı listesi | hayır | Cevap metninde **bulunmaması** gereken değerler (uydurma, kendi hesabı, belirsizlikte kendi seçimi). |
| `asks` | mantıksal | hayır | `true` ise cevap netleştirme sorusu içermelidir. |

Her soruda en az bir olumlu denetim bulunur: `tools` boş değilse ya da `expect` doluysa ya da `asks: true`. `tools: []` olan sorular (`kapsam_disi`) bu kuralın istisnasıdır; ölçütleri `durum` ve `tool`'dur.

**Değer referansı** iki biçimden biridir:

| Biçim | Anlam |
|---|---|
| `{"calc": "<hesap adı>", "params": {...}, "on": "eval"\|"base"}` | Hesabın sonucu. `on` verilmezse `eval`: agent'ın gördüğü veriden hesaplanır. `base`: bozulmadan önceki veriden hesaplanır; bozulmada kaybolan değerin cevapta **görünmemesini** denetlemek için kullanılır (ör. silinen `estimated_time`). |
| `{"literal": "<metin>"}` | Sabit metin. Yalnızca iki durumda: sorudaki bir kimliğin cevapta tekrarlanması (`ZZ9999`) ya da rakam içermeyen bir anahtar sözcük (`iptal`). Rakam içeren literal, doldurulmamış soru metninde aynen geçmelidir. |

**Hesap referansı** (`now`, `slots`) yalnızca `calc` biçimindedir.

## Hesap adları

Her hesap `(temel veri, eval verisi, now, params)`'tan saf bir fonksiyondur; sistem saatini okumaz, rastgelelik kullanmaz. Tanımlar `docs/tools.md`'deki tool hesaplarıyla **aynı anlamdadır** ama `backend/tools/`'tan bağımsız yazılır (bkz. Kurallar).

| Ad | `params` | Sonuç | Tanım |
|---|---|---|---|
| `summary.total` | `direction`: `all`/`arrival`/`departure` | tamsayı | `flights`'ta kaydı olan ve `movements`'ta yönü eşleşen uçuş sayısı; iptaller dahil, yetim kayıtlar hariç (`docs/tools.md` › `get_flight_summary`). |
| `summary.cancelled` | `direction` | tamsayı | Aynı kümede `cancelled: true` olanların sayısı. |
| `summary.delayed` | `direction` | tamsayı | Aynı kümede `delays`'te kaydı olanların sayısı (`flight_id` başına bir). |
| `summary.not_cancelled` | `direction` | tamsayı | `summary.total − summary.cancelled`. Hiçbir tool bu değeri döndürmez; yalnızca `forbid`'de, modelin kendi aritmetiğini yakalamak için kullanılır. |
| `flight.field` | `flight_no`, `field` | alanın değeri | `flight_no`'su tam eşit olan tek `flights` kaydının alanı. `field`: `scheduled_time`, `estimated_time`, `registration`, `callsign`, `aircraft_type`, `origin`, `destination` (`flights`); `stand_code`, `gate_code`, `actual_block_time`, `actual_runway_time` (`movements`); `delay_minutes`, `delay_code`, `delay_category` (`delays`, kaynak alan `category`). |
| `identity.candidates` | `query`, `field` | liste | `docs/tools.md` › `resolve_flight_identity` › Eşleşme kuralı ile `query`'ye uyan tüm uçuşlar, `flight_id` sırasıyla; her biri için `field` (`flight.field`'daki alanlar ya da `flight_no`). En az 2 eşleşme beklenir; 2'den azsa golden set hatası. |
| `position.last` | `flight_no`, `field`: `ts`/`lat`/`lon`/`phase` | alanın değeri | Uçuşun `positions` kayıtlarından `ts ≤ now` olanların `ts`'si en büyüğü (`docs/tools.md` › `get_flight_details` › `position`). |
| `position.track_end` | `flight_no` | zaman damgası | Uçuşun `positions` izindeki en büyük `ts`, `now`'dan bağımsız. Yalnızca `now` için; ISO 8601 `+03:00` olarak kalır, metinde aranmaz. |
| `flights.pick` | `cancelled`: mantıksal | `flight_no` | `cancelled` değeri verilen, `flight_no`'su günde tekil uçuşlardan `flight_id` sırasına göre ilki. Yalnızca `slots` için. |
| `stands.codes` | yok | liste | `stands`'teki tüm `stand_code`'lar. Yalnızca `forbid`'de, stand'ı olmaması gereken bir cevapta herhangi bir stand kodunun geçmediğini denetlemek için. |

**Boş sonuç golden set hatasıdır.** Hesap bir değer bulamazsa (uçuş yok, alan yok, liste beklenenden kısa) koşucu soruyu `hesap_hatasi` sayar ve ölçütleri çalıştırmaz. Böylece `forbid` boş bir değerle sessizce geçmez. Bozulmada kaybolan değer bu yüzden `on: "base"` ile hesaplanır.

**Metne çevirme.** Değer cevap metninde aranmadan önce şöyle yazılır:

| Değer | Yazım | Örnek |
|---|---|---|
| tamsayı | ondalık, binlik ayırıcısız | `25` |
| zaman damgası | `+03:00` yerel saat, `HH:MM` (sistem talimatındaki biçim) | `16:05` |
| ondalıklı sayı | kaynaktaki yazım; ondalık ayırıcı olarak `.` ya da `,` kabul edilir | `41.05` / `41,05` |
| metin (kod) | olduğu gibi | `R236`, `BUS4` |
| liste | her öğe ayrı değer: `expect`'te hepsi bulunmalı, `forbid`'de hiçbiri bulunmamalı | |

**Eşleşme.** Bir değer, cevap metninde önünde ve arkasında harf ya da rakam olmayan bir yerde geçiyorsa bulunmuş sayılır (`4`, `TK2345` içinde bulunmaz; `A1`, `A12` içinde bulunmaz). Kodlar, sayılar ve rakam içeren `literal` büyük/küçük harfe duyarlıdır. Rakam içermeyen `literal` (anahtar sözcük) iki istisnayla aranır: metin ve sözcük Türkçe küçük harfe çevrilerek karşılaştırılır (`İ` → `i`, `I` → `ı`, sonra küçük harf), ve yalnızca **önündeki** sınır aranır; Türkçe ekli yazımlar da bulunur (`iptal`, `iptaldir` ve `iptali` içinde bulunur, `kriptal` içinde bulunmaz). Zaman damgası, `T` içeren ve saat dilimi taşıyan ISO 8601 metin olarak tanınır; diğer metinler koddur. Bir ondalıklı sayı ya da zaman yalnızca yukarıdaki yazımla aranır (`16:05` bulunur, `1605` ya da ham damga bulunmaz).

## Ölçütler

Her koşumda (soru × tekrar) aşağıdaki ölçütler ayrı ayrı `geçti`/`kaldı` olur. Uygulanmayan ölçüt (ör. `args` yok) `uygulanmaz` yazılır ve hesaba girmez.

| Ölçüt | Ne zaman uygulanır | Geçme koşulu |
|---|---|---|
| `durum` | her soruda | `AgentResult.status == "tamam"`. |
| `tool` | her soruda | `executed: true` çağrıların ad kümesi `tools` ile tam eşit. |
| `arguman` | `args` doluysa | Her öğe için ad ve kanonik JSON `input`'u eşit, çalışmış bir çağrı var. |
| `deger` | `expect` doluysa | Her değer `text`'te bulunuyor. |
| `uydurmama` | `forbid` doluysa | Hiçbir değer `text`'te bulunmuyor. |
| `netlestirme` | `asks: true` ise | `text` `?` içeriyor. |

- `status` `tamam` değilse yalnızca `durum` ve `tool` değerlendirilir; metin ölçütleri `kaldı` sayılır (`docs/agent.md` › Sonuç: `text` nihai cevap değildir). `missing` ve `found_forbidden` tanı için yine metinden doldurulur.
- `tool` ve `arguman` yalnızca `executed: true` çağrılara bakar; çalıştırılmamış istek sayılmaz.
- Özette `uygulanmaz` ölçütler ve hata koşumlarının ölçütleri orana girmez; hata koşumu golden skorda kalmış sayılır. Payda `0` ise oran `null`'dur.
- **Soru geçer** ⇔ uygulanan ölçütlerin hepsi geçti. `hesap_hatasi` ve `api_hatasi` geçmez.
- **Golden skor**: geçen koşum sayısı / toplam koşum sayısı. Ayrıca ölçüt başına geçme oranı ve `category` başına skor raporlanır.
- `--tekrar N` ile bir soru, N koşumun hepsinde geçtiyse **kararlı** sayılır; rapor kararlı soru sayısını ayrıca verir.
- Ölçütler belirlenimcidir; LLM ile puanlama (judge) yoktur. Bilinen sınırlar: `kapsam_disi` sorularında cevabın içeriği değil yalnızca tool kullanılmadığı denetlenir; `uydurmama` bir sayının cevapta başka bir anlamla geçtiği durumda yanlış alarm verebilir (koşum çıktısında metin bulunduğu için elle doğrulanır).

## Koşucu

```
python -m eval.run --out eval\out\sonuc.json [--soru G01,G13] [--tekrar 1] [--instruction v1] [--data dosya.json | --seed 42 --date 2026-10-20]
python -m eval.run --kuru [--soru ...] [--data ... | --seed ... --date ...]
```

| Argüman | Zorunlu | Açıklama |
|---|---|---|
| `--out` | `--kuru` yoksa evet | Sonuç dosyası. Varsa üzerine yazmaz: `Hata:` ve 1. Klasörü yoksa oluşturulur. |
| `--soru` | hayır | Virgülle ayrılmış `id`'ler; verilmezse 20 soru. Bilinmeyen `id` hata. |
| `--tekrar` | hayır | Soru başına koşum sayısı, varsayılan 1, en az 1. |
| `--instruction` | hayır | `run_agent`'a `instruction_version` olarak gider; verilmezse `COPILOT_INSTRUCTION`, boşsa `v3`. Geçersizse `Hata:` ve 1. |
| `--data` | hayır | Temel veri dosyası. Varsayılan `data/referans/seed42-2026-10-20.json`. |
| `--seed`, `--date` | hayır, birlikte | Temel veriyi `synth.generator` ile geçici klasörde üretir. `--data` ile birlikte verilemez. |
| `--kuru` | hayır | Model çağrılmaz, `backend.llm` yüklenmez. stdout'a soru başına bir JSON satırı yazar, başka bir şey yazmaz: `{"id", "question" (doldurulmuş), "corruption", "now", "expect", "forbid", "error"}`. `expect`/`forbid` metne çevrilmiş değerlerdir (listeler açılır, her değerin ilk yazımı); `error` `hesap_hatasi` ya da `null`. Hesap hatası varsa 1 ile çıkar. Golden set ya da hesap değişince ilk bu çalıştırılır. |
| `--golden` | hayır | Golden set dosyası, varsayılan `eval/golden.json`. Yardım metninde görünmez; testler geçersiz golden set'i bununla verir. |

Akış:

1. `golden.json` okunur ve bu sözleşmeye göre doğrulanır (`eval/golden.py`); hata varsa hiçbir koşum başlamaz. Ardından `--soru` id'leri denetlenir.
2. Gerçek koşumda `--out` var mı diye bakılır, `backend.llm` yüklenir ve talimat sürümü doğrulanır. Ayar hatası (`.env` eksik) ya da bilinmeyen sürüm `Hata:` ve 1 verir; hiçbir model çağrısı yapılmaz.
3. Temel veri hazırlanır; `corruption` içeren her farklı `(scenario, flight_no, field)` bir kez `synth.corruption` ile geçici klasörde üretilir. Bozulma komutu başarısızsa ilgili sorular `hesap_hatasi` olur. Geçici klasör koşu bitince silinir.
4. Her soru için `now`, `slots`, `expect`, `forbid` hesaplanır. `hesap_hatasi` olan soru için model çağrılmaz.
5. Gerçek koşumda, başlamadan önce stderr'e ücretli agent koşusu sayısı (hesap hatasız soru × tekrar) yazılır.
6. Her koşum için `COPILOT_DATA` eval verisine, `COPILOT_NOW` sorunun `now`'una ayarlanır, `run_agent(soru, instruction_version=...)` çağrılır, ortam eski haline döner. Koşumlar birbirinden bağımsızdır; sıra sonucu etkilemez.
7. API hatası (`anthropic.APIError`) koşumu `api_hatasi` yapar, kalan koşumlar sürer. Sonuca yalnızca exception sınıf adı (`exception`) yazılır; mesaj, yanıt ve request id yazılmaz. Diğer exception'lar kod hatasıdır, yakalanmaz.
8. Sonuç dosyası tüm koşumlar bitince bir kez yazılır; özet (golden skor, ölçüt ve kategori oranları, kararlı soru sayısı, dosya yolu) stdout'a basılır.

Çıkış kodu: tüm koşumlar geçtiyse 0; geçmeyen koşum, golden set ya da hesap hatası varsa 1; argparse kullanım hatası 2.

Sonuç dosyası (UTF-8, `ensure_ascii=False`):

| Alan | İçerik |
|---|---|
| `golden_version` | `golden.json` › `version` |
| `instruction` | `AgentResult.instruction` (`name`, `version`, `summary`) |
| `model` | `backend.llm.MODEL` |
| `base` | `{"path", "meta"}`: temel verinin yolu (verildiği gibi) ve `meta`'sı (`seed`, `date`, `generator_version`) |
| `runs` | Her koşum: `id`, `repeat` (1'den), `category`, `behavior`, `question` (doldurulmuş), `now`, `corruption`, `status`, `executed_tools` (ad ve `input`), `criteria` (ölçüt → `geçti`/`kaldı`/`uygulanmaz`), `missing` (bulunamayan `expect` değerleri), `found_forbidden` (bulunan `forbid` değerleri), `text`, `passed`, `error` (`hesap_hatasi`/`api_hatasi`/`null`), `exception` (`api_hatasi`'nda exception sınıf adı, diğerlerinde `null`). Hata koşumunda `status` `null`, `criteria` `{}`, `text` boştur. |
| `summary` | Golden skor, ölçüt başına oran, `category` başına skor, kararlı soru sayısı |

Zarflar (`turns[].tool_calls[].envelope`) sonuca girmez; gerekirse aynı soru `scripts/agent_run.py` ile ayrıca incelenir.

## Kurallar

- **Golden set'te beklenen değer yok.** `golden.json` hiçbir JSON sayısı içermez. Rakam yalnızca `version`, `id`, `question`, `params` içindeki `flight_no`/`query` ve soruda geçen `literal` değerlerinde bulunabilir. `tests/test_eval_golden.py` bunu dosyanın tamamını gezerek denetler.
- **Hesap tool'dan bağımsızdır.** `eval/expected.py` `backend/tools/` ve `backend/envelope.py`'yi import etmez; ham JSON'u kendisi okur. Aynı kodla hesaplanan beklenen değer tool hatasını gizler. Hesap ile tool aynı veride farklı sonuç verirse ikisinden biri `docs/tools.md`'ye uymuyordur; golden set gevşetilmez.
- **Sorular yalnızca sabit kayıtlara ya da `slots`'a dayanır.** Seed'e göre değişen bir sefer no, stand ya da gate soru metnine yazılmaz.
- **Gerçek koşum yalnızca açıkça istenince yapılır.** Her koşum ücretlidir (en az 20 agent döngüsü). Testler, hook'lar ve `--kuru` model çağırmaz; koşucu döngüde ya da gereksiz yere yeniden çalıştırılmaz (CLAUDE.md › Yasaklar).
- **Golden set değişince sürüm artar.** Soru eklemek, çıkarmak ya da bir sorunun `expect`/`forbid`/`tools`'unu değiştirmek `version`'ı artırır ve aşağıdaki Değişiklik günlüğüne işlenir. Talimat ya da tool değişikliğinin etkisi yalnızca aynı `golden_version` ve aynı temel veriyle alınmış iki sonuç arasında karşılaştırılır.
- **Golden set başarısızlığa göre düzeltilmez.** Bir soru kaldığında önce sonucun `text`'i ve `executed_tools`'u incelenir; soru yalnızca beklenti bu belgeye ya da `docs/tools.md` › Kenar durumlar'a aykırıysa değişir.
- `experiments/function_calling/sorular.json` ayrı bir ölçümdür ve değiştirilmez; golden set onun yerine geçmez.
- Bulgular `docs/sorumluluk-zinciri.md` tablosuna işlenir.

## Değişiklik günlüğü

| Sürüm | Değişiklik |
|---|---|
| `1.0.0` | İlk 20 soru: özet (5), uçuş (5), belirsizlik (2), bozulma (6), kapsam dışı (2). |
