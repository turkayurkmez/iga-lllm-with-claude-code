"""Tool çıktı zarfı sözleşme testleri (docs/zarf.md).

Testler koddan önce yazıldı; backend/envelope.py yokken kırmızıdır. Saat her testte
COPILOT_NOW ile zarf.md örneklerindeki simüle saate sabitlenir.
"""

import importlib
import importlib.util
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent
NOW = "2026-10-20T16:22:00+03:00"
REFERENCE = "data/referans/seed42-2026-10-20.json"
STALE_SOURCE = "synth/out/stale.json"
FIELDS = {
    "value",
    "source",
    "as_of",
    "filters",
    "stale",
    "tool_version",
    "error",
    "author",
}
ERROR_CODES = {
    "NOT_FOUND",
    "AMBIGUOUS_ENTITY",
    "STALE_DATA",
    "CAPABILITY_NOT_IN_SCOPE",
    "SCHEMA_VALIDATION_FAILED",
}
POSITION = {
    "flight_id": "FL-20261020-0270",
    "flight_no": "TK2345",
    "ts": "2026-10-20T16:12:00+03:00",
    "lat": 41.197692,
    "lon": 28.680769,
    "heading_deg": 235.0,
    "speed_kt": 187.7,
    "phase": "CLIMB",
}


def load_envelope():
    assert importlib.util.find_spec("backend.envelope") is not None, (
        "backend/envelope.py yok"
    )
    return importlib.import_module("backend.envelope")


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setenv("COPILOT_NOW", NOW)


class SummaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["all", "arrival", "departure"] = "all"


class FlightArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flight_no: str


def flight_summary(direction):
    return {
        "value": {
            "date": "2026-10-20",
            "direction": direction,
            "total": 600,
            "cancelled": 4,
            "delayed": 115,
        },
        "source": REFERENCE,
    }


def flight_position(flight_no):
    if flight_no != "TK2345":
        return {
            "value": None,
            "source": REFERENCE,
            "error": {
                "code": "NOT_FOUND",
                "message": "Bu sefer numarasıyla uçuş bulunamadı.",
            },
        }
    return {"value": POSITION, "source": STALE_SOURCE, "data_time": POSITION["ts"]}


def spec(name, func, args_model, max_age=None):
    envelope = load_envelope()
    return envelope.ToolSpec(
        name=name,
        version="1.0.0",
        func=func,
        args_model=args_model,
        max_age=max_age,
    )


def registry(*specs):
    return {s.name: s for s in specs}


def call_single(func, args, args_model=FlightArgs, max_age=None):
    envelope = load_envelope()
    tools = registry(spec("tool_x", func, args_model, max_age))
    return envelope.call_tool(tools, "tool_x", args)


def doc_examples():
    text = (REPO_ROOT / "docs" / "zarf.md").read_text(encoding="utf-8")
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, re.DOTALL)]


# --- Zarfın biçimi ---


def test_zarf_tam_olarak_sekiz_alan_tasir():
    result = call_single(flight_summary, {}, SummaryArgs)

    assert set(result) == FIELDS


def test_hata_kodlari_belgeyle_ayni():
    envelope = load_envelope()

    assert {code.value for code in envelope.ErrorCode} == ERROR_CODES


def test_zarf_json_olarak_yazilabilir():
    result = call_single(flight_position, {"flight_no": "TK2345"}, max_age=None)

    assert json.loads(json.dumps(result, ensure_ascii=False)) == result


def test_belgedeki_uc_ornek_kodun_uretimiyle_ayni():
    envelope = load_envelope()
    tools = registry(
        spec("get_flight_summary", flight_summary, SummaryArgs),
        spec(
            "get_flight_position",
            flight_position,
            FlightArgs,
            max_age=timedelta(minutes=5),
        ),
    )
    produced = [
        envelope.call_tool(tools, "get_flight_summary", {"direction": "all"}),
        envelope.call_tool(tools, "get_flight_position", {"flight_no": "TK2345"}),
        envelope.call_tool(tools, "get_flight_position", {"flight_no": "ZZ9999"}),
    ]

    assert produced == doc_examples()


# --- as_of ve stale katmanda hesaplanır ---


def test_veri_zamani_yoksa_as_of_saatten_gelir():
    result = call_single(flight_summary, {}, SummaryArgs)

    assert result["as_of"] == NOW
    assert result["stale"] is False


def test_veri_zamani_varsa_as_of_veri_zamanidir():
    result = call_single(flight_position, {"flight_no": "TK2345"})

    assert result["as_of"] == POSITION["ts"]


def test_tool_as_of_ve_stale_gonderirse_yok_sayilir():
    def tool(flight_no):
        return {
            "value": {"flight_no": flight_no},
            "source": REFERENCE,
            "as_of": "1999-01-01T00:00:00+03:00",
            "stale": True,
        }

    result = call_single(tool, {"flight_no": "TK2345"}, max_age=timedelta(minutes=5))

    assert result["as_of"] == NOW
    assert result["stale"] is False
    assert result["error"] is None
    assert result["author"] == "tool"


def test_veri_zamani_esigi_asarsa_stale_data_doner():
    result = call_single(
        flight_position, {"flight_no": "TK2345"}, max_age=timedelta(minutes=5)
    )

    assert result["stale"] is True
    assert result["error"]["code"] == "STALE_DATA"
    assert result["author"] == "layer"
    assert result["value"] == POSITION
    assert result["as_of"] == POSITION["ts"]
    assert result["source"] == STALE_SOURCE


def test_esige_esit_yastaki_veri_eski_sayilmaz():
    result = call_single(
        flight_position, {"flight_no": "TK2345"}, max_age=timedelta(minutes=10)
    )

    assert result["stale"] is False
    assert result["error"] is None
    assert result["author"] == "tool"


def test_esik_tanimsizsa_eski_veri_stale_sayilmaz():
    result = call_single(flight_position, {"flight_no": "TK2345"}, max_age=None)

    assert result["stale"] is False
    assert result["error"] is None


def test_saat_dilimsiz_veri_zamani_sema_hatasidir():
    def tool(flight_no):
        return {"value": {}, "source": REFERENCE, "data_time": "2026-10-20T16:12:00"}

    result = call_single(tool, {"flight_no": "TK2345"})

    assert result["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert result["author"] == "layer"
    assert result["value"] is None


# --- Tool hataları ---


def test_not_found_tool_tarafindan_yazilir():
    result = call_single(flight_position, {"flight_no": "ZZ9999"})

    assert result["error"]["code"] == "NOT_FOUND"
    assert result["author"] == "tool"
    assert result["value"] is None
    assert result["stale"] is False


def test_ambiguous_entity_adaylari_value_icinde_tasir():
    candidates = [
        {"flight_no": "TK2345", "registration": "TC-LSD"},
        {"flight_no": "TK1001", "registration": "TC-AAA"},
    ]

    def tool(flight_no):
        return {
            "value": candidates,
            "source": REFERENCE,
            "error": {"code": "AMBIGUOUS_ENTITY", "message": "Birden fazla uçuş."},
        }

    result = call_single(tool, {"flight_no": "THY2345"})

    assert result["error"]["code"] == "AMBIGUOUS_ENTITY"
    assert result["author"] == "tool"
    assert result["value"] == candidates


@pytest.mark.parametrize(
    "code", ["STALE_DATA", "CAPABILITY_NOT_IN_SCOPE", "SCHEMA_VALIDATION_FAILED"]
)
def test_tool_katman_kodunu_yazamaz(code):
    def tool(flight_no):
        return {
            "value": None,
            "source": REFERENCE,
            "error": {"code": code, "message": "x"},
        }

    result = call_single(tool, {"flight_no": "TK2345"})

    assert result["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert result["author"] == "layer"


# --- Katman hataları ---


def test_kayitsiz_tool_kapsam_disidir_ve_cagrilmaz():
    envelope = load_envelope()
    calls = []

    def tool(flight_no):
        calls.append(flight_no)
        return {"value": None, "source": REFERENCE}

    tools = registry(spec("tool_x", tool, FlightArgs))

    result = envelope.call_tool(tools, "predict_delay", {"flight_no": "TK2345"})

    assert calls == []
    assert result["error"]["code"] == "CAPABILITY_NOT_IN_SCOPE"
    assert result["author"] == "layer"
    assert result["value"] is None
    assert result["source"] is None
    assert result["tool_version"] is None
    assert set(result) == FIELDS


@pytest.mark.parametrize("args", [{}, {"flight_no": 42}, {"flight_no": "TK1", "x": 1}])
def test_semaya_uymayan_arguman_toolu_cagirmaz(args):
    calls = []

    def tool(flight_no):
        calls.append(flight_no)
        return {"value": None, "source": REFERENCE}

    result = call_single(tool, args)

    assert calls == []
    assert result["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert result["author"] == "layer"
    assert result["filters"] == {}
    assert result["tool_version"] == "1.0.0"


def test_filters_dogrulanmis_argumanlardir():
    result = call_single(flight_summary, {}, SummaryArgs)

    assert result["filters"] == {"direction": "all"}


@pytest.mark.parametrize(
    "output",
    [
        None,
        "metin",
        {"value": {}},
        {"value": {}, "source": REFERENCE, "error": {"code": "NOT_FOUND"}},
        {
            "value": {},
            "source": REFERENCE,
            "error": {"code": "BILINMEYEN", "message": "x"},
        },
    ],
)
def test_semaya_uymayan_tool_ciktisi_atilir(output):
    result = call_single(lambda flight_no: output, {"flight_no": "TK2345"})

    assert result["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert result["author"] == "layer"
    assert result["value"] is None
    assert set(result) == FIELDS


def test_katman_hatasi_ayrinti_sizdirmaz():
    secret = "postgres://copilot:gizli@db/copilot"

    result = call_single(lambda flight_no: {"value": secret}, {"flight_no": "TK2345"})

    assert secret not in json.dumps(result, ensure_ascii=False)


# --- Eksik alan hata değildir ---


def test_value_icindeki_eksik_alan_hata_degildir():
    flight = {"flight_no": "TK2345", "scheduled_time": "2026-10-20T15:40:00+03:00"}

    result = call_single(
        lambda flight_no: {"value": dict(flight), "source": REFERENCE},
        {"flight_no": "TK2345"},
    )

    assert result["error"] is None
    assert result["value"] == flight
    assert "estimated_time" not in result["value"]


# --- Envelope modeli ve JSON Schema ---


def schema_text(envelope):
    return (
        json.dumps(envelope.Envelope.model_json_schema(), ensure_ascii=False, indent=2)
        + "\n"
    )


def valid_envelope():
    return doc_examples()[0]


def test_belge_ornekleri_envelope_modeline_uyar():
    envelope = load_envelope()

    for example in doc_examples():
        model = envelope.Envelope.model_validate(example)
        assert model.model_dump(mode="json") == example


def test_sema_sekiz_alani_zorunlu_tutar_ve_fazlasini_reddeder():
    envelope = load_envelope()
    schema = envelope.Envelope.model_json_schema()

    assert set(schema["required"]) == FIELDS
    assert set(schema["properties"]) == FIELDS
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("field", sorted(FIELDS))
def test_envelope_eksik_alani_reddeder(field):
    envelope = load_envelope()
    data = valid_envelope()
    del data[field]

    with pytest.raises(ValidationError):
        envelope.Envelope.model_validate(data)


def test_envelope_fazla_alani_reddeder():
    envelope = load_envelope()

    with pytest.raises(ValidationError):
        envelope.Envelope.model_validate({**valid_envelope(), "confidence": 0.9})


@pytest.mark.parametrize(
    ("stale", "code"), [(True, None), (False, "STALE_DATA"), (True, "NOT_FOUND")]
)
def test_stale_ve_stale_data_birlikte_gider(stale, code):
    envelope = load_envelope()
    error = None if code is None else {"code": code, "message": "x"}

    with pytest.raises(ValidationError):
        envelope.Envelope.model_validate(
            {**valid_envelope(), "stale": stale, "error": error}
        )


def test_docs_altindaki_sema_modelle_ayni():
    envelope = load_envelope()
    path = REPO_ROOT / "docs" / "zarf.schema.json"

    assert path.read_bytes().decode("utf-8") == schema_text(envelope), (
        "Şema güncel değil: python -m backend.envelope"
    )
