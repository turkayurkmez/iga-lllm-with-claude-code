"""Grafik sorgusu için düz uçuş görünümü (spec: 2026-10-30-…-design.md › B).

Her uçuş için tek satır: flights + movements + delays + aircraft + stands
birleştirilir. Alan listesi bu dosyada tektir (FIELDS); kontrattaki enum'lar onunla
birebir aynı olmak zorundadır (tests/test_chart.py denetler). Kaynakta değeri olmayan
(None ya da boş) alan satırda hiç bulunmaz; değer uydurulmaz.
"""

from typing import Any, Literal, NamedTuple

from backend.tools._ortak import DataError

DATA_KEYS = ("meta", "flights", "movements", "delays", "aircraft", "stands")
AIRLINE_CODE_LENGTH = 2


class Field(NamedTuple):
    name: str
    kind: Literal["categorical", "time", "numeric"]


CATEGORICAL = (
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
TIME = (
    "scheduled_time",
    "estimated_time",
    "actual_runway_time",
    "actual_block_time",
)
NUMERIC = ("delay_minutes",)

FIELDS: dict[str, Field] = {
    **{name: Field(name, "categorical") for name in CATEGORICAL},
    **{name: Field(name, "time") for name in TIME},
    **{name: Field(name, "numeric") for name in NUMERIC},
}

# Satırdaki alan → kaynak tablo ve kaynaktaki alan adı.
FROM_FLIGHT = (
    "flight_no",
    "callsign",
    "registration",
    "aircraft_type",
    "origin",
    "destination",
    "scheduled_time",
    "estimated_time",
)
FROM_MOVEMENT = (
    "movement_type",
    "stand_code",
    "gate_code",
    "actual_runway_time",
    "actual_block_time",
)
FROM_AIRCRAFT = ("code_letter", "operator_iata")
FROM_STAND = ("stand_type", "max_code_letter")


def _require(record: object, fields: tuple[str, ...], table: str) -> dict:
    if not isinstance(record, dict) or any(field not in record for field in fields):
        raise DataError(f"{table} kaydında zorunlu alan yok: {', '.join(fields)}")
    return record


def _put(row: dict, name: str, value: Any) -> None:
    if value is not None and value != "":
        row[name] = value


def build_rows(data: dict) -> list[dict]:
    """Uçuş başına bir satır; hareketi olmayan uçuş ve yetim kayıtlar kullanılmaz."""
    flights = [
        _require(f, ("flight_id", "cancelled"), "flights") for f in data["flights"]
    ]
    known = {f["flight_id"] for f in flights}
    movements: dict[str, dict] = {}
    for movement in data["movements"]:
        _require(movement, ("flight_id", "movement_type"), "movements")
        if movement["flight_id"] in known:
            movements[movement["flight_id"]] = movement
    delays: dict[str, dict] = {}
    for delay in data["delays"]:
        _require(delay, ("flight_id", "delay_minutes"), "delays")
        if delay["flight_id"] in known:
            delays[delay["flight_id"]] = delay
    aircraft = {
        a["registration"]: a for a in data["aircraft"] if "registration" in a
    }
    stands = {s["stand_code"]: s for s in data["stands"] if "stand_code" in s}

    rows = []
    for flight in flights:
        movement = movements.get(flight["flight_id"])
        if movement is None:
            continue
        row: dict[str, Any] = {}
        for name in FROM_FLIGHT:
            _put(row, name, flight.get(name))
        flight_no = flight.get("flight_no")
        if isinstance(flight_no, str) and len(flight_no) >= AIRLINE_CODE_LENGTH:
            row["airline"] = flight_no[:AIRLINE_CODE_LENGTH].upper()
        for name in FROM_MOVEMENT:
            _put(row, name, movement.get(name))
        plane = aircraft.get(flight.get("registration"), {})
        for name in FROM_AIRCRAFT:
            _put(row, name, plane.get(name))
        stand = stands.get(movement.get("stand_code"), {})
        for name in FROM_STAND:
            _put(row, name, stand.get(name))
        delay = delays.get(flight["flight_id"])
        if delay is not None:
            _put(row, "delay_minutes", delay["delay_minutes"])
            _put(row, "delay_code", delay.get("delay_code"))
            _put(row, "delay_category", delay.get("category"))
        cancelled = flight["cancelled"] is True
        row["cancelled"] = "true" if cancelled else "false"
        row["status"] = (
            "cancelled" if cancelled else "delayed" if delay is not None else "on_time"
        )
        rows.append(row)
    return rows
