"""Sentetik veri üreteci sözleşme testleri (docs/spec.md §6–§10).

Testler üreteçten önce yazıldı; synth/generator.py yokken kırmızıdır. Üreteç yazılırken
bu testler gevşetilmez (spec §10).
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SEED = 42
OTHER_SEED = 43
DATE = "2026-10-20"
UTC_OFFSET = timedelta(hours=3)
LOCAL_AIRPORT = "XXXX"

TOP_LEVEL_KEYS = {
    "meta",
    "aircraft",
    "stands",
    "gates",
    "flights",
    "movements",
    "delays",
    "positions",
}

# §6 sütunları; flights.status üreteçten gelmez (§8).
FIELDS = {
    "aircraft": {"registration", "type_icao", "code_letter", "operator_iata"},
    "stands": {
        "stand_code",
        "stand_type",
        "max_code_letter",
        "mars",
        "status",
        "lat",
        "lon",
    },
    "gates": {"gate_code", "terminal", "pier", "stand_code"},
    "flights": {
        "flight_id",
        "flight_no",
        "callsign",
        "registration",
        "aircraft_type",
        "origin",
        "destination",
        "scheduled_time",
        "estimated_time",
        "cancelled",
    },
    "movements": {
        "flight_id",
        "movement_type",
        "stand_code",
        "gate_code",
        "actual_runway_time",
        "actual_block_time",
    },
    "positions": {"flight_id", "ts", "lat", "lon", "heading_deg", "speed_kt", "phase"},
    "delays": {"flight_id", "delay_minutes", "delay_code", "category"},
}

CODE_LETTERS = {"A", "B", "C", "D", "E", "F"}
PHASES = {"APPROACH", "TAXI_IN", "AT_STAND", "TAXI_OUT", "CLIMB"}
CATEGORIES = {
    "PASSENGER_BAGGAGE",
    "AIRCRAFT_TECHNICAL",
    "GROUND_HANDLING",
    "WEATHER",
    "ATC_RESTRICTION",
    "AIRPORT_FACILITIES",
    "REACTIONARY",
}
FLIGHT_ID_RE = re.compile(r"^FL-(\d{8})-(\d{4})$")
IATA_RE = re.compile(r"^[A-Z]{3}$")
DELAY_CODE_RE = re.compile(r"^\d{2}$")

# Özet satırında geçmesi gereken alanlar (§8).
SUMMARY_FIELDS = (
    "toplam",
    "arrival",
    "departure",
    "gecikmeli",
    "iptal",
    "uçak",
    "stand",
    "gate",
)

TRACK_LENGTH = timedelta(minutes=20)
TRACK_STEP = timedelta(seconds=30)


def run_generator(seed: int, day: str, out: Path, hash_seed: str = "0"):
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "synth.generator",
            "--seed",
            str(seed),
            "--date",
            day,
            "--out",
            str(out),
        ],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"Üreteç başarısız oldu:\n{result.stderr}"
    return result


@pytest.fixture(scope="module")
def generate(tmp_path_factory):
    """(seed, gün) başına üreteci bir kez çalıştırır; yol, stdout ve veriyi döndürür."""
    cache = {}

    def _generate(seed: int, day: str) -> dict:
        key = (seed, day)
        if key not in cache:
            # Var olmayan iç içe klasör: üretecin klasörü kendisinin oluşturması beklenir.
            out = (
                tmp_path_factory.mktemp("synth") / "yok" / "alt" / f"{seed}-{day}.json"
            )
            result = run_generator(seed, day, out)
            cache[key] = {
                "path": out,
                "stdout": result.stdout,
                "data": json.loads(out.read_text(encoding="utf-8")),
            }
        return cache[key]

    return _generate


@pytest.fixture(scope="module")
def output(generate):
    return generate(SEED, DATE)


@pytest.fixture(scope="module")
def data(output):
    return output["data"]


def parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    assert ts.tzinfo is not None, f"Zaman dilimsiz zaman damgası: {value}"
    return ts


def at(day: str, hour: int, minute: int) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00+03:00")


def seq_no(flight_id: str) -> int:
    match = FLIGHT_ID_RE.match(flight_id)
    assert match, f"Geçersiz flight_id: {flight_id}"
    return int(match.group(2))


def index(records: list[dict], key: str) -> dict:
    return {record[key]: record for record in records}


def pairs(data: dict) -> list[tuple[dict, dict]]:
    """Ardışık flight_id çiftleri: tek sıra no'lu arrival, ardından çift sıra no'lu departure."""
    flights = sorted(data["flights"], key=lambda f: f["flight_id"])
    assert len(flights) % 2 == 0, (
        "Uçuş sayısı çift olmalı; her arrival bir departure ile eşleşir."
    )
    return [(flights[i], flights[i + 1]) for i in range(0, len(flights), 2)]


def all_timestamps(data: dict):
    for flight in data["flights"]:
        yield flight["flight_id"], flight["scheduled_time"]
        yield flight["flight_id"], flight["estimated_time"]
    for movement in data["movements"]:
        for field in ("actual_runway_time", "actual_block_time"):
            if movement[field] is not None:
                yield movement["flight_id"], movement[field]
    for position in data["positions"]:
        yield position["flight_id"], position["ts"]


# ───────── 1–3: belirlenimcilik ve komut sözleşmesi ─────────


def test_ayni_seed_ayri_sureclerde_farkli_hash_seed_ile_birebir_ayni_dosya(tmp_path):
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    run_generator(SEED, DATE, first, hash_seed="0")
    run_generator(SEED, DATE, second, hash_seed="1")

    assert first.read_bytes() == second.read_bytes()


def test_farkli_seed_farkli_cikti(generate, output):
    other = generate(OTHER_SEED, DATE)

    assert other["path"].read_bytes() != output["path"].read_bytes()


def test_ozet_satiri_tek_satir_ve_tum_alanlari_icerir(output):
    lines = [line for line in output["stdout"].splitlines() if line.strip()]

    assert len(lines) == 1, f"Tek satır özet bekleniyordu:\n{output['stdout']}"
    # "İ".lower() birleşik nokta üretir; önce düz i'ye çevrilir.
    summary = lines[0].replace("İ", "i").lower()
    for field in SUMMARY_FIELDS:
        assert field in summary, f"Özet satırında '{field}' yok: {lines[0]}"


def test_cikti_klasoru_yoksa_olusturulur(output):
    assert output["path"].is_file()


def test_ust_anahtarlar_ve_alan_adlari_sozlesmeye_uyar(data):
    assert set(data) == TOP_LEVEL_KEYS
    for table, fields in FIELDS.items():
        for record in data[table]:
            assert set(record) == fields, (
                f"{table} alanları sözleşmeye uymuyor: {sorted(record)}"
            )


# ───────── 4: hacimler ─────────


def test_hacimler_spec_araliklarinda(data):
    movements = data["movements"]
    arrivals = [m for m in movements if m["movement_type"] == "ARRIVAL"]
    departures = [m for m in movements if m["movement_type"] == "DEPARTURE"]
    stands = data["stands"]
    gates = data["gates"]
    stand_by_code = index(stands, "stand_code")
    cancelled = [f for f in data["flights"] if f["cancelled"]]

    assert len(data["flights"]) == len(movements)
    assert 550 <= len(movements) <= 650
    assert 275 <= len(arrivals) <= 325
    assert 275 <= len(departures) <= 325
    assert len(data["aircraft"]) == 200

    assert len(stands) == 120
    assert sum(s["stand_type"] == "CONTACT" for s in stands) == 72
    assert sum(s["stand_type"] == "REMOTE" for s in stands) == 48
    assert sum(s["status"] == "UNAVAILABLE" for s in stands) >= 5

    assert len(gates) == 80
    linked = [g for g in gates if g["stand_code"] is not None]
    assert len(linked) == 72
    assert all(
        stand_by_code[g["stand_code"]]["stand_type"] == "CONTACT" for g in linked
    )
    assert sum(g["stand_code"] is None for g in gates) == 8

    assert 4 <= len(cancelled) <= 10


def test_gecikmeli_orani_ve_dakika_araligi(data):
    active = [f for f in data["flights"] if not f["cancelled"]]
    delays = data["delays"]

    ratio = len(delays) / len(active)
    assert 0.15 <= ratio <= 0.25, f"Gecikmeli oranı %15–25 dışında: {ratio:.3f}"
    assert all(15 <= d["delay_minutes"] <= 250 for d in delays)


def test_iptal_edilen_harekette_yerlesim_zaman_konum_ve_gecikme_yok(data):
    movements = index(data["movements"], "flight_id")
    delayed = {d["flight_id"] for d in data["delays"]}
    tracked = {p["flight_id"] for p in data["positions"]}

    for flight in data["flights"]:
        if not flight["cancelled"]:
            continue
        flight_id = flight["flight_id"]
        movement = movements[flight_id]
        assert movement["stand_code"] is None, flight_id
        assert movement["gate_code"] is None, flight_id
        assert movement["actual_runway_time"] is None, flight_id
        assert movement["actual_block_time"] is None, flight_id
        assert flight_id not in tracked, flight_id
        assert flight_id not in delayed, flight_id


def test_iptal_edilmeyen_her_hareketin_20_dakikalik_30_saniyelik_izi_var(data):
    movements = index(data["movements"], "flight_id")
    tracks = defaultdict(list)
    for position in data["positions"]:
        tracks[position["flight_id"]].append(parse_ts(position["ts"]))

    for flight in data["flights"]:
        if flight["cancelled"]:
            continue
        flight_id = flight["flight_id"]
        track = sorted(tracks[flight_id])
        assert track, f"{flight_id} için konum izi yok"
        assert track[-1] - track[0] == TRACK_LENGTH, flight_id
        steps = {b - a for a, b in pairwise(track)}
        assert steps == {TRACK_STEP}, flight_id

        movement = movements[flight_id]
        block = parse_ts(movement["actual_block_time"])
        if movement["movement_type"] == "ARRIVAL":
            assert track[-1] == block, f"{flight_id} arrival izi on-block'ta bitmeli"
        else:
            assert track[0] == block, (
                f"{flight_id} departure izi off-block'ta başlamalı"
            )


# ───────── 5: referans bütünlüğü ve kod listeleri ─────────


def test_referans_butunlugu_ve_kod_listeleri(data):
    aircraft = index(data["aircraft"], "registration")
    stands = index(data["stands"], "stand_code")
    gates = index(data["gates"], "gate_code")
    flights = index(data["flights"], "flight_id")
    movements = index(data["movements"], "flight_id")
    day = DATE.replace("-", "")

    # Birincil anahtarlar tekil.
    assert len(aircraft) == len(data["aircraft"])
    assert len(stands) == len(data["stands"])
    assert len(gates) == len(data["gates"])
    assert len(flights) == len(data["flights"])
    assert len(movements) == len(data["movements"])
    assert len(index(data["delays"], "flight_id")) == len(data["delays"])
    position_keys = {(p["flight_id"], p["ts"]) for p in data["positions"]}
    assert len(position_keys) == len(data["positions"])

    for record in data["aircraft"]:
        assert record["code_letter"] in CODE_LETTERS
    for record in data["stands"]:
        assert record["stand_type"] in {"CONTACT", "REMOTE"}
        assert record["max_code_letter"] in CODE_LETTERS
        assert record["status"] in {"AVAILABLE", "UNAVAILABLE"}
        assert isinstance(record["mars"], bool)
    for record in data["gates"]:
        assert record["stand_code"] is None or record["stand_code"] in stands

    for flight_id, flight in flights.items():
        match = FLIGHT_ID_RE.match(flight_id)
        assert match, flight_id
        assert match.group(1) == day, flight_id
        assert flight["registration"] in aircraft, flight_id
        assert isinstance(flight["cancelled"], bool), flight_id
        assert flight_id in movements, f"{flight_id} için hareket kaydı yok"

    for flight_id, movement in movements.items():
        assert flight_id in flights, flight_id
        flight = flights[flight_id]
        assert movement["movement_type"] in {"ARRIVAL", "DEPARTURE"}
        if movement["movement_type"] == "ARRIVAL":
            assert flight["destination"] == LOCAL_AIRPORT, flight_id
            assert IATA_RE.match(flight["origin"]), flight_id
        else:
            assert flight["origin"] == LOCAL_AIRPORT, flight_id
            assert IATA_RE.match(flight["destination"]), flight_id
        if movement["stand_code"] is not None:
            assert movement["stand_code"] in stands, flight_id
        if movement["gate_code"] is not None:
            assert movement["gate_code"] in gates, flight_id

        if flight["cancelled"]:
            continue
        stand = stands.get(movement["stand_code"])
        assert stand is not None, f"{flight_id} için stand atanmamış"
        assert stand["status"] == "AVAILABLE", flight_id
        letter = aircraft[flight["registration"]]["code_letter"]
        assert letter <= stand["max_code_letter"], f"{flight_id}: {letter} uçak {stand}"
        assert movement["gate_code"] in gates, f"{flight_id} için gate atanmamış"

    for delay in data["delays"]:
        assert delay["flight_id"] in flights
        assert not flights[delay["flight_id"]]["cancelled"]
        assert delay["delay_minutes"] >= 15
        assert DELAY_CODE_RE.match(delay["delay_code"]), delay
        assert delay["category"] in CATEGORIES

    for position in data["positions"]:
        assert position["flight_id"] in flights
        assert position["phase"] in PHASES


# ───────── 6: zamanlar ve çiftler ─────────


def test_tum_zaman_damgalari_verilen_gunde_ve_utc_arti_3(data):
    day = date.fromisoformat(DATE)
    for flight_id, value in all_timestamps(data):
        ts = parse_ts(value)
        assert ts.utcoffset() == UTC_OFFSET, f"{flight_id}: {value}"
        assert ts.date() == day, f"{flight_id}: {value}"


def test_tahmini_zaman_gecikme_kadar_sonra_gecikmesizde_tarifeye_esit(data):
    delays = index(data["delays"], "flight_id")
    for flight in data["flights"]:
        scheduled = parse_ts(flight["scheduled_time"])
        estimated = parse_ts(flight["estimated_time"])
        delay = delays.get(flight["flight_id"])
        expected = timedelta(minutes=delay["delay_minutes"]) if delay else timedelta(0)
        assert estimated - scheduled == expected, flight["flight_id"]


def test_iptal_edilmeyen_harekette_block_zamani_var(data):
    flights = index(data["flights"], "flight_id")
    for movement in data["movements"]:
        if not flights[movement["flight_id"]]["cancelled"]:
            assert movement["actual_block_time"] is not None, movement["flight_id"]


def test_her_arrival_ayni_ucagin_departure_i_ile_cift_ve_departure_sonra(data):
    movements = index(data["movements"], "flight_id")
    for arrival, departure in pairs(data):
        arr_id, dep_id = arrival["flight_id"], departure["flight_id"]
        assert seq_no(arr_id) % 2 == 1, arr_id
        assert seq_no(dep_id) == seq_no(arr_id) + 1, dep_id
        assert movements[arr_id]["movement_type"] == "ARRIVAL", arr_id
        assert movements[dep_id]["movement_type"] == "DEPARTURE", dep_id
        assert arrival["registration"] == departure["registration"], arr_id

        if arrival["cancelled"] or departure["cancelled"]:
            continue
        on_block = parse_ts(movements[arr_id]["actual_block_time"])
        off_block = parse_ts(movements[dep_id]["actual_block_time"])
        assert off_block > on_block, (
            f"{dep_id} departure, {arr_id} arrival'dan sonra olmalı"
        )


# ───────── 7: yer işgali ─────────


def test_ayni_ucak_ve_ayni_stand_icin_isgal_araliklari_cakismaz(data):
    movements = index(data["movements"], "flight_id")
    by_aircraft = defaultdict(list)
    by_stand = defaultdict(list)

    for arrival, departure in pairs(data):
        if arrival["cancelled"] or departure["cancelled"]:
            continue
        arr_movement = movements[arrival["flight_id"]]
        interval = (
            parse_ts(arr_movement["actual_block_time"]),
            parse_ts(movements[departure["flight_id"]]["actual_block_time"]),
            arrival["flight_id"],
        )
        by_aircraft[arrival["registration"]].append(interval)
        by_stand[arr_movement["stand_code"]].append(interval)

    for group_name, groups in (("uçak", by_aircraft), ("stand", by_stand)):
        for key, intervals in groups.items():
            intervals.sort()
            for (_, prev_end, prev_id), (start, _, cur_id) in pairwise(intervals):
                assert start >= prev_end, (
                    f"{group_name} {key}: {prev_id} ile {cur_id} çakışıyor"
                )


# ───────── 8: en çok gecikenler ─────────


def test_en_cok_geciken_alti_hareketin_dakikalari_farkli(data):
    top = sorted((d["delay_minutes"] for d in data["delays"]), reverse=True)[:6]

    assert len(top) == 6
    assert len(set(top)) == 6, f"En çok geciken altı harekette eşit dakika var: {top}"


# ───────── 9: sabit kayıtlar ─────────


def assert_pinned_records(data: dict, day: str) -> None:
    aircraft = index(data["aircraft"], "registration")
    movements = index(data["movements"], "flight_id")
    delays = index(data["delays"], "flight_id")

    assert aircraft.get("TC-LSD") == {
        "registration": "TC-LSD",
        "type_icao": "A321",
        "code_letter": "C",
        "operator_iata": "TK",
    }

    arrivals = [f for f in data["flights"] if f["flight_no"] == "TK2344"]
    assert len(arrivals) == 1
    arrival = arrivals[0]
    assert movements[arrival["flight_id"]]["movement_type"] == "ARRIVAL"
    assert parse_ts(arrival["scheduled_time"]) == at(day, 13, 5)

    departures = [f for f in data["flights"] if f["flight_no"] == "TK2345"]
    assert len(departures) == 1
    departure = departures[0]
    flight_id = departure["flight_id"]
    movement = movements[flight_id]
    assert movement["movement_type"] == "DEPARTURE"
    assert departure["callsign"] == "THY2345"
    assert departure["registration"] == "TC-LSD"
    assert departure["cancelled"] is False
    assert parse_ts(departure["scheduled_time"]) == at(day, 15, 40)
    assert parse_ts(departure["estimated_time"]) == at(day, 16, 5)
    assert flight_id in delays
    assert delays[flight_id]["delay_minutes"] == 25
    assert movement["stand_code"] is not None
    assert movement["gate_code"] is not None
    assert any(p["flight_id"] == flight_id for p in data["positions"])

    for flight in data["flights"]:
        assert flight["flight_no"] != "ZZ9999", flight["flight_id"]
        assert flight["callsign"] != "ZZ9999", flight["flight_id"]


def test_sabit_kayitlar_var_zz9999_yok(data):
    assert_pinned_records(data, DATE)


@pytest.mark.parametrize(
    ("seed", "day"),
    [
        (0, "2028-02-29"),  # artık gün
        (999999, "2026-12-31"),  # yıl sonu, büyük seed
        (2026, "2027-01-01"),  # yıl başı
    ],
)
def test_sabit_kayitlar_baska_seed_ve_tarihte_de_ayni(generate, seed, day):
    assert_pinned_records(generate(seed, day)["data"], day)


# ───────── 10: bağımlılık ─────────


def test_pytest_requirements_te_sabitlenmis():
    lines = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert "pytest==9.1.1" in [line.strip() for line in lines]
