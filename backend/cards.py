"""Tool zarfından /chat olayları: source_chip, kpi_card, selection_card, map_command.

Sözleşme docs/chat.md › Olay tipleri ve Kod garantileri'ndedir. Kartlar yalnızca
zarftan (ve kpi_card açıklamaları kontrattan) kurulur; zarf yorumlanmaz: hesap,
yuvarlama, saat dönüşümü yoktur, alanlar olduğu gibi taşınır.
"""

from backend.envelope import ErrorCode
from backend.tools._ortak import load_contract

SUMMARY_TOOL = "get_flight_summary"
MAP_TOOLS = ("focus_map_object", "highlight_map_set")


def _error_code(envelope: dict) -> str | None:
    error = envelope["error"]
    return None if error is None else error["code"]


def source_chip(name: str, envelope: dict) -> dict | None:
    """Kaynağı olan zarfın çipi; source null ise çip yoktur (Kod garantileri 3)."""
    if envelope["source"] is None:
        return None
    return {
        "tool": name,
        "source": envelope["source"],
        "as_of": envelope["as_of"],
        "stale": envelope["stale"],
        "error_code": _error_code(envelope),
    }


def kpi_card(name: str, envelope: dict) -> dict | None:
    """Başarılı get_flight_summary zarfının tamsayı alanları, kontrat sırasıyla."""
    if name != SUMMARY_TOOL or envelope["error"] is not None:
        return None
    properties = load_contract(name)["value_schema"]["properties"]
    value = envelope["value"]
    items = [
        {"field": field, "description": spec["description"], "value": value[field]}
        for field, spec in properties.items()
        if spec.get("type") == "integer" and field in value
    ]
    return {
        "tool": name,
        "items": items,
        "source": envelope["source"],
        "as_of": envelope["as_of"],
    }


def map_command(name: str, envelope: dict) -> dict | None:
    """Başarılı harita tool'unun value'su, olduğu gibi (docs/harita.md › map_command)."""
    if name not in MAP_TOOLS or envelope["error"] is not None:
        return None
    return envelope["value"]


def selection_card(envelope: dict) -> dict | None:
    """AMBIGUOUS_ENTITY zarfının adayları; kod aday seçmez (Kod garantileri 5)."""
    if _error_code(envelope) != ErrorCode.AMBIGUOUS_ENTITY:
        return None
    return {
        "query": envelope["filters"]["query"],
        "message": envelope["error"]["message"],
        "candidates": envelope["value"],
        "source": envelope["source"],
        "as_of": envelope["as_of"],
    }


class CardBuilder:
    """Bir /chat koşusunun kartlarını üretir; aynı çip bir koşuda bir kez çıkar."""

    def __init__(self) -> None:
        self._chips: set[tuple] = set()

    def cards(self, name: str, envelope: dict) -> list[tuple[str, dict]]:
        """Zarfın olayları, sırasıyla: çip (yeni ise), ardından kpi, seçim kartı ya da komut."""
        events = []
        chip = source_chip(name, envelope)
        if chip is not None:
            key = (chip["source"], chip["as_of"], chip["stale"], chip["error_code"])
            if key not in self._chips:
                self._chips.add(key)
                events.append(("source_chip", chip))
        kpi = kpi_card(name, envelope)
        if kpi is not None:
            events.append(("kpi_card", kpi))
        selection = selection_card(envelope)
        if selection is not None:
            events.append(("selection_card", selection))
        command = map_command(name, envelope)
        if command is not None:
            events.append(("map_command", command))
        return events
