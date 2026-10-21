"""get_flight_details: tek uçuşun kaydı, hareketi, gecikmesi ve son konumu.

Sözleşme docs/tools.md'dedir. Uçuş flight_id ile tam eşitlikle aranır. Konum,
ts'si backend.clock.now()'a eşit ya da ondan önce olan kayıtların sonuncusudur.
Tool zarfı kurmaz ve sistem saatini doğrudan okumaz; {value, source, error?}
döndürür.
"""

from datetime import datetime

from backend import clock
from backend.envelope import ErrorCode
from backend.tools._ortak import DataError, load_data

KEYS = ("flights", "movements", "delays", "positions")
# flights.status üreteçten gelmez, döndürülmez (docs/spec.md §6).
FLIGHT_FIELDS = (
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
)
MOVEMENT_FIELDS = (
    "movement_type",
    "stand_code",
    "gate_code",
    "actual_runway_time",
    "actual_block_time",
)
# delays alanı → value alanı; category ad çakışmasın diye önekli.
DELAY_FIELDS = {
    "delay_minutes": "delay_minutes",
    "delay_code": "delay_code",
    "category": "delay_category",
}
POSITION_FIELDS = ("ts", "lat", "lon", "heading_deg", "speed_kt", "phase")

NOT_FOUND = {
    "code": ErrorCode.NOT_FOUND,
    "message": "Bu kimlikle uçuş bulunamadı.",
}


def _records(data: dict, table: str) -> list[dict]:
    records = data[table]
    for record in records:
        if not isinstance(record, dict) or "flight_id" not in record:
            raise DataError(f"{table} kaydında zorunlu alan yok: flight_id")
    return records


def _first(records: list[dict], flight_id: str) -> dict:
    return next((r for r in records if r["flight_id"] == flight_id), {})


def _copy(record: dict, fields) -> dict:
    # Kaynakta olmayan ya da null olan alan value'ya yazılmaz (docs/tools.md).
    return {
        target: record[source]
        for source, target in fields
        if record.get(source) is not None
    }


def _timestamp(raw: object) -> datetime:
    try:
        ts = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as exc:
        raise DataError("positions kaydında ts geçersiz.") from exc
    if ts.utcoffset() is None:
        raise DataError("positions kaydında ts saat dilimsiz.")
    return ts


def _last_position(positions: list[dict], flight_id: str) -> dict | None:
    now = clock.now()
    latest = None
    latest_ts = None
    for record in positions:
        if record["flight_id"] != flight_id:
            continue
        if "ts" not in record:
            raise DataError("positions kaydında zorunlu alan yok: ts")
        ts = _timestamp(record["ts"])
        if ts <= now and (latest_ts is None or ts > latest_ts):
            latest, latest_ts = record, ts
    return latest


def get_flight_details(flight_id: str) -> dict:
    data, source = load_data(KEYS)

    flights = _records(data, "flights")
    movements = _records(data, "movements")
    delays = _records(data, "delays")
    positions = _records(data, "positions")

    flight = _first(flights, flight_id)
    if not flight:
        # Yetim movements/delays/positions kayıtlarına bakılmaz.
        return {"value": None, "source": source, "error": NOT_FOUND}

    value = _copy(flight, ((f, f) for f in FLIGHT_FIELDS))
    value |= _copy(_first(movements, flight_id), ((f, f) for f in MOVEMENT_FIELDS))
    value |= _copy(_first(delays, flight_id), DELAY_FIELDS.items())
    position = _last_position(positions, flight_id)
    if position is not None:
        value["position"] = _copy(position, ((f, f) for f in POSITION_FIELDS))
    return {"value": value, "source": source}
