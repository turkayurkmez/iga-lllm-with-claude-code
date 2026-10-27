"""Uçuş tool'ları sözleşme testleri (docs/tools.md, backend/tools/contracts/).

Testler koddan önce yazıldı; backend.tools yokken kırmızıdır. Yalnızca iki giriş
noktası kullanılır: run_tool ve tool_definitions. Tool'ların iç fonksiyonlarına ve
zarf katmanına bakılmaz. COPILOT_DATA ve COPILOT_NOW her testte ayarlanır; bozuk
veri dosyaları geçici klasörde synth.corruption ile üretilir.

Beklenen değerler data/referans/seed42-2026-10-20.json'dan bir kez hesaplanıp sabit
yazılmıştır; dosya elle düzeltilmez (CLAUDE.md).
"""

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = REPO_ROOT / "backend" / "tools" / "contracts"
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
VERSION = "1.0.0"
TOOL_NAMES = [
    "get_flight_summary",
    "resolve_flight_identity",
    "get_flight_details",
    "focus_map_object",
    "highlight_map_set",
]

NOT_FOUND = {"code": "NOT_FOUND", "message": "Bu kimlikle uçuş bulunamadı."}
AMBIGUOUS = {
    "code": "AMBIGUOUS_ENTITY",
    "message": "Bu kimlik birden fazla uçuşla eşleşiyor.",
}
NOT_IN_SCOPE = {
    "code": "CAPABILITY_NOT_IN_SCOPE",
    "message": "Bu istek copilot'un kapsamı dışında.",
}
ARGS_INVALID = {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Tool argümanları şemaya uymuyor.",
}
DATA_INVALID = {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Tool çıktısı şemaya uymuyor; yanıt üretilemedi.",
}

TK2345_ID = "FL-20261020-0270"
TK2344_ID = "FL-20261020-0269"
CANCELLED_ID = "FL-20261020-0143"
# duplicate_callsign senaryosunda callsign'ı THY2345 olan ikinci uçuş (TK2533).
DUPLICATE_ID = "FL-20261020-0002"

TK2345_CANDIDATE = {
    "flight_id": TK2345_ID,
    "flight_no": "TK2345",
    "callsign": "THY2345",
    "registration": "TC-LSD",
    "movement_type": "DEPARTURE",
    "scheduled_time": "2026-10-20T15:40:00+03:00",
}
TK2344_CANDIDATE = {
    "flight_id": TK2344_ID,
    "flight_no": "TK2344",
    "callsign": "THY2344",
    "registration": "TC-LSD",
    "movement_type": "ARRIVAL",
    "scheduled_time": "2026-10-20T13:05:00+03:00",
}
TK2345_DETAILS = {
    "flight_id": TK2345_ID,
    "flight_no": "TK2345",
    "callsign": "THY2345",
    "registration": "TC-LSD",
    "aircraft_type": "A321",
    "origin": "XXXX",
    "destination": "VAN",
    "scheduled_time": "2026-10-20T15:40:00+03:00",
    "estimated_time": "2026-10-20T16:05:00+03:00",
    "cancelled": False,
    "movement_type": "DEPARTURE",
    "stand_code": "R236",
    "gate_code": "BUS4",
    "actual_runway_time": "2026-10-20T16:09:00+03:00",
    "actual_block_time": "2026-10-20T16:02:00+03:00",
    "delay_minutes": 25,
    "delay_code": "82",
    "delay_category": "ATC_RESTRICTION",
    "position": {
        "ts": "2026-10-20T16:22:00+03:00",
        "lat": 41.05,
        "lon": 28.4,
        "heading_deg": 235.0,
        "speed_kt": 280.0,
        "phase": "CLIMB",
    },
}
TK2345_POSITION_1610 = {
    "ts": "2026-10-20T16:10:00+03:00",
    "lat": 41.227231,
    "lon": 28.736923,
    "heading_deg": 235.0,
    "speed_kt": 169.2,
    "phase": "CLIMB",
}
# stale_position senaryosunda kalan son nokta (docs/zarf.md › Örnek 2).
TK2345_POSITION_1612 = {
    "ts": "2026-10-20T16:12:00+03:00",
    "lat": 41.197692,
    "lon": 28.680769,
    "heading_deg": 235.0,
    "speed_kt": 187.7,
    "phase": "CLIMB",
}
TK2344_DETAILS = {
    "flight_id": TK2344_ID,
    "flight_no": "TK2344",
    "callsign": "THY2344",
    "registration": "TC-LSD",
    "aircraft_type": "A321",
    "origin": "VAN",
    "destination": "XXXX",
    "scheduled_time": "2026-10-20T13:05:00+03:00",
    "estimated_time": "2026-10-20T13:05:00+03:00",
    "cancelled": False,
    "movement_type": "ARRIVAL",
    "stand_code": "R236",
    "gate_code": "BUS4",
    "actual_runway_time": "2026-10-20T13:00:00+03:00",
    "actual_block_time": "2026-10-20T13:08:00+03:00",
    "position": {
        "ts": "2026-10-20T13:08:00+03:00",
        "lat": 41.251,
        "lon": 28.7541,
        "heading_deg": 131.5,
        "speed_kt": 0,
        "phase": "AT_STAND",
    },
}
CANCELLED_DETAILS = {
    "flight_id": CANCELLED_ID,
    "flight_no": "TK5086",
    "callsign": "THY5086",
    "registration": "TC-TIX",
    "aircraft_type": "A333",
    "origin": "CDG",
    "destination": "XXXX",
    "scheduled_time": "2026-10-20T07:55:00+03:00",
    "estimated_time": "2026-10-20T07:55:00+03:00",
    "cancelled": True,
    "movement_type": "ARRIVAL",
}
SUMMARIES = {
    "all": {"total": 600, "cancelled": 4, "delayed": 115},
    "arrival": {"total": 300, "cancelled": 2, "delayed": 44},
    "departure": {"total": 300, "cancelled": 2, "delayed": 71},
}


def load_tools():
    assert importlib.util.find_spec("backend.tools") is not None, "backend.tools yok"
    module = importlib.import_module("backend.tools")
    for name in ("run_tool", "tool_definitions"):
        assert callable(getattr(module, name, None)), f"backend.tools.{name} yok"
    return module


def load_contract(name: str) -> dict:
    return json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    # source, COPILOT_DATA'nın değeri olduğu gibi döner; göreli yol için kök sabitlenir.
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)


@pytest.fixture(scope="module")
def corrupted(tmp_path_factory) -> dict[str, str]:
    """Senaryo adı → synth.corruption ile geçici klasörde üretilmiş dosya yolu."""
    folder = tmp_path_factory.mktemp("bozuk")
    runs = {
        "stale_position": ["--scenario", "stale_position"],
        "duplicate_callsign": ["--scenario", "duplicate_callsign"],
        "undefined_flight": ["--scenario", "undefined_flight"],
        "missing_cancelled": [
            "--scenario",
            "missing_field",
            "--field",
            "flights.cancelled",
        ],
        "missing_callsign": [
            "--scenario",
            "missing_field",
            "--field",
            "flights.callsign",
        ],
        "missing_estimated": [
            "--scenario",
            "missing_field",
            "--field",
            "flights.estimated_time",
        ],
        "missing_movement_type": [
            "--scenario",
            "missing_field",
            "--field",
            "movements.movement_type",
        ],
        "missing_stand": [
            "--scenario",
            "missing_field",
            "--field",
            "movements.stand_code",
        ],
    }
    paths = {}
    for key, args in runs.items():
        out = folder / f"{key}.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "synth.corruption",
                "--in",
                str(REPO_ROOT / REFERENCE),
                *args,
                "--out",
                str(out),
            ],
            check=False,
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"Bozulma üretilemedi ({key}):\n{result.stderr}"
        paths[key] = str(out)
    return paths


def call(name, args) -> dict:
    """run_tool'u çağırır; zarfın JSON'a yazılabildiğini ve 8 alanı taşıdığını denetler."""
    envelope = load_tools().run_tool(name, args)
    assert json.loads(json.dumps(envelope, ensure_ascii=False)) == envelope
    assert set(envelope) == {
        "value",
        "source",
        "as_of",
        "filters",
        "stale",
        "tool_version",
        "error",
        "author",
    }
    if name in TOOL_NAMES and envelope["author"] == "tool":
        schema = load_contract(name)["value_schema"]
        Draft202012Validator(schema).validate(envelope["value"])
    return envelope


def tool_envelope(value, filters, error=None, source=REFERENCE, as_of=NOW) -> dict:
    return {
        "value": value,
        "source": source,
        "as_of": as_of,
        "filters": filters,
        "stale": False,
        "tool_version": VERSION,
        "error": error,
        "author": "tool",
    }


def layer_envelope(error, filters=None, tool_version=VERSION) -> dict:
    return {
        "value": None,
        "source": None,
        "as_of": None,
        "filters": filters if filters is not None else {},
        "stale": False,
        "tool_version": tool_version,
        "error": error,
        "author": "layer",
    }


# --- tool_definitions -------------------------------------------------------------


def test_tool_definitions_kontratlarla_birebir_aynidir():
    expected = [
        {
            key: load_contract(name)[key]
            for key in ("name", "description", "input_schema")
        }
        # search_documents COPILOT_DATA okumaz; sözleşmesi tests/test_search_documents.py'de.
        for name in [*TOOL_NAMES, "search_documents"]
    ]
    assert load_tools().tool_definitions() == expected


def test_kontratlarin_surumu_ve_semalari_gecerlidir():
    for name in TOOL_NAMES:
        contract = load_contract(name)
        assert contract["name"] == name
        assert contract["version"] == VERSION
        Draft202012Validator.check_schema(contract["input_schema"])
        Draft202012Validator.check_schema(contract["value_schema"])
    load_tools()


# --- Ortak kurallar -----------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["get_flight_position", "", "GET_FLIGHT_SUMMARY", None]
)
def test_bilinmeyen_tool_kapsam_disi_doner(name):
    assert call(name, {"direction": "all"}) == layer_envelope(
        NOT_IN_SCOPE, tool_version=None
    )


@pytest.mark.parametrize("name", TOOL_NAMES)
@pytest.mark.parametrize("args", [None, [], "all", 1])
def test_nesne_olmayan_argumanlar_sema_hatasi_verir(name, args):
    assert call(name, args) == layer_envelope(ARGS_INVALID)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_bilinmeyen_tool_ve_sema_hatasi_veriyi_okumaz(name, monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))
    assert call("get_flight_position", {}) == layer_envelope(
        NOT_IN_SCOPE, tool_version=None
    )
    assert call(name, {}) == layer_envelope(ARGS_INVALID)


VALID_ARGS = {
    "get_flight_summary": {"direction": "all"},
    "resolve_flight_identity": {"query": "TK2345"},
    "get_flight_details": {"flight_id": TK2345_ID},
    "focus_map_object": {"object_type": "stand", "id": "C101"},
    "highlight_map_set": {"object_type": "stand", "ids": ["C101", "C102"]},
}


def write_without(tmp_path: Path, key: str) -> str:
    data = json.loads((REPO_ROOT / REFERENCE).read_text(encoding="utf-8"))
    del data[key]
    path = tmp_path / f"{key}_yok.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_copilot_data_tanimsizsa_veri_hatasi_doner(name, monkeypatch):
    monkeypatch.delenv("COPILOT_DATA")
    args = VALID_ARGS[name]
    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_copilot_data_bossa_veri_hatasi_doner(name, monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", "")
    args = VALID_ARGS[name]
    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


@pytest.mark.parametrize("name", TOOL_NAMES)
def test_dosya_yoksa_veri_hatasi_doner(name, monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))
    args = VALID_ARGS[name]
    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


@pytest.mark.parametrize("name", TOOL_NAMES)
@pytest.mark.parametrize("content", [b"{bozuk", b"", b"\xff\xfe{}"])
def test_gecersiz_json_veri_hatasi_doner(name, content, monkeypatch, tmp_path):
    path = tmp_path / "bozuk.json"
    path.write_bytes(content)
    monkeypatch.setenv("COPILOT_DATA", str(path))
    args = VALID_ARGS[name]
    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("get_flight_summary", "meta"),
        ("get_flight_summary", "flights"),
        ("get_flight_summary", "movements"),
        ("get_flight_summary", "delays"),
        ("resolve_flight_identity", "flights"),
        ("resolve_flight_identity", "movements"),
        ("get_flight_details", "flights"),
        ("get_flight_details", "movements"),
        ("get_flight_details", "delays"),
        ("get_flight_details", "positions"),
        ("focus_map_object", "stands"),
        ("highlight_map_set", "stands"),
    ],
)
def test_kullanilan_ust_anahtar_yoksa_veri_hatasi_doner(
    name, key, monkeypatch, tmp_path
):
    monkeypatch.setenv("COPILOT_DATA", write_without(tmp_path, key))
    args = VALID_ARGS[name]
    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


def test_veri_her_cagrida_ortamdan_yeniden_okunur(monkeypatch, corrupted):
    args = {"direction": "all"}
    assert call("get_flight_summary", args)["value"]["total"] == 600
    monkeypatch.setenv("COPILOT_DATA", corrupted["undefined_flight"])
    second = call("get_flight_summary", args)
    assert second["value"]["total"] == 599
    assert second["source"] == corrupted["undefined_flight"]
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)
    assert call("get_flight_summary", args)["value"]["total"] == 600


def test_as_of_saatin_o_anki_degeridir(monkeypatch):
    monkeypatch.setenv("COPILOT_NOW", "2026-10-20T09:00:00+03:00")
    assert call("get_flight_summary", {"direction": "all"})["as_of"] == (
        "2026-10-20T09:00:00+03:00"
    )


# --- get_flight_summary -------------------------------------------------------------


@pytest.mark.parametrize("direction", ["all", "arrival", "departure"])
def test_ozet_referans_veriyle_eslesir(direction):
    value = {"date": "2026-10-20", "direction": direction, **SUMMARIES[direction]}
    assert call("get_flight_summary", {"direction": direction}) == tool_envelope(
        value, {"direction": direction}
    )


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"direction": "ALL"},
        {"direction": "gelen"},
        {"direction": ""},
        {"direction": None},
        {"direction": "all", "airline": "TK"},
    ],
)
def test_ozet_gecersiz_argumanda_sema_hatasi_verir(args):
    assert call("get_flight_summary", args) == layer_envelope(ARGS_INVALID)


def test_ozet_yetim_kayitlari_saymaz(monkeypatch, corrupted):
    monkeypatch.setenv("COPILOT_DATA", corrupted["undefined_flight"])
    value = {
        "date": "2026-10-20",
        "direction": "departure",
        "total": 299,
        "cancelled": 2,
        "delayed": 70,
    }
    assert call("get_flight_summary", {"direction": "departure"}) == tool_envelope(
        value, {"direction": "departure"}, source=corrupted["undefined_flight"]
    )


@pytest.mark.parametrize("scenario", ["duplicate_callsign", "missing_estimated"])
def test_ozet_sayimda_kullanilmayan_bozulmadan_etkilenmez(
    scenario, monkeypatch, corrupted
):
    monkeypatch.setenv("COPILOT_DATA", corrupted[scenario])
    value = {"date": "2026-10-20", "direction": "all", **SUMMARIES["all"]}
    assert call("get_flight_summary", {"direction": "all"}) == tool_envelope(
        value, {"direction": "all"}, source=corrupted[scenario]
    )


@pytest.mark.parametrize("scenario", ["missing_cancelled", "missing_movement_type"])
def test_ozet_zorunlu_alan_eksikse_kismi_sayi_vermez(scenario, monkeypatch, corrupted):
    monkeypatch.setenv("COPILOT_DATA", corrupted[scenario])
    args = {"direction": "all"}
    assert call("get_flight_summary", args) == layer_envelope(
        DATA_INVALID, filters=args
    )


# --- resolve_flight_identity --------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "matched_on"),
    [
        ("TK2345", "flight_no"),
        ("THY2345", "callsign"),
        (" thy2345 ", "callsign"),
        ("tk2345", "flight_no"),
    ],
)
def test_kimlik_tek_eslesmede_aday_nesnesi_doner(query, matched_on):
    value = {**TK2345_CANDIDATE, "matched_on": matched_on}
    assert call("resolve_flight_identity", {"query": query}) == tool_envelope(
        value, {"query": query}
    )


@pytest.mark.parametrize("query", ["TC-LSD", "tc-lsd"])
def test_tescil_birden_fazla_ucusla_eslesince_adaylari_listeler(query):
    value = [
        {**TK2344_CANDIDATE, "matched_on": "registration"},
        {**TK2345_CANDIDATE, "matched_on": "registration"},
    ]
    assert call("resolve_flight_identity", {"query": query}) == tool_envelope(
        value, {"query": query}, error=AMBIGUOUS
    )


@pytest.mark.parametrize(
    "query", ["ZZ9999", "TK234", "2345", "THY", "FL-20261020-0270"]
)
def test_kimlik_eslesmezse_not_found_doner(query):
    assert call("resolve_flight_identity", {"query": query}) == tool_envelope(
        None, {"query": query}, error=NOT_FOUND
    )


def test_iptal_edilen_ucus_normal_aday_olarak_doner():
    value = {
        "flight_id": CANCELLED_ID,
        "flight_no": "TK5086",
        "callsign": "THY5086",
        "registration": "TC-TIX",
        "movement_type": "ARRIVAL",
        "scheduled_time": "2026-10-20T07:55:00+03:00",
        "matched_on": "flight_no",
    }
    assert call("resolve_flight_identity", {"query": "TK5086"}) == tool_envelope(
        value, {"query": "TK5086"}
    )


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": 2345},
        {"query": None},
        {"query": "TK2345", "type": "flight_no"},
    ],
)
def test_kimlik_gecersiz_argumanda_sema_hatasi_verir(args):
    assert call("resolve_flight_identity", args) == layer_envelope(ARGS_INVALID)


def test_cift_callsign_iki_adayla_belirsiz_doner(monkeypatch, corrupted):
    source = corrupted["duplicate_callsign"]
    monkeypatch.setenv("COPILOT_DATA", source)
    envelope = call("resolve_flight_identity", {"query": "THY2345"})
    assert envelope["error"] == AMBIGUOUS
    assert envelope["author"] == "tool"
    assert envelope["source"] == source
    assert [c["flight_id"] for c in envelope["value"]] == [DUPLICATE_ID, TK2345_ID]
    assert [c["matched_on"] for c in envelope["value"]] == ["callsign", "callsign"]
    assert envelope["value"][1] == {**TK2345_CANDIDATE, "matched_on": "callsign"}
    assert envelope["value"][0]["flight_no"] == "TK2533"


def test_cift_callsign_veride_sefer_no_tekil_kalir(monkeypatch, corrupted):
    source = corrupted["duplicate_callsign"]
    monkeypatch.setenv("COPILOT_DATA", source)
    value = {**TK2345_CANDIDATE, "matched_on": "flight_no"}
    assert call("resolve_flight_identity", {"query": "TK2345"}) == tool_envelope(
        value, {"query": "TK2345"}, source=source
    )


@pytest.mark.parametrize("query", ["TK2345", "THY2345"])
def test_tanimsiz_ucus_yetim_kayitlardan_bulunmaz(query, monkeypatch, corrupted):
    source = corrupted["undefined_flight"]
    monkeypatch.setenv("COPILOT_DATA", source)
    assert call("resolve_flight_identity", {"query": query}) == tool_envelope(
        None, {"query": query}, error=NOT_FOUND, source=source
    )


def test_eksik_callsign_ile_aranamaz_ama_sefer_no_ile_bulunur(monkeypatch, corrupted):
    source = corrupted["missing_callsign"]
    monkeypatch.setenv("COPILOT_DATA", source)
    assert call("resolve_flight_identity", {"query": "THY2345"}) == tool_envelope(
        None, {"query": "THY2345"}, error=NOT_FOUND, source=source
    )
    value = {**TK2345_CANDIDATE, "matched_on": "flight_no"}
    del value["callsign"]
    assert call("resolve_flight_identity", {"query": "TK2345"}) == tool_envelope(
        value, {"query": "TK2345"}, source=source
    )


@pytest.mark.parametrize(
    ("query", "candidate", "matched_on"),
    [
        ("THY02345", TK2345_CANDIDATE, "callsign"),
        ("thy002345", TK2345_CANDIDATE, "callsign"),
        ("TK02344", TK2344_CANDIDATE, "flight_no"),
    ],
)
def test_sayidaki_bastaki_sifirlar_yok_sayilir(query, candidate, matched_on):
    value = {**candidate, "matched_on": matched_on}
    assert call("resolve_flight_identity", {"query": query}) == tool_envelope(
        value, {"query": query}
    )


@pytest.mark.parametrize(
    ("query", "matched_on"),
    [("THY15", "callsign"), ("thy0015", "callsign"), ("tk15", "flight_no")],
)
def test_kayittaki_bastaki_sifirlar_da_yok_sayilir(
    query, matched_on, monkeypatch, tmp_path
):
    # Referans veride sıfırla başlayan sefer no yok; tek uçuşluk küçük bir dosya.
    flight = {
        "flight_id": "FL-20261020-0001",
        "flight_no": "TK0015",
        "callsign": "THY0015",
        "registration": "TC-ABC",
        "aircraft_type": "A321",
        "origin": "XXXX",
        "destination": "VAN",
        "scheduled_time": "2026-10-20T08:00:00+03:00",
        "estimated_time": "2026-10-20T08:00:00+03:00",
        "cancelled": False,
    }
    movement = {
        "flight_id": "FL-20261020-0001",
        "movement_type": "DEPARTURE",
        "stand_code": None,
        "gate_code": None,
        "actual_runway_time": None,
        "actual_block_time": None,
    }
    data = {
        "meta": {"seed": 1, "date": "2026-10-20", "generator_version": "1.0.0"},
        "aircraft": [],
        "stands": [],
        "gates": [],
        "flights": [flight],
        "movements": [movement],
        "delays": [],
        "positions": [],
    }
    path = tmp_path / "sifirli.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("COPILOT_DATA", str(path))
    value = {
        "flight_id": "FL-20261020-0001",
        "flight_no": "TK0015",
        "callsign": "THY0015",
        "registration": "TC-ABC",
        "movement_type": "DEPARTURE",
        "scheduled_time": "2026-10-20T08:00:00+03:00",
        "matched_on": matched_on,
    }
    assert call("resolve_flight_identity", {"query": query}) == tool_envelope(
        value, {"query": query}, source=str(path)
    )
    for other in ("15", "THY", "THY150", "TK015X"):
        assert call("resolve_flight_identity", {"query": other})["error"] == NOT_FOUND


# --- get_flight_details -------------------------------------------------------------


def test_detay_tum_alanlari_ve_son_konumu_doner():
    assert call("get_flight_details", {"flight_id": TK2345_ID}) == tool_envelope(
        TK2345_DETAILS, {"flight_id": TK2345_ID}
    )


def test_gecikmesiz_ucusta_gecikme_alanlari_yoktur():
    assert call("get_flight_details", {"flight_id": TK2344_ID}) == tool_envelope(
        TK2344_DETAILS, {"flight_id": TK2344_ID}
    )


def test_iptal_edilen_ucusta_null_alanlar_ve_konum_yazilmaz():
    assert call("get_flight_details", {"flight_id": CANCELLED_ID}) == tool_envelope(
        CANCELLED_DETAILS, {"flight_id": CANCELLED_ID}
    )


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"flight_id": "TK2345"},
        {"flight_id": "fl-20261020-0270"},
        {"flight_id": ""},
        {"flight_id": "FL-20261020-270"},
        {"flight_id": " FL-20261020-0270"},
        {"flight_id": None},
        {"flight_id": TK2345_ID, "flight_no": "TK2345"},
    ],
)
def test_detay_gecersiz_argumanda_sema_hatasi_verir(args):
    assert call("get_flight_details", args) == layer_envelope(ARGS_INVALID)


def test_bicime_uyan_ama_olmayan_flight_id_not_found_doner():
    args = {"flight_id": "FL-20261020-9999"}
    assert call("get_flight_details", args) == tool_envelope(
        None, args, error=NOT_FOUND
    )


def test_tanimsiz_ucusun_yetim_kayitlari_kullanilmaz(monkeypatch, corrupted):
    source = corrupted["undefined_flight"]
    monkeypatch.setenv("COPILOT_DATA", source)
    args = {"flight_id": TK2345_ID}
    assert call("get_flight_details", args) == tool_envelope(
        None, args, error=NOT_FOUND, source=source
    )


def test_konum_saatten_sonraki_noktalari_kullanmaz(monkeypatch):
    now = "2026-10-20T16:10:15+03:00"
    monkeypatch.setenv("COPILOT_NOW", now)
    value = {**TK2345_DETAILS, "position": TK2345_POSITION_1610}
    args = {"flight_id": TK2345_ID}
    assert call("get_flight_details", args) == tool_envelope(value, args, as_of=now)


def test_saat_esit_ts_li_nokta_secilir(monkeypatch):
    now = "2026-10-20T16:10:00+03:00"
    monkeypatch.setenv("COPILOT_NOW", now)
    envelope = call("get_flight_details", {"flight_id": TK2345_ID})
    assert envelope["value"]["position"] == TK2345_POSITION_1610


def test_konum_izi_baslamamissa_position_yoktur(monkeypatch):
    now = "2026-10-20T16:00:00+03:00"
    monkeypatch.setenv("COPILOT_NOW", now)
    value = {k: v for k, v in TK2345_DETAILS.items() if k != "position"}
    args = {"flight_id": TK2345_ID}
    # actual_* zamanları saate göre süzülmez (docs/tools.md › Kenar durumlar).
    assert call("get_flight_details", args) == tool_envelope(value, args, as_of=now)


def test_eski_konum_ts_iyle_doner_ve_stale_isaretlenmez(monkeypatch, corrupted):
    source = corrupted["stale_position"]
    monkeypatch.setenv("COPILOT_DATA", source)
    value = {**TK2345_DETAILS, "position": TK2345_POSITION_1612}
    args = {"flight_id": TK2345_ID}
    assert call("get_flight_details", args) == tool_envelope(value, args, source=source)


@pytest.mark.parametrize(
    ("scenario", "field"),
    [("missing_estimated", "estimated_time"), ("missing_stand", "stand_code")],
)
def test_eksik_alan_valueda_yer_almaz(scenario, field, monkeypatch, corrupted):
    source = corrupted[scenario]
    monkeypatch.setenv("COPILOT_DATA", source)
    value = {k: v for k, v in TK2345_DETAILS.items() if k != field}
    args = {"flight_id": TK2345_ID}
    assert call("get_flight_details", args) == tool_envelope(value, args, source=source)


def test_detay_cift_callsign_bozulmasindan_etkilenmez(monkeypatch, corrupted):
    source = corrupted["duplicate_callsign"]
    monkeypatch.setenv("COPILOT_DATA", source)
    args = {"flight_id": TK2345_ID}
    assert call("get_flight_details", args) == tool_envelope(
        TK2345_DETAILS, args, source=source
    )
