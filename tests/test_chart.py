"""get_chart_data tool'u (kontrat 2.0.0) ve chart_card olayı (docs/tools.md, chat.md).

Test günü 2026-10-20'dir (COPILOT_DATA referans dosya, COPILOT_NOW aynı gün). Beklenen
sayılar referans dosyadan bu dosyada bağımsız hesaplanır; havayolu dağılımı ayrıca
sabit yazılmıştır. API'siz.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend.cards import CardBuilder
from backend.tools import run_tool, tool_definitions
from backend.tools.chart_fields import CATEGORICAL, FIELDS, NUMERIC, TIME

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "data/referans/seed42-2026-10-20.json"
CONTRACT = REPO_ROOT / "backend/tools/contracts/get_chart_data.json"
NOW = "2026-10-20T16:22:00+03:00"
NAME = "get_chart_data"
TYPES = [
    "bar_horizontal",
    "bar_vertical",
    "stacked_bar",
    "grouped_bar",
    "pie",
    "doughnut",
    "line",
    "area",
    "heatmap",
]
HOUR = {"field": "scheduled_time", "bucket": "hour"}
BAR_AIRLINES = {
    "chart_type": "bar_horizontal",
    "group_by": {"field": "airline"},
    "filters": [{"field": "movement_type", "op": "eq", "value": "ARRIVAL"}],
}
ARRIVAL_AIRLINES = [
    ("TK", 154),
    ("AJ", 34),
    ("QR", 25),
    ("PC", 23),
    ("AF", 15),
    ("KL", 13),
    ("LX", 13),
    ("BA", 10),
    ("LH", 7),
    ("EK", 6),
]
Q2 = {
    "chart_type": "bar_horizontal",
    "group_by": HOUR,
    "series_by": {"field": "movement_type"},
    "filters": [
        {"field": "scheduled_time", "op": "ge", "value": "17:00"},
        {"field": "scheduled_time", "op": "lt", "value": "19:00"},
    ],
    "derive": "pct_change_vs_previous",
    "plot": "change_pct",
}


@pytest.fixture(autouse=True)
def veri(monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)
    monkeypatch.setenv("COPILOT_NOW", NOW)


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads((REPO_ROOT / REFERENCE).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def pairs(envelope: dict) -> list[tuple[str, float]]:
    return [(i["label"], i["value"]) for i in envelope["value"]["items"]]


# --- Kontrat ---------------------------------------------------------------------


def test_tool_kayitli_ve_son_sirada():
    names = [definition["name"] for definition in tool_definitions()]

    assert names.count(NAME) == 1
    assert names[-1] == NAME


def test_kontrat_aciklamasi_sorma_kuralini_ve_uc_soruyu_icerir(contract):
    description = contract["description"]

    assert "Ne zaman kullanılır" in description
    assert "Ne zaman KULLANILMAZ" in description
    assert "ÇAĞIRMA; önce hangi türü" in description


def objects(node: object):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from objects(value)


def test_kontrat_surumu_ve_semalari_gecerli(contract):
    assert contract["version"] == "2.0.0"
    for key in ("input_schema", "value_schema"):
        Draft202012Validator.check_schema(contract[key])
        nodes = list(objects(contract[key]))
        assert nodes
        assert all(node.get("additionalProperties") is False for node in nodes)
    banned = r'"(minLength|maxLength|minimum|maximum|multipleOf|maxItems)"\s*:'
    assert re.search(banned, CONTRACT.read_text(encoding="utf-8")) is None


def test_kontrat_alan_enumlari_FIELDS_ile_birebir_ayni(contract):
    properties = contract["input_schema"]["properties"]
    group_field = properties["group_by"]["properties"]["field"]["enum"]
    filter_item = properties["filters"]["items"]["properties"]

    assert group_field == [*CATEGORICAL, *TIME]
    assert properties["series_by"]["properties"]["field"]["enum"] == group_field
    assert properties["measure"]["properties"]["field"]["enum"] == list(NUMERIC)
    assert filter_item["field"]["enum"] == [*CATEGORICAL, *TIME, *NUMERIC]
    assert filter_item["field"]["enum"] == list(FIELDS)
    assert properties["chart_type"]["enum"] == TYPES
    assert filter_item["op"]["enum"] == ["eq", "ne", "in", "gt", "ge", "lt", "le"]


# --- Sorgular ----------------------------------------------------------------------


def test_gelen_ve_giden_pasta_iki_dilim(raw):
    flights = {f["flight_id"] for f in raw["flights"]}
    expected = Counter(
        m["movement_type"] for m in raw["movements"] if m["flight_id"] in flights
    )

    envelope = run_tool(
        NAME, {"chart_type": "pie", "group_by": {"field": "movement_type"}}
    )

    assert envelope["error"] is None
    assert pairs(envelope) == sorted(expected.items())
    assert pairs(envelope) == [("ARRIVAL", 300), ("DEPARTURE", 300)]
    assert envelope["value"]["flights"] == 600
    assert envelope["value"]["groups_total"] == 2
    assert envelope["source"] == REFERENCE


def test_gelen_ucuslar_havayoluna_gore():
    envelope = run_tool(NAME, BAR_AIRLINES)

    assert envelope["error"] is None
    assert pairs(envelope) == ARRIVAL_AIRLINES
    assert envelope["value"]["flights"] == 300
    assert envelope["value"]["groups_total"] == 10
    assert envelope["value"]["unclassified"] == 0
    assert envelope["filters"]["sort"] == "value_desc"
    assert envelope["filters"]["limit"] == 10
    assert envelope["filters"]["plot"] == "value"


def test_saat_x_yon_yigilmis_toplami_ucus_sayisina_esit():
    envelope = run_tool(
        NAME,
        {
            "chart_type": "stacked_bar",
            "group_by": HOUR,
            "series_by": {"field": "movement_type"},
        },
    )

    items = envelope["value"]["items"]
    assert envelope["error"] is None
    assert items
    assert sum(item["value"] for item in items) == 600
    assert envelope["value"]["series_truncated"] == 0
    assert all("series" in item for item in items)
    assert {item["series"] for item in items} == {"ARRIVAL", "DEPARTURE"}


def test_ortalama_gecikme_ucak_tipine_gore(raw):
    delays = {d["flight_id"]: d["delay_minutes"] for d in raw["delays"]}
    by_type = defaultdict(list)
    for f in raw["flights"]:
        if f["flight_id"] in delays:
            by_type[f["aircraft_type"]].append(delays[f["flight_id"]])
    expected = {t: round(sum(v) / len(v), 1) for t, v in by_type.items()}

    envelope = run_tool(
        NAME,
        {
            "chart_type": "bar_vertical",
            "group_by": {"field": "aircraft_type"},
            "measure": {"agg": "avg", "field": "delay_minutes"},
            "limit": 20,
        },
    )

    assert envelope["error"] is None
    assert expected
    assert dict(pairs(envelope)) == expected


def test_gecikme_60_dakikadan_fazla_suzgeci(raw):
    known = {f["flight_id"] for f in raw["flights"]}
    moved = {m["flight_id"] for m in raw["movements"]}
    expected = sum(
        1
        for d in raw["delays"]
        if d["flight_id"] in known & moved and d["delay_minutes"] > 60
    )

    envelope = run_tool(
        NAME,
        {
            "chart_type": "pie",
            "group_by": {"field": "status"},
            "filters": [{"field": "delay_minutes", "op": "gt", "value": 60}],
        },
    )

    assert expected > 0
    assert envelope["error"] is None
    assert envelope["value"]["flights"] == expected
    assert sum(value for _, value in pairs(envelope)) == expected


@pytest.mark.parametrize("field", [*CATEGORICAL, *TIME])
def test_tum_alanlar_gruplanabilir(field):
    group_by = {"field": field}
    if field in TIME:
        group_by["bucket"] = "hour"

    envelope = run_tool(
        NAME, {"chart_type": "bar_horizontal", "group_by": group_by, "limit": 50}
    )

    assert envelope["error"] is None, field
    assert envelope["value"]["groups_total"] >= 1
    assert envelope["value"]["items"]


def test_q2_gelen_giden_18_00_17_00_degisimi_yatay_cubuk(raw):
    flights = {f["flight_id"]: f for f in raw["flights"]}
    counts = Counter()
    for m in raw["movements"]:
        hour = flights[m["flight_id"]]["scheduled_time"][11:13]
        if hour in ("17", "18"):
            counts[(f"{hour}:00", m["movement_type"])] += 1
    assert min(counts.values()) > 0
    assert len(counts) == 4

    envelope = run_tool(NAME, Q2)

    assert envelope["error"] is None
    assert envelope["value"]["plot"] == "change_pct"
    assert envelope["value"]["derive"] == "pct_change_vs_previous"
    items = {(i["label"], i["series"]): i for i in envelope["value"]["items"]}
    assert set(items) == set(counts)
    for series in ("ARRIVAL", "DEPARTURE"):
        first, second = items[("17:00", series)], items[("18:00", series)]
        assert first["value"] == counts[("17:00", series)]
        assert "change_pct" not in first
        assert "trend" not in first
        before, now = counts[("17:00", series)], counts[("18:00", series)]
        assert second["value"] == now
        assert second["change_pct"] == round((now - before) / before * 100, 1)
        expected = "up" if now > before else "down" if now < before else "flat"
        assert second["trend"] == expected


def test_degisim_tarifi_kart_olarak_tasinir():
    envelope = run_tool(NAME, Q2)

    events = dict(CardBuilder().cards(NAME, envelope))

    card = events["chart_card"]
    assert card["plot"] == "change_pct"
    assert card["items"] == envelope["value"]["items"]
    assert any("change_pct" in item for item in card["items"])


def test_hicbir_ucus_kalmazsa_hata_degil_bos_items():
    envelope = run_tool(
        NAME,
        {
            "chart_type": "bar_horizontal",
            "group_by": {"field": "airline"},
            "filters": [{"field": "airline", "op": "eq", "value": "ZZ"}],
        },
    )

    assert envelope["error"] is None
    assert envelope["value"]["flights"] == 0
    assert envelope["value"]["items"] == []


# --- Geçersiz tarifler: veri okunmaz -------------------------------------------------

BAD = {
    "ek_alan_series": {"series": [1, 2]},
    "bilinmeyen_alan": {"group_by": {"field": "pax"}},
    "sayisal_olmayan_olcu": {"measure": {"agg": "sum", "field": "airline"}},
    "bilinmeyen_tur": {"chart_type": "donut"},
    "limit_7": {"limit": 7},
    "bilinmeyen_islec": {"filters": [{"field": "airline", "op": "like", "value": "T"}]},
    "group_by_yok": {"group_by": None},
    "line_kategorik": {"chart_type": "line"},
    "stacked_serisiz": {"chart_type": "stacked_bar"},
    "pie_seriyle": {"chart_type": "pie", "series_by": {"field": "movement_type"}},
    "plot_derivesiz": {"plot": "change_pct"},
}


@pytest.mark.parametrize("name", BAD)
def test_gecersiz_tarif_sema_hatasi_verir_ve_veriyi_okumaz(name, monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", "yok.json")
    args = {"chart_type": "bar_horizontal", "group_by": {"field": "airline"}}
    for key, value in BAD[name].items():
        if value is None:
            del args[key]
        else:
            args[key] = value

    envelope = run_tool(NAME, args)

    assert envelope["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert envelope["author"] == "layer"
    assert envelope["value"] is None
    assert envelope["tool_version"] == "2.0.0"


def test_veri_okunamazsa_genel_hata_doner(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))

    envelope = run_tool(NAME, BAR_AIRLINES)

    assert envelope["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert envelope["value"] is None
    assert str(tmp_path) not in json.dumps(envelope)


# --- chart_card ----------------------------------------------------------------------


def test_chart_karti_zarfin_alanlarini_oldugu_gibi_tasir():
    envelope = run_tool(NAME, BAR_AIRLINES)

    events = CardBuilder().cards(NAME, envelope)

    assert [name for name, _ in events] == ["source_chip", "chart_card"]
    card = dict(events)["chart_card"]
    assert card == {
        "tool": NAME,
        **envelope["value"],
        "filters": envelope["filters"],
        "source": envelope["source"],
        "as_of": envelope["as_of"],
    }
    assert [(i["label"], i["value"]) for i in card["items"]] == ARRIVAL_AIRLINES


def test_hatali_zarftan_chart_karti_cikmaz():
    envelope = run_tool(
        NAME, {"chart_type": "line", "group_by": {"field": "airline"}}
    )

    assert [name for name, _ in CardBuilder().cards(NAME, envelope)] == []


def test_baska_tool_chart_karti_uretmez():
    envelope = run_tool("get_flight_summary", {"direction": "all"})

    kinds = [name for name, _ in CardBuilder().cards("get_flight_summary", envelope)]

    assert "chart_card" not in kinds
    assert "kpi_card" in kinds
