"""Grafik için düz uçuş görünümü (spec: 2026-10-30-…-design.md › B › Düz uçuş görünümü).

Küçük elle yazılmış veriyle ve referans günle sınanır; ağ ve model yok.
"""

import importlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "data" / "referans" / "seed42-2026-10-20.json"
MODULE = "backend.tools.chart_fields"


def load():
    assert importlib.util.find_spec(MODULE) is not None, f"{MODULE} yok"
    return importlib.import_module(MODULE)


def flight(flight_id="F1", **extra) -> dict:
    base = {
        "flight_id": flight_id,
        "flight_no": "TK100",
        "callsign": "THY100",
        "registration": "TC-AAA",
        "aircraft_type": "A321",
        "origin": "IST",
        "destination": "DOH",
        "scheduled_time": "2026-10-20T10:00:00+03:00",
        "estimated_time": "2026-10-20T10:05:00+03:00",
        "cancelled": False,
    }
    return base | extra


def movement(flight_id="F1", **extra) -> dict:
    base = {
        "flight_id": flight_id,
        "movement_type": "DEPARTURE",
        "stand_code": "C101",
        "gate_code": "D6",
        "actual_runway_time": "2026-10-20T10:10:00+03:00",
        "actual_block_time": "2026-10-20T10:03:00+03:00",
    }
    return base | extra


def data(**tables) -> dict:
    base = {
        "meta": {"date": "2026-10-20"},
        "flights": [flight()],
        "movements": [movement()],
        "delays": [],
        "aircraft": [
            {
                "registration": "TC-AAA",
                "type_icao": "A321",
                "code_letter": "C",
                "operator_iata": "TK",
            }
        ],
        "stands": [{"stand_code": "C101", "stand_type": "CONTACT", "max_code_letter": "C"}],
    }
    return base | tables


def test_modul_var():
    assert load() is not None


def test_alan_listesi_spec_tablosuyla_birebir():
    fields = load()

    assert fields.CATEGORICAL == (
        "airline",
        "flight_no",
        "callsign",
        "registration",
        "aircraft_type",
        "origin",
        "destination",
        "code_letter",
        "operator_iata",
        "movement_type",
        "stand_code",
        "gate_code",
        "stand_type",
        "max_code_letter",
        "delay_code",
        "delay_category",
        "cancelled",
        "status",
    )
    assert fields.TIME == (
        "scheduled_time",
        "estimated_time",
        "actual_runway_time",
        "actual_block_time",
    )
    assert fields.NUMERIC == ("delay_minutes",)
    assert set(fields.FIELDS) == {*fields.CATEGORICAL, *fields.TIME, *fields.NUMERIC}
    assert {fields.FIELDS[name].kind for name in fields.CATEGORICAL} == {"categorical"}
    assert {fields.FIELDS[name].kind for name in fields.TIME} == {"time"}
    assert {fields.FIELDS[name].kind for name in fields.NUMERIC} == {"numeric"}


def test_airline_sefer_numarasinin_ilk_iki_karakteri_buyuk_harf():
    rows = load().build_rows(data(flights=[flight(flight_no="tk2345")]))

    assert len(rows) == 1
    assert rows[0]["airline"] == "TK"
    assert rows[0]["flight_no"] == "tk2345"


def test_hareketi_olmayan_ucus_satir_olmaz_yetim_hareket_kullanilmaz():
    rows = load().build_rows(
        data(
            flights=[flight("F1"), flight("F2")],
            movements=[movement("F1"), movement("YETIM")],
        )
    )

    assert [row["flight_no"] for row in rows] == ["TK100"]
    assert len(rows) == 1


def test_kaynakta_null_olan_alan_satirda_yok():
    rows = load().build_rows(
        data(
            flights=[flight(cancelled=True)],
            movements=[
                movement(
                    stand_code=None,
                    gate_code=None,
                    actual_runway_time=None,
                    actual_block_time=None,
                )
            ],
        )
    )

    row = rows[0]
    assert len(rows) == 1
    for name in ("stand_code", "gate_code", "stand_type", "max_code_letter"):
        assert name not in row
    for name in ("actual_runway_time", "actual_block_time"):
        assert name not in row
    assert row["cancelled"] == "true"


def test_status_cancelled_delayed_on_time():
    rows = load().build_rows(
        data(
            flights=[flight("F1", cancelled=True), flight("F2"), flight("F3")],
            movements=[movement("F1"), movement("F2"), movement("F3")],
            delays=[
                {
                    "flight_id": "F2",
                    "delay_minutes": 25,
                    "delay_code": "93",
                    "category": "REACTIONARY",
                }
            ],
        )
    )

    assert [row["status"] for row in rows] == ["cancelled", "delayed", "on_time"]
    delayed = rows[1]
    assert delayed["delay_minutes"] == 25
    assert delayed["delay_code"] == "93"
    assert delayed["delay_category"] == "REACTIONARY"
    assert "delay_minutes" not in rows[2]


def test_cancelled_metin_true_false():
    rows = load().build_rows(
        data(
            flights=[flight("F1", cancelled=True), flight("F2")],
            movements=[movement("F1"), movement("F2")],
        )
    )

    assert [row["cancelled"] for row in rows] == ["true", "false"]


def test_aircraft_ve_stand_birlesimi_eslesme_yoksa_alan_yok():
    rows = load().build_rows(
        data(
            flights=[flight("F1"), flight("F2", registration="TC-ZZZ")],
            movements=[movement("F1"), movement("F2", stand_code="X999")],
        )
    )

    first, second = rows
    assert (first["code_letter"], first["operator_iata"]) == ("C", "TK")
    assert (first["stand_type"], first["max_code_letter"]) == ("CONTACT", "C")
    for name in ("code_letter", "operator_iata", "stand_type", "max_code_letter"):
        assert name not in second
    assert second["stand_code"] == "X999"


@pytest.mark.parametrize(
    ("table", "drop"),
    [("flights", "cancelled"), ("movements", "movement_type"), ("delays", "delay_minutes")],
)
def test_zorunlu_alan_eksikse_veri_hatasi(table, drop):
    from backend.tools._ortak import DataError

    record = {
        "flights": flight(),
        "movements": movement(),
        "delays": {"flight_id": "F1", "delay_minutes": 5},
    }[table]
    del record[drop]

    with pytest.raises(DataError):
        load().build_rows(data(**{table: [record]}))


def test_referans_gunde_satir_sayisi_ve_havayolu_dagilimi():
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))

    rows = load().build_rows(reference)

    assert len(rows) == 600
    arrivals = Counter(row["airline"] for row in rows if row["movement_type"] == "ARRIVAL")
    ordered = sorted(arrivals.items(), key=lambda item: (-item[1], item[0]))
    assert ordered == [
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
