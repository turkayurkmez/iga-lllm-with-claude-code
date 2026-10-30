"""get_chart_data: uçuşları bir boyuta göre gruplayıp ölçen grafik verisi (docs/tools.md).

Sayılar her çağrıda COPILOT_DATA'dan hesaplanır. Tool zarfı kurmaz ve saati okumaz;
yalnızca {value, source} döndürür. Model grafiğin tarifini (boyut, ölçü, süzgeç)
verir, seriyi bu modül hesaplar. Hesap için zorunlu alan eksikse DataError fırlatır,
zarfı run_tool kurar.
"""

from collections import defaultdict

from backend.tools._ortak import DataError, load_data

KEYS = ("meta", "flights", "movements", "delays")
MOVEMENT_TYPES = {"all": None, "arrival": "ARRIVAL", "departure": "DEPARTURE"}
AIRLINE_CODE_LENGTH = 2
# scheduled_time "2026-10-20T15:40:00+03:00" biçimindedir; saat dilimi 11:13.
HOUR_SLICE = slice(11, 13)
STATUS_ORDER = ("cancelled", "delayed", "on_time")
ORDERED_BY_LABEL = ("hour", "status")


def check_chart(args: dict) -> str | None:
    """Şemanın anlatamadığı kural: çizgi grafik yalnızca saat boyutuyla anlamlıdır."""
    if args.get("chart_type") == "line" and args.get("group_by") != "hour":
        return "line grafik yalnızca group_by hour ile kullanılır."
    return None


def _require(record: object, fields: tuple[str, ...], table: str) -> dict:
    if not isinstance(record, dict) or any(field not in record for field in fields):
        raise DataError(f"{table} kaydında zorunlu alan yok: {', '.join(fields)}")
    return record


def _label(group_by: str, flight: dict, movement: dict, delayed: bool) -> str | None:
    """Uçuşun gruplama etiketi; boyut kayıtta yoksa None (gruba girmez)."""
    if group_by == "airline":
        flight_no = flight.get("flight_no")
        if not isinstance(flight_no, str) or len(flight_no) < AIRLINE_CODE_LENGTH:
            return None
        return flight_no[:AIRLINE_CODE_LENGTH].upper()
    if group_by == "hour":
        scheduled = flight.get("scheduled_time")
        return scheduled[HOUR_SLICE] if isinstance(scheduled, str) else None
    if group_by == "status":
        if flight["cancelled"] is True:
            return "cancelled"
        return "delayed" if delayed else "on_time"
    source = movement if group_by in ("stand", "gate") else flight
    field = {"stand": "stand_code", "gate": "gate_code"}.get(group_by, group_by)
    label = source.get(field)
    return label if isinstance(label, str) and label else None


def get_chart_data(
    chart_type: str,
    group_by: str,
    metric: str = "count",
    direction: str = "all",
    include_cancelled: bool = True,
    limit: int = 10,
) -> dict:
    data, source = load_data(KEYS)

    meta = _require(data["meta"], ("date",), "meta")
    flights = {
        f["flight_id"]: f
        for f in (
            _require(f, ("flight_id", "cancelled"), "flights") for f in data["flights"]
        )
    }
    movement_type = MOVEMENT_TYPES[direction]
    # Uçuş başına tek hareket; yetim kayıtlar sayılmaz.
    movements = {}
    for movement in data["movements"]:
        _require(movement, ("flight_id", "movement_type"), "movements")
        if movement["flight_id"] in flights and (
            movement_type is None or movement["movement_type"] == movement_type
        ):
            movements[movement["flight_id"]] = movement
    delay_minutes: dict[str, int] = {}
    for delay in data["delays"]:
        _require(delay, ("flight_id", "delay_minutes"), "delays")
        delay_minutes[delay["flight_id"]] = delay["delay_minutes"]

    scope = [
        flight_id
        for flight_id in movements
        if include_cancelled or flights[flight_id]["cancelled"] is not True
    ]

    groups: dict[str, list[int]] = defaultdict(list)
    unclassified = 0
    for flight_id in scope:
        label = _label(
            group_by,
            flights[flight_id],
            movements[flight_id],
            flight_id in delay_minutes,
        )
        if label is None:
            unclassified += 1
        elif metric == "count":
            groups[label].append(1)
        elif flight_id in delay_minutes:
            groups[label].append(delay_minutes[flight_id])

    if metric == "total_delay_minutes":
        values = {label: sum(parts) for label, parts in groups.items()}
    elif metric == "avg_delay_minutes":
        values = {
            label: round(sum(parts) / len(parts), 1) for label, parts in groups.items()
        }
    else:
        values = {label: len(parts) for label, parts in groups.items()}

    if group_by == "status":
        ordered = sorted(values.items(), key=lambda item: STATUS_ORDER.index(item[0]))
    elif group_by in ORDERED_BY_LABEL:
        ordered = sorted(values.items())
    else:
        ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    shown = ordered if group_by in ORDERED_BY_LABEL else ordered[:limit]

    value = {
        "date": meta["date"],
        "chart_type": chart_type,
        "group_by": group_by,
        "metric": metric,
        "flights": len(scope),
        "groups_total": len(ordered),
        "unclassified": unclassified,
        "items": [{"label": label, "value": number} for label, number in shown],
    }
    return {"value": value, "source": source}
