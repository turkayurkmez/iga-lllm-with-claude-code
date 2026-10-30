"""Uçuş tool'larının giriş noktaları (sözleşme: docs/tools.md).

Dışarıya yalnızca iki giriş noktası açılır: run_tool ve tool_definitions. Tool
tanımları backend/tools/contracts/*.json'dan okunur. run_tool zarfı
backend.envelope.call_tool ile kurar ve hiçbir koşulda istisna fırlatmaz.
"""

import logging
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from backend.envelope import (
    OUTPUT_INVALID,
    Envelope,
    EnvelopeError,
    ErrorCode,
    ToolSpec,
    call_tool,
)
from backend.tools._ortak import (
    TOOL_NAMES,
    DataError,
    args_model,
    load_contract,
)
from backend.tools.chart_query import check_query
from backend.tools.get_chart_data import get_chart_data
from backend.tools.get_flight_details import get_flight_details
from backend.tools.get_flight_summary import get_flight_summary
from backend.tools.harita import (
    check_focus,
    check_highlight,
    focus_map_object,
    highlight_map_set,
)
from backend.tools.resolve_flight_identity import resolve_flight_identity
from backend.tools.search_documents import search_documents

__all__ = ["run_tool", "tool_definitions"]

logger = logging.getLogger(__name__)

# Tool adı → {value, source, data_time?, error?} döndüren fonksiyon. Tool'lar
# yazıldıkça buraya eklenir; eksik olan, geçerli argümanda veri hatası döner.
IMPLEMENTATIONS: dict[str, Callable[..., dict]] = {
    "get_flight_summary": get_flight_summary,
    "resolve_flight_identity": resolve_flight_identity,
    "get_flight_details": get_flight_details,
    "focus_map_object": focus_map_object,
    "highlight_map_set": highlight_map_set,
    "search_documents": search_documents,
    "get_chart_data": get_chart_data,
}

# Şemanın anlatamadığı argüman kuralları (yalnızca olan tool'lar).
ARG_CHECKS: dict[str, Callable[[dict], str | None]] = {
    "focus_map_object": check_focus,
    "highlight_map_set": check_highlight,
    "get_chart_data": check_query,
}


def _not_implemented(name: str) -> Callable[..., dict]:
    def func(**_kwargs: Any) -> dict:
        raise DataError(f"Tool henüz yazılmadı: {name}")

    return func


def _build_registry() -> dict[str, ToolSpec]:
    registry = {}
    for name in TOOL_NAMES:
        contract = load_contract(name)
        registry[name] = ToolSpec(
            name=name,
            version=contract["version"],
            func=IMPLEMENTATIONS.get(name, _not_implemented(name)),
            args_model=args_model(contract["input_schema"], ARG_CHECKS.get(name)),
        )
    return registry


REGISTRY = _build_registry()


def tool_definitions() -> list[dict]:
    """Tool'ların Anthropic tool tanımı; kontrat dosyaları her çağrıda okunur."""
    definitions = []
    for name in TOOL_NAMES:
        contract = load_contract(name)
        definitions.append(
            {key: contract[key] for key in ("name", "description", "input_schema")}
        )
    return definitions


def _failure(spec: ToolSpec | None, filters: dict) -> dict:
    return Envelope(
        value=None,
        source=None,
        as_of=None,
        filters=filters,
        stale=False,
        tool_version=spec.version if spec is not None else None,
        error=EnvelopeError(
            code=ErrorCode.SCHEMA_VALIDATION_FAILED, message=OUTPUT_INVALID
        ),
        author="layer",
    ).model_dump(mode="json")


def run_tool(name: Any, args: Any) -> dict:
    """Tool'u çalıştırır ve zarfı döndürür (docs/tools.md › Hata eşlemesi)."""
    # Metin olmayan ad (None, liste) kayıtta aranmaz; katman kapsam dışı döner.
    key = name if isinstance(name, str) else ""
    spec = REGISTRY.get(key)

    filters: dict = {}
    if spec is not None:
        try:
            filters = spec.args_model.model_validate(args).model_dump(mode="json")
        except ValidationError:
            # Şema hatası zarfını call_tool yazar.
            pass

    try:
        return call_tool(REGISTRY, key, args)
    except DataError:
        logger.exception("Tool verisi kullanılamadı: %s", key)
    except Exception:
        logger.exception("Tool beklenmeyen bir hatayla durdu: %s", key)
    return _failure(spec, filters)
