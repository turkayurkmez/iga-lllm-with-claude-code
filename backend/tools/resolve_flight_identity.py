"""resolve_flight_identity: sefer no, callsign ya da tescili uçuş kaydına çevirir.

Sözleşme docs/tools.md'dedir. Eşleşme büyük/küçük harf duyarsız tam eşitliktir;
sefer no ve callsign'da sayı kısmının başındaki sıfırlar yok sayılır (THY15 =
THY0015). Tool zarfı kurmaz ve saati okumaz; {value, source, error?} döndürür.
"""

import re

from backend.envelope import ErrorCode
from backend.tools._ortak import DataError, load_data

KEYS = ("flights", "movements")
# Öncelik sırası: aynı kayıt birden fazla alanda eşleşirse ilk alan matched_on olur.
MATCH_FIELDS = ("flight_no", "callsign", "registration")
CANDIDATE_FIELDS = ("flight_id", "flight_no", "callsign", "registration")
# Harf öneki + rakamlar; rakamların başındaki sıfırlar atılır, en az bir rakam kalır.
NUMBERED = re.compile(r"^([A-Z]+)0*(\d+)$")

NOT_FOUND = {
    "code": ErrorCode.NOT_FOUND,
    "message": "Bu kimlikle uçuş bulunamadı.",
}
AMBIGUOUS = {
    "code": ErrorCode.AMBIGUOUS_ENTITY,
    "message": "Bu kimlik birden fazla uçuşla eşleşiyor.",
}


def _normalize(text: str, field: str) -> str:
    normalized = text.strip().upper()
    if field != "registration":
        match = NUMBERED.match(normalized)
        if match:
            normalized = match[1] + match[2]
    return normalized


def _matched_on(flight: dict, query: str) -> str | None:
    for field in MATCH_FIELDS:
        value = flight.get(field)
        if isinstance(value, str) and _normalize(value, field) == _normalize(
            query, field
        ):
            return field
    return None


def resolve_flight_identity(query: str) -> dict:
    data, source = load_data(KEYS)

    flights = data["flights"]
    for flight in flights:
        if not isinstance(flight, dict) or "flight_id" not in flight:
            raise DataError("flights kaydında zorunlu alan yok: flight_id")
    movement_types = {
        m["flight_id"]: m.get("movement_type")
        for m in data["movements"]
        if isinstance(m, dict) and "flight_id" in m
    }

    candidates = []
    for flight in flights:
        matched_on = _matched_on(flight, query)
        if matched_on is None:
            continue
        # Kaynakta olmayan ya da null olan alan adaya yazılmaz (docs/tools.md).
        candidate = {
            field: flight[field]
            for field in CANDIDATE_FIELDS
            if flight.get(field) is not None
        }
        movement_type = movement_types.get(flight["flight_id"])
        if movement_type is not None:
            candidate["movement_type"] = movement_type
        if flight.get("scheduled_time") is not None:
            candidate["scheduled_time"] = flight["scheduled_time"]
        candidate["matched_on"] = matched_on
        candidates.append(candidate)
    candidates.sort(key=lambda c: c["flight_id"])

    if not candidates:
        return {"value": None, "source": source, "error": NOT_FOUND}
    if len(candidates) > 1:
        return {"value": candidates, "source": source, "error": AMBIGUOUS}
    return {"value": candidates[0], "source": source}
