"""focus_map_object ve highlight_map_set: harita komutları (sözleşme: docs/harita.md).

İki tool da operasyonel veri değil, girişin doğrulanmış kopyası olan bir komut
döndürür. Doğrulama iki yerdedir: kimlik biçimi object_type'a göre `check_*` ile
(argüman doğrulamasına eklenir, ihlal SCHEMA_VALIDATION_FAILED olur), nesnenin
haritada var olması tool gövdesinde. Uçuş, canlı depoda görünür konumu varsa;
stand, COPILOT_DATA'daki `stands` listesinde varsa vardır. Tool zarfı kurmaz ve
sistem saatini doğrudan okumaz.
"""

import re

from backend import clock, live
from backend.envelope import ErrorCode
from backend.tools._ortak import DataError, load_data

# Kimlik biçimleri (docs/harita.md › Kimlik biçimi). [0-9] ve fullmatch: `\d` Unicode
# rakamları, `$` sondaki satır sonunu kabul eder; sözleşme ikisini de reddeder.
ID_PATTERNS = {
    "flight": re.compile(r"[A-Z]{2}[0-9]{3,4}"),
    "stand": re.compile(r"[A-Z][0-9]{3}"),
}
MAX_IDS = 50

NOT_FOUND = {
    "code": ErrorCode.NOT_FOUND,
    "message": "Haritada bu nesne için konum yok.",
}


def _id_error(object_type: str, ids: list) -> str | None:
    pattern = ID_PATTERNS[object_type]
    for object_id in ids:
        if not pattern.fullmatch(object_id):
            return f"Kimlik {object_type} biçimine uymuyor."
    return None


def check_focus(args: dict) -> str | None:
    """Şemanın ötesi: id, object_type'ın biçimine uymalı."""
    return _id_error(args["object_type"], [args["id"]])


def check_highlight(args: dict) -> str | None:
    """Şemanın ötesi: biçim object_type'a göre, 1-50 eleman, tekrarsız."""
    ids = args["ids"]
    if not 1 <= len(ids) <= MAX_IDS:
        return f"ids {MAX_IDS} elemanı aşamaz ve boş olamaz."
    if len(set(ids)) != len(ids):
        return "ids tekrar içeremez."
    return _id_error(args["object_type"], ids)


def _stand_codes(data: dict) -> set[str]:
    stands = data["stands"]
    if not isinstance(stands, list):
        raise DataError("stands bir liste değil.")
    codes = set()
    for stand in stands:
        if not isinstance(stand, dict) or not isinstance(stand.get("stand_code"), str):
            raise DataError("stands kaydında zorunlu alan yok: stand_code")
        codes.add(stand["stand_code"])
    return codes


def _visible_flights(hub: live.LiveHub, flight_nos: list[str]) -> set[str]:
    """Canlı depoda LastUpdate ≤ operasyonel saat olan kaydı bulunan sefer numaraları."""
    now = clock.operational_now().timestamp()
    return {
        flight_no
        for flight_no in flight_nos
        if any(
            record["LastUpdate"] <= now
            for record in hub.positions_for_flight(flight_no)
        )
    }


def _exists(object_type: str, ids: list[str]) -> tuple[bool, str]:
    """Kimliklerin hepsi haritada mı; (var_mı, source). Veri her çağrıda okunur."""
    if object_type == "stand":
        data, source = load_data(("stands",))
        return set(ids) <= _stand_codes(data), source
    # Uçuş denetimi dosyadan değil depodan yapılır; dosya yalnızca source içindir.
    _, source = load_data(())
    hub = live.active()
    if hub is None:
        return False, source
    return set(ids) <= _visible_flights(hub, ids), source


def focus_map_object(object_type: str, id: str) -> dict:
    found, source = _exists(object_type, [id])
    if not found:
        return {"value": None, "source": source, "error": NOT_FOUND}
    value = {"command": "focus_map_object", "object_type": object_type, "id": id}
    return {"value": value, "source": source}


def highlight_map_set(object_type: str, ids: list[str]) -> dict:
    found, source = _exists(object_type, ids)
    if not found:
        return {"value": None, "source": source, "error": NOT_FOUND}
    value = {"command": "highlight_map_set", "object_type": object_type, "ids": ids}
    return {"value": value, "source": source}
