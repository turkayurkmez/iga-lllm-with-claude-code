"""Golden set hesap adları (docs/eval.md › Hesap adları).

Beklenen değerler yüklenmiş veri sözlüğünden (spec §8 biçimi) hesaplanır. Tanımlar
docs/tools.md'deki tool hesaplarıyla aynı anlamdadır ama backend/'den bağımsız
yazılmıştır: aynı kodla hesaplanan beklenen değer tool hatasını gizler. Dosya
okunmaz, sistem saati okunmaz, veri değiştirilmez.
"""

import re
from collections import Counter
from datetime import datetime


class ExpectedError(ValueError):
    """Hesap değer üretemedi; golden set hatasıdır (docs/eval.md › Boş sonuç)."""


DIRECTIONS = {"all": None, "arrival": "ARRIVAL", "departure": "DEPARTURE"}

# field → (tablo, kaynak alan)
FLIGHT_FIELDS = {
    "scheduled_time": ("flights", "scheduled_time"),
    "estimated_time": ("flights", "estimated_time"),
    "registration": ("flights", "registration"),
    "callsign": ("flights", "callsign"),
    "aircraft_type": ("flights", "aircraft_type"),
    "origin": ("flights", "origin"),
    "destination": ("flights", "destination"),
    "stand_code": ("movements", "stand_code"),
    "gate_code": ("movements", "gate_code"),
    "actual_block_time": ("movements", "actual_block_time"),
    "actual_runway_time": ("movements", "actual_runway_time"),
    "delay_minutes": ("delays", "delay_minutes"),
    "delay_code": ("delays", "delay_code"),
    "delay_category": ("delays", "category"),
}
CANDIDATE_FIELDS = {"flight_no": ("flights", "flight_no"), **FLIGHT_FIELDS}
POSITION_FIELDS = ("ts", "lat", "lon", "phase")

# Harf öneki + rakam: baştaki sıfırlar yok sayılır, en az bir rakam kalır.
_NUMBERED = re.compile(r"([A-Z]+)0*(\d+)")


def compute(ref, base, data, now):
    """Değer referansını çözer: ref = {"calc", "params", "on"?}.

    on "eval" (varsayılan) ise data, "base" ise base kullanılır. now saat dilimli
    datetime ya da None'dır; yalnızca position.last kullanır.
    """
    name = ref.get("calc")
    if name not in _CALCS:
        raise ExpectedError(f"Bilinmeyen hesap adı: {name}.")
    on = ref.get("on", "eval")
    if on not in ("eval", "base"):
        raise ExpectedError(f"Bilinmeyen veri seçimi: {on}.")
    func, param_names = _CALCS[name]
    params = ref.get("params", {})
    if set(params) != set(param_names):
        expected = ", ".join(param_names) or "yok"
        raise ExpectedError(f"{name} parametreleri: {expected}.")
    source = base if on == "base" else data
    return func(source, now, **params)


def _rows(source, key):
    rows = source.get(key)
    if not isinstance(rows, list):
        raise ExpectedError(f"Veride {key} yok.")
    return rows


def _selected_ids(source, direction):
    """flights'ta kaydı olan ve yönü eşleşen uçuşlar; yetim kayıtlar hariç."""
    if direction not in DIRECTIONS:
        raise ExpectedError(f"Bilinmeyen yön: {direction}.")
    wanted = DIRECTIONS[direction]
    known = {row["flight_id"] for row in _rows(source, "flights")}
    return {
        row["flight_id"]
        for row in _rows(source, "movements")
        if row["flight_id"] in known
        and (wanted is None or row.get("movement_type") == wanted)
    }


def _summary_total(source, now, direction):
    return len(_selected_ids(source, direction))


def _summary_cancelled(source, now, direction):
    selected = _selected_ids(source, direction)
    return sum(
        1
        for row in _rows(source, "flights")
        if row["flight_id"] in selected and row.get("cancelled") is True
    )


def _summary_delayed(source, now, direction):
    selected = _selected_ids(source, direction)
    return len({row["flight_id"] for row in _rows(source, "delays")} & selected)


def _summary_not_cancelled(source, now, direction):
    total = _summary_total(source, now, direction)
    return total - _summary_cancelled(source, now, direction)


def _unique_flight(source, flight_no):
    matches = [r for r in _rows(source, "flights") if r.get("flight_no") == flight_no]
    if len(matches) != 1:
        raise ExpectedError(f"{flight_no} için {len(matches)} uçuş var, 1 bekleniyor.")
    return matches[0]


def _field_value(source, flight, field, fields):
    if field not in fields:
        raise ExpectedError(f"Bilinmeyen alan: {field}.")
    table, key = fields[field]
    if table == "flights":
        row = flight
    else:
        row = next(
            (r for r in _rows(source, table) if r["flight_id"] == flight["flight_id"]),
            {},
        )
    value = row.get(key)
    if value is None:
        raise ExpectedError(f"{flight['flight_id']} kaydında {field} yok.")
    return value


def _flight_field(source, now, flight_no, field):
    flight = _unique_flight(source, flight_no)
    return _field_value(source, flight, field, FLIGHT_FIELDS)


def _numbered(value):
    match = _NUMBERED.fullmatch(value)
    return match.group(1) + match.group(2) if match else value


def _matches(flight, query):
    """docs/tools.md › resolve_flight_identity › Eşleşme kuralı."""
    wanted = query.strip().upper()
    for key in ("flight_no", "callsign"):
        value = flight.get(key)
        if value is not None and _numbered(value.upper()) == _numbered(wanted):
            return True
    registration = flight.get("registration")
    return registration is not None and registration.upper() == wanted


def _identity_candidates(source, now, query, field):
    flights = sorted(
        (r for r in _rows(source, "flights") if _matches(r, query)),
        key=lambda r: r["flight_id"],
    )
    if len(flights) < 2:
        raise ExpectedError(
            f"{query} için {len(flights)} aday var, en az 2 bekleniyor."
        )
    return [_field_value(source, f, field, CANDIDATE_FIELDS) for f in flights]


def _track(source, flight_no):
    flight_id = _unique_flight(source, flight_no)["flight_id"]
    return [
        (datetime.fromisoformat(row["ts"]), row)
        for row in _rows(source, "positions")
        if row["flight_id"] == flight_id
    ]


def _position_last(source, now, flight_no, field):
    if field not in POSITION_FIELDS:
        raise ExpectedError(f"Bilinmeyen konum alanı: {field}.")
    if now is None or now.tzinfo is None:
        raise ExpectedError("position.last saat dilimli bir now ister.")
    past = [(ts, row) for ts, row in _track(source, flight_no) if ts <= now]
    if not past:
        raise ExpectedError(f"{flight_no} için {now.isoformat()} öncesinde konum yok.")
    value = max(past, key=lambda item: item[0])[1].get(field)
    if value is None:
        raise ExpectedError(f"{flight_no} son konumunda {field} yok.")
    return value


def _position_track_end(source, now, flight_no):
    track = _track(source, flight_no)
    if not track:
        raise ExpectedError(f"{flight_no} için konum izi yok.")
    return max(track, key=lambda item: item[0])[1]["ts"]


def _flights_pick(source, now, cancelled):
    if not isinstance(cancelled, bool):
        raise ExpectedError("flights.pick › cancelled mantıksal olmalı.")
    flights = sorted(_rows(source, "flights"), key=lambda r: r["flight_id"])
    counts = Counter(r.get("flight_no") for r in flights)
    for row in flights:
        flight_no = row.get("flight_no")
        if (
            flight_no is not None
            and counts[flight_no] == 1
            and row.get("cancelled") is cancelled
        ):
            return flight_no
    raise ExpectedError("Uygun tekil sefer no'lu uçuş yok.")


def _stands_codes(source, now):
    codes = [row["stand_code"] for row in _rows(source, "stands")]
    if not codes:
        raise ExpectedError("Veride stand yok.")
    return codes


_CALCS = {
    "summary.total": (_summary_total, ("direction",)),
    "summary.cancelled": (_summary_cancelled, ("direction",)),
    "summary.delayed": (_summary_delayed, ("direction",)),
    "summary.not_cancelled": (_summary_not_cancelled, ("direction",)),
    "flight.field": (_flight_field, ("flight_no", "field")),
    "identity.candidates": (_identity_candidates, ("query", "field")),
    "position.last": (_position_last, ("flight_no", "field")),
    "position.track_end": (_position_track_end, ("flight_no",)),
    "flights.pick": (_flights_pick, ("cancelled",)),
    "stands.codes": (_stands_codes, ()),
}
CALC_NAMES = tuple(_CALCS)
