"""Tool çıktılarının ortak zarfını kuran katman (sözleşme: docs/zarf.md).

Tool zarfı kendisi kurmaz; {value, source, data_time?, error?} döndürür. Argümanları
doğrulamak, as_of/stale hesaplamak, tazelik eşiğini uygulamak ve katman hatalarını
yazmak buranın işidir. Tool'un gönderdiği as_of/stale yok sayılır. Saat yalnızca
backend.clock'tan alınır.

docs/zarf.schema.json, Envelope modelinden üretilir: python -m backend.envelope
"""

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from backend import clock

logger = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "docs" / "zarf.schema.json"


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS_ENTITY = "AMBIGUOUS_ENTITY"
    STALE_DATA = "STALE_DATA"
    CAPABILITY_NOT_IN_SCOPE = "CAPABILITY_NOT_IN_SCOPE"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"


MESSAGES = {
    ErrorCode.STALE_DATA: "Veri güncel değil; son bilinen değer döndürüldü.",
    ErrorCode.CAPABILITY_NOT_IN_SCOPE: "Bu istek copilot'un kapsamı dışında.",
}
ARGS_INVALID = "Tool argümanları şemaya uymuyor."
OUTPUT_INVALID = "Tool çıktısı şemaya uymuyor; yanıt üretilemedi."


class EnvelopeError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(description="Kısa, genel Türkçe açıklama; iç ayrıntı içermez.")


class Envelope(BaseModel):
    """Her tool çıktısının ortak zarfı; sekiz alan da zorunludur (docs/zarf.md)."""

    model_config = ConfigDict(extra="forbid", title="Envelope")

    value: Any = Field(description="Tool'un döndürdüğü veri; katman hatasında null.")
    source: str | None = Field(description="Verinin kaynağı; katman hatasında null.")
    as_of: AwareDatetime | None = Field(
        description="Verinin ait olduğu an, +03:00; katman hesaplar."
    )
    filters: dict[str, Any] = Field(description="Doğrulanmış tool argümanları.")
    stale: bool = Field(description="true ise error.code STALE_DATA'dır.")
    tool_version: str | None = Field(description="Tool sürümü, MAJOR.MINOR.PATCH.")
    error: EnvelopeError | None
    author: Literal["tool", "layer"] = Field(description="Zarfı kimin yazdığı.")

    @model_validator(mode="after")
    def _stale_matches_error(self) -> "Envelope":
        is_stale_error = (
            self.error is not None and self.error.code is ErrorCode.STALE_DATA
        )
        if self.stale != is_stale_error:
            raise ValueError("stale ile STALE_DATA birlikte gitmeli.")
        return self


class ToolErrorOutput(BaseModel):
    # Tool yalnızca bu iki kodu yazabilir; diğerleri katmanındır.
    code: Literal[ErrorCode.NOT_FOUND, ErrorCode.AMBIGUOUS_ENTITY]
    message: str


class ToolOutput(BaseModel):
    """Tool'un katmana döndürdüğü nesne; ek alanlar (as_of, stale dahil) atılır."""

    value: Any
    source: str
    data_time: AwareDatetime | None = None
    error: ToolErrorOutput | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    func: Callable[..., Any]
    args_model: type[BaseModel]
    # None: tazelik denetlenmez.
    max_age: timedelta | None = None


def _envelope(
    *,
    author: Literal["tool", "layer"],
    value: Any = None,
    source: str | None = None,
    as_of: datetime | None = None,
    filters: dict | None = None,
    stale: bool = False,
    tool_version: str | None = None,
    code: ErrorCode | None = None,
    message: str | None = None,
) -> dict:
    return Envelope(
        value=value,
        source=source,
        as_of=as_of,
        filters=filters if filters is not None else {},
        stale=stale,
        tool_version=tool_version,
        error=None if code is None else EnvelopeError(code=code, message=message),
        author=author,
    ).model_dump(mode="json")


def call_tool(registry: Mapping[str, ToolSpec], name: str, args: Any) -> dict:
    """Tool'u çalıştırır ve JSON'a yazılabilir zarfı döndürür."""
    spec = registry.get(name)
    if spec is None:
        code = ErrorCode.CAPABILITY_NOT_IN_SCOPE
        return _envelope(author="layer", code=code, message=MESSAGES[code])

    try:
        validated = spec.args_model.model_validate(args)
    except ValidationError:
        logger.warning("Argüman doğrulanamadı: %s", name, exc_info=True)
        return _envelope(
            author="layer",
            tool_version=spec.version,
            code=ErrorCode.SCHEMA_VALIDATION_FAILED,
            message=ARGS_INVALID,
        )
    filters = validated.model_dump(mode="json")

    try:
        output = ToolOutput.model_validate(spec.func(**validated.model_dump()))
    except ValidationError:
        logger.warning("Tool çıktısı reddedildi: %s", name, exc_info=True)
        return _envelope(
            author="layer",
            filters=filters,
            tool_version=spec.version,
            code=ErrorCode.SCHEMA_VALIDATION_FAILED,
            message=OUTPUT_INVALID,
        )

    now = clock.now()
    as_of = (output.data_time or now).astimezone(clock.TZ)
    common = {
        "value": output.value,
        "source": output.source,
        "as_of": as_of,
        "filters": filters,
        "tool_version": spec.version,
    }

    if output.error is not None:
        return _envelope(
            author="tool",
            code=output.error.code,
            message=output.error.message,
            **common,
        )

    if spec.max_age is not None and now - as_of > spec.max_age:
        code = ErrorCode.STALE_DATA
        return _envelope(
            author="layer", stale=True, code=code, message=MESSAGES[code], **common
        )

    return _envelope(author="tool", **common)


def schema_json() -> str:
    schema = Envelope.model_json_schema()
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    SCHEMA_FILE.write_text(schema_json(), encoding="utf-8", newline="\n")
    print(f"Yazıldı: {SCHEMA_FILE}")
