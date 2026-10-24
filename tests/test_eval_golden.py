"""Golden set dosyası sözleşme testleri (docs/eval.md › Soru biçimi, Kurallar).

Testler koddan önce yazıldı; eval.golden yokken kırmızıdır. Gerçek eval/golden.json'un
geçerli olduğu, her kuralın da dosyanın bozulmuş bir kopyasıyla yakalandığı denetlenir.
"""

import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "eval" / "golden.json"


@pytest.fixture
def golden_module():
    return importlib.import_module("eval.golden")


@pytest.fixture
def golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def by_id(golden, id_):
    return next(q for q in golden["questions"] if q["id"] == id_)


def errors_after(golden_module, golden, mutate):
    broken = copy.deepcopy(golden)
    mutate(broken)
    return golden_module.validate(broken)


def test_modul_var():
    assert importlib.util.find_spec("eval") is not None
    assert importlib.util.find_spec("eval.golden") is not None


def test_gercek_golden_set_gecerli(golden_module, golden):
    assert golden_module.validate(golden) == []


def test_gercek_golden_set_20_soru_ve_kategoriler(golden):
    questions = golden["questions"]
    assert [q["id"] for q in questions] == [f"G{n:02d}" for n in range(1, 21)]
    categories = [q["category"] for q in questions]
    assert {c: categories.count(c) for c in set(categories)} == {
        "ozet": 5,
        "ucus": 5,
        "belirsizlik": 2,
        "bozulma": 6,
        "kapsam_disi": 2,
    }


def test_dogrulama_golden_seti_degistirmez(golden_module, golden):
    before = copy.deepcopy(golden)
    golden_module.validate(golden)
    assert golden == before


def set_(path, value):
    """golden içinde yol boyunca ilerleyip son anahtarı value yapan mutasyon."""

    def mutate(g):
        node = g
        for key in path[:-1]:
            node = (
                by_id(g, key) if isinstance(key, str) and key[:1] == "G" else node[key]
            )
        node[path[-1]] = value

    return mutate


def drop(path):
    def mutate(g):
        node = g
        for key in path[:-1]:
            node = (
                by_id(g, key) if isinstance(key, str) and key[:1] == "G" else node[key]
            )
        del node[path[-1]]

    return mutate


def append_question(g):
    extra = copy.deepcopy(g["questions"][0])
    extra["id"] = "G21"
    g["questions"].append(extra)


def swap_first_two(g):
    g["questions"][0], g["questions"][1] = g["questions"][1], g["questions"][0]


def duplicate_id(g):
    g["questions"][1]["id"] = "G01"


BROKEN = [
    # Üst düzey
    pytest.param(set_(["version"], "1.0"), "version", id="surum_bicimi"),
    pytest.param(drop(["now"]), "now", id="ust_now_yok"),
    pytest.param(set_(["now"], {"literal": "16:22"}), "now", id="ust_now_literal"),
    pytest.param(set_(["extra"], True), "extra", id="ust_bilinmeyen_alan"),
    pytest.param(lambda g: g["questions"].pop(), "20", id="soru_eksik"),
    pytest.param(append_question, "20", id="soru_fazla"),
    pytest.param(swap_first_two, "sıra", id="id_sirasi"),
    pytest.param(duplicate_id, "G01", id="id_tekrar"),
    # Soru alanları
    pytest.param(set_(["G01", "note"], "x"), "note", id="bilinmeyen_alan"),
    pytest.param(drop(["G01", "tools"]), "tools", id="zorunlu_alan_yok"),
    pytest.param(set_(["G01", "category"], "genel"), "category", id="kategori"),
    pytest.param(set_(["G01", "behavior"], "iyi"), "behavior", id="davranis"),
    pytest.param(set_(["G01", "asks"], "evet"), "asks", id="asks_mantiksal"),
    pytest.param(set_(["G01", "tools"], ["get_weather"]), "get_weather", id="tool"),
    pytest.param(
        set_(["G01", "args"], [{"name": "get_flight_details", "input": {}}]),
        "args",
        id="args_tools_disinda",
    ),
    # Yer tutucular
    pytest.param(
        set_(["G01", "question"], "{ucus} kaç?"), "ucus", id="yer_tutucu_slotsuz"
    ),
    pytest.param(drop(["G12", "question"]), "question", id="soru_metni_yok"),
    pytest.param(
        set_(["G12", "question"], "Hangi stand'da?"), "ucus", id="slot_yer_tutucusuz"
    ),
    pytest.param(
        set_(["G12", "question"], "{ucus} hangi stand'da}?"), "{", id="fazla_parantez"
    ),
    pytest.param(
        set_(["G12", "slots", "ucus"], {"literal": "TK1"}), "slots", id="slot_literal"
    ),
    # Bozulma
    pytest.param(
        set_(["G13", "corruption", "scenario"], "late"), "scenario", id="senaryo"
    ),
    pytest.param(
        set_(["G13", "corruption", "field"], "flights.callsign"),
        "field",
        id="field_yalniz_missing_field",
    ),
    pytest.param(drop(["G13", "corruption", "flight_no"]), "flight_no", id="hedef"),
    # Değer referansları
    pytest.param(
        set_(["G01", "expect"], [{"calc": "summary.average", "params": {}}]),
        "summary.average",
        id="bilinmeyen_hesap",
    ),
    pytest.param(set_(["G01", "expect", 0, "on"], "ham"), "on", id="on_degeri"),
    pytest.param(
        set_(["G01", "expect", 0, "extra"], True), "extra", id="ref_bilinmeyen_alan"
    ),
    pytest.param(
        set_(["G01", "expect"], [{"literal": "ZZ9999"}]),
        "ZZ9999",
        id="rakamli_literal_soruda_yok",
    ),
    pytest.param(
        set_(["G10", "expect"], [{"literal": 9999}]), "literal", id="literal_metin"
    ),
    # Beklenen değer yazılmaz
    pytest.param(
        set_(["G01", "expect", 0, "params", "direction"], 600),
        "sayı",
        id="json_sayisi",
    ),
    pytest.param(
        set_(["G06", "expect", 0, "params", "field"], "stand_code_2"),
        "rakam",
        id="izinsiz_alanda_rakam",
    ),
    pytest.param(set_(["G01", "behavior"], "cevap1"), "rakam", id="behavior_rakam"),
]


@pytest.mark.parametrize(("mutate", "needle"), BROKEN)
def test_kural_ihlali_yakalanir(golden_module, golden, mutate, needle):
    errors = errors_after(golden_module, golden, mutate)
    assert errors, "hata bekleniyordu"
    assert all(isinstance(e, str) and e for e in errors)
    assert any(needle in e for e in errors), errors


def test_izinli_alanlarda_rakam_serbest(golden_module, golden):
    # version, id, question, params.flight_no/query ve soruda geçen literal.
    errors = errors_after(
        golden_module,
        golden,
        set_(["G10", "question"], "ZZ9999 seferi 2. kez nerede?"),
    )
    assert errors == []


def test_hata_mesaji_soru_idsini_tasir(golden_module, golden):
    errors = errors_after(golden_module, golden, set_(["G07", "note"], "x"))
    assert errors
    assert all(e.startswith("G07") for e in errors)


def test_nesne_olmayan_girdi_hatadir(golden_module):
    assert golden_module.validate([]) != []
    assert golden_module.validate({"questions": "x"}) != []
