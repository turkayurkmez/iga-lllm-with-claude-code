"""get_chart_data tool'u ve chart_card olayı (docs/tools.md, docs/chat.md).

Beklenen sayılar data/referans/seed42-2026-10-20.json'dan bu dosyada bağımsız
hesaplanır; ayrıca gelen uçuşların havayolu dağılımı sabit yazılmıştır. API'siz.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from backend.cards import CardBuilder
from backend.tools import run_tool, tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
NAME = "get_chart_data"
BAR = {"chart_type": "bar_horizontal", "group_by": "airline", "direction": "arrival"}
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


@pytest.fixture(autouse=True)
def veri(monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)
    monkeypatch.setenv("COPILOT_NOW", NOW)


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads((REPO_ROOT / REFERENCE).read_text(encoding="utf-8"))


def items(envelope: dict) -> list[tuple[str, float]]:
    return [(i["label"], i["value"]) for i in envelope["value"]["items"]]


def test_tool_kayitli_ve_son_sirada():
    names = [definition["name"] for definition in tool_definitions()]

    assert names.count(NAME) == 1
    assert names[-1] == NAME


def test_kontrat_aciklamasi_sorma_kuralini_ve_uc_soruyu_icerir():
    contract = json.loads(
        (REPO_ROOT / "backend/tools/contracts/get_chart_data.json").read_text(
            encoding="utf-8"
        )
    )
    description = contract["description"]

    assert "Ne zaman kullanılır" in description
    assert "Ne zaman KULLANILMAZ" in description
    assert "ÇAĞIRMA; önce hangi türü" in description


def test_gelen_ucuslar_havayoluna_gore_sayilir():
    envelope = run_tool(NAME, BAR)

    assert envelope["error"] is None
    assert items(envelope) == ARRIVAL_AIRLINES
    assert envelope["value"]["flights"] == 300
    assert envelope["value"]["groups_total"] == 10
    assert envelope["value"]["unclassified"] == 0
    assert envelope["filters"]["direction"] == "arrival"
    assert envelope["filters"]["metric"] == "count"
    assert envelope["source"] == REFERENCE


def test_chart_type_zarfa_oldugu_gibi_gecer():
    for chart_type in ("bar_horizontal", "bar_vertical", "pie"):
        envelope = run_tool(NAME, {**BAR, "chart_type": chart_type})

        assert envelope["value"]["chart_type"] == chart_type


def test_limit_en_buyuk_gruplari_keser_ama_toplam_grup_sayisi_kalir():
    envelope = run_tool(NAME, {**BAR, "limit": 5})

    assert items(envelope) == ARRIVAL_AIRLINES[:5]
    assert envelope["value"]["groups_total"] == 10


def test_saat_dagilimi_saat_artan_sirayla_ve_limitsiz(raw):
    envelope = run_tool(
        NAME, {"chart_type": "line", "group_by": "hour", "direction": "departure"}
    )

    departures = {
        m["flight_id"] for m in raw["movements"] if m["movement_type"] == "DEPARTURE"
    }
    expected = Counter(
        f["scheduled_time"][11:13]
        for f in raw["flights"]
        if f["flight_id"] in departures
    )
    assert items(envelope) == sorted(expected.items())
    assert envelope["value"]["groups_total"] == len(expected)


def test_durum_dagilimi_iptal_gecikmeli_zamaninda(raw):
    envelope = run_tool(NAME, {"chart_type": "pie", "group_by": "status"})

    assert items(envelope) == [("cancelled", 4), ("delayed", 115), ("on_time", 481)]


def test_iptaller_haric_tutulabilir():
    envelope = run_tool(NAME, {**BAR, "include_cancelled": False})

    assert envelope["value"]["flights"] == 298
    assert sum(value for _, value in items(envelope)) == 298


def test_boyutu_olmayan_ucus_gruba_girmez_ama_sayilir():
    envelope = run_tool(
        NAME,
        {"chart_type": "bar_vertical", "group_by": "stand", "direction": "arrival"},
    )

    assert envelope["value"]["unclassified"] == 2
    assert envelope["value"]["flights"] == 300


def test_gecikme_olcusu_yalniz_gecikmeli_ucuslardan_hesaplanir(raw):
    delays = {d["flight_id"]: d["delay_minutes"] for d in raw["delays"]}
    by_type = {f["flight_id"]: f["aircraft_type"] for f in raw["flights"]}
    total: Counter = Counter()
    for flight_id, minutes in delays.items():
        total[by_type[flight_id]] += minutes

    envelope = run_tool(
        NAME,
        {
            "chart_type": "pie",
            "group_by": "aircraft_type",
            "metric": "total_delay_minutes",
            "limit": 20,
        },
    )

    assert dict(items(envelope)) == dict(total)
    assert sum(v for _, v in items(envelope)) == sum(delays.values())


@pytest.mark.parametrize(
    "args",
    [
        {"chart_type": "line", "group_by": "airline"},
        {"chart_type": "donut", "group_by": "airline"},
        {"chart_type": "pie", "group_by": "pax"},
        {"chart_type": "pie", "group_by": "airline", "limit": 7},
        {"group_by": "airline"},
        {"chart_type": "pie"},
        {"chart_type": "pie", "group_by": "airline", "series": [1, 2]},
    ],
)
def test_gecersiz_tarif_sema_hatasi_verir_ve_veriyi_okumaz(args, monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", "yok.json")

    envelope = run_tool(NAME, args)

    assert envelope["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert envelope["author"] == "layer"
    assert envelope["value"] is None


def test_veri_okunamazsa_genel_hata_doner(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))

    envelope = run_tool(NAME, BAR)

    assert envelope["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert envelope["value"] is None
    assert str(tmp_path) not in json.dumps(envelope)


# ───────── chart_card ─────────


def test_chart_karti_zarfin_alanlarini_oldugu_gibi_tasir():
    envelope = run_tool(NAME, BAR)

    events = CardBuilder().cards(NAME, envelope)

    kinds = [name for name, _ in events]
    assert kinds == ["source_chip", "chart_card"]
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
    envelope = run_tool(NAME, {"chart_type": "line", "group_by": "airline"})

    kinds = [name for name, _ in CardBuilder().cards(NAME, envelope)]

    assert kinds == []


def test_baska_tool_chart_karti_uretmez():
    envelope = run_tool("get_flight_summary", {"direction": "all"})

    kinds = [name for name, _ in CardBuilder().cards("get_flight_summary", envelope)]

    assert "chart_card" not in kinds
    assert "kpi_card" in kinds
