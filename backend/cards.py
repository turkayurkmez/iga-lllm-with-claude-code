"""Tool zarfından /chat olayları: source_chip, kpi_card, selection_card, map_command.

Sözleşme docs/chat.md › Olay tipleri ve Kod garantileri'ndedir. Kartlar yalnızca
zarftan (ve kpi_card açıklamaları kontrattan) kurulur; zarf yorumlanmaz: hesap,
yuvarlama, saat dönüşümü yoktur, alanlar olduğu gibi taşınır.
"""

import re

from backend.envelope import ErrorCode
from backend.tools._ortak import load_contract

SUMMARY_TOOL = "get_flight_summary"
SEARCH_TOOL = "search_documents"
# Etiket biçimi search_documents kontratındaki chunk_id desenidir: [D03#02].
CITATION_TAG = re.compile(r"\[(D\d{2}#\d{2,})\]")
CITATION_DOCUMENT_FIELDS = ("title", "section", "revision", "effective_from", "status")
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


def retrieved_chunks(name: str, envelope: dict) -> list[dict]:
    """Başarılı search_documents zarfının parçaları; hatalı zarf parça getirmemiştir."""
    if name != SEARCH_TOOL or envelope["error"] is not None:
        return []
    return envelope["value"] or []


def citation(chunk_id: str, chunks: dict[str, dict]) -> dict:
    """Etiketin olayı: eşleşen parçanın belge alanları olduğu gibi, yoksa yalnızca kimlik."""
    found = chunks.get(chunk_id)
    if found is None:
        return {"chunk_id": chunk_id, "dogrulandi": False}
    return {"chunk_id": chunk_id, "dogrulandi": True} | {
        field: found[field] for field in CITATION_DOCUMENT_FIELDS
    }


class CardBuilder:
    """Bir /chat koşusunun kartlarını üretir; aynı çip bir koşuda bir kez çıkar."""

    def __init__(self) -> None:
        self._chips: set[tuple] = set()
        self._chunks: dict[str, dict] = {}

    def citations(self, text: str) -> list[dict]:
        """Cevaptaki her ayrık etiketin olayı, ilk geçiş sırasıyla (docs/chat.md › Atıf olayı)."""
        chunk_ids = dict.fromkeys(CITATION_TAG.findall(text))
        return [citation(chunk_id, self._chunks) for chunk_id in chunk_ids]

    def cards(self, name: str, envelope: dict) -> list[tuple[str, dict]]:
        """Zarfın olayları, sırasıyla: çip (yeni ise), ardından kpi, seçim kartı ya da komut."""
        for found in retrieved_chunks(name, envelope):
            # Aynı kimlik birden çok aramada gelirse ilk çağrının parçası kalır.
            self._chunks.setdefault(found["chunk_id"], found)
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
