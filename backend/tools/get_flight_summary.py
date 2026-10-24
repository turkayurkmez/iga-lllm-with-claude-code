"""get_flight_summary: günün uçuşlarının sayısal özeti (docs/tools.md).

Sayılar her çağrıda COPILOT_DATA'dan hesaplanır. Tool zarfı kurmaz ve saati okumaz;
yalnızca {value, source} döndürür. Hesap için zorunlu alan eksikse DataError
fırlatır, zarfı run_tool kurar.
"""

from backend.tools._ortak import DataError, load_data

KEYS = ("meta", "flights", "movements", "delays")
# direction değerinin movements.movement_type karşılığı; None tümünü kapsar.
MOVEMENT_TYPES = {"all": None, "arrival": "ARRIVAL", "departure": "DEPARTURE"}


def _require(record: object, fields: tuple[str, ...], table: str) -> dict:
    if not isinstance(record, dict) or any(field not in record for field in fields):
        raise DataError(f"{table} kaydında zorunlu alan yok: {', '.join(fields)}")
    return record


def get_flight_summary(direction: str) -> dict:
    data, source = load_data(KEYS)

    meta = _require(data["meta"], ("date",), "meta")
    flights = [
        _require(f, ("flight_id", "cancelled"), "flights") for f in data["flights"]
    ]
    movements = [
        _require(m, ("flight_id", "movement_type"), "movements")
        for m in data["movements"]
    ]

    # Yetim kayıtlar sayılmaz: yalnızca flights'ta kaydı olan uçuşlar.
    known = {f["flight_id"] for f in flights}
    movement_type = MOVEMENT_TYPES[direction]
    selected = {
        m["flight_id"]
        for m in movements
        if m["flight_id"] in known
        and (movement_type is None or m["movement_type"] == movement_type)
    }
    cancelled = sum(
        1 for f in flights if f["flight_id"] in selected and f["cancelled"] is True
    )
    delayed = len(
        {d.get("flight_id") for d in data["delays"] if isinstance(d, dict)} & selected
    )

    value = {
        "date": meta["date"],
        "direction": direction,
        "total": len(selected),
        "cancelled": cancelled,
        "delayed": delayed,
    }
    return {"value": value, "source": source}
