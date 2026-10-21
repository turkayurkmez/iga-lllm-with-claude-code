"""AOCC Copilot HTTP API.

Repo kökünden çalıştırın: uvicorn backend.main:app --reload
"""

import importlib
import json
import logging
from collections.abc import AsyncIterator
from types import ModuleType

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, field_validator
from starlette.concurrency import run_in_threadpool

from backend.prompts import SYSTEM_INSTRUCTIONS
from backend.tools import run_tool, tool_definitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_TOKENS = 16000

# İstemciye yalnızca bu genel mesaj gider; hatanın ayrıntısı sunucu loguna yazılır.
ERROR_MESSAGE = "Yanıt üretilirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
CONFIG_ERROR_MESSAGE = (
    "Sohbet servisi şu anda yapılandırılmamış. Lütfen yöneticinize başvurun."
)
INVALID_JSON_MESSAGE = "İstek gövdesi geçerli JSON değil."
UNEXPECTED_MESSAGE = "Beklenmeyen bir hata oluştu."

# Zarfın error.code'u → HTTP durum kodu (docs/http.md › Durum kodu eşlemesi).
# Tablo kapalıdır: listede olmayan kod 500 olur.
STATUS_BY_CODE = {
    None: 200,
    "STALE_DATA": 200,
    "NOT_FOUND": 404,
    "AMBIGUOUS_ENTITY": 409,
    "CAPABILITY_NOT_IN_SCOPE": 404,
    "SCHEMA_VALIDATION_FAILED": 422,
}

app = FastAPI(title="AOCC Copilot")


def load_llm() -> ModuleType:
    """backend.llm'i ilk /chat isteğinde yükler; /health API anahtarı olmadan çalışsın diye.

    Başarısız import sys.modules'e girmez, yani her çağrı ayarları yeniden dener.
    """
    # importlib: `from backend import llm` paket özniteliğinde kalan eski modülü döndürebilir.
    return importlib.import_module("backend.llm")


class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Mesaj boş olamaz.")
        return value


def sse_event(event: str, data: dict) -> str:
    # ensure_ascii=False: Türkçe karakterler ş gibi kaçış dizilerine dönüşmeden,
    # UTF-8 olarak gönderilir.
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_reply(llm: ModuleType, message: str) -> AsyncIterator[str]:
    """Model yanıtını SSE olayları olarak üretir: delta*, ardından done ya da error."""
    try:
        async with llm.async_client.messages.stream(
            model=llm.MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_INSTRUCTIONS,
            messages=[{"role": "user", "content": message}],
        ) as stream:
            async for text in stream.text_stream:
                yield sse_event("delta", {"text": text})
            final = await stream.get_final_message()
    except anthropic.APIError:
        logger.exception("Claude çağrısı başarısız oldu")
        yield sse_event("error", {"message": ERROR_MESSAGE})
        return

    yield sse_event("done", {"stop_reason": final.stop_reason})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def json_response(content: object, status_code: int) -> Response:
    """/tools yanıtı: UTF-8, kaçışsız JSON; tool sonucu canlı veri, önbelleğe alınmaz."""
    # JSONResponse charset eklemez ve ensure_ascii=True yazar; ikisi de sözleşmeye aykırı.
    return Response(
        content=json.dumps(content, ensure_ascii=False).encode("utf-8"),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/tools")
async def list_tools() -> Response:
    return json_response(tool_definitions(), 200)


@app.post("/tools/{name}")
async def call_tool(name: str, request: Request) -> Response:
    """Gövdeyi argüman olarak run_tool'a verir; zarfı değiştirmeden taşır (docs/http.md)."""
    raw = await request.body()
    try:
        args = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        logger.exception("Tool isteğinin gövdesi çözülemedi: %s", name)
        return json_response({"detail": INVALID_JSON_MESSAGE}, 400)

    try:
        # run_tool veriyi diskten okur; olay döngüsünü bloklamasın.
        envelope = await run_in_threadpool(run_tool, name, args)
        error = envelope["error"]
        status_code = STATUS_BY_CODE[None if error is None else error["code"]]
        return json_response(envelope, status_code)
    except Exception:
        logger.exception("Tool çağrısı taşınamadı: %s", name)
        return json_response({"detail": UNEXPECTED_MESSAGE}, 500)


@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    # ConfigError, backend.llm import edilemeden yakalanamaz; RuntimeError onun taban sınıfıdır.
    try:
        llm = load_llm()
    except RuntimeError:
        logger.exception("LLM ayarları yüklenemedi")
        raise HTTPException(status_code=503, detail=CONFIG_ERROR_MESSAGE) from None

    # text/event-stream için Starlette charset=utf-8'i başlığa kendisi ekler.
    return StreamingResponse(
        stream_reply(llm, request.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
