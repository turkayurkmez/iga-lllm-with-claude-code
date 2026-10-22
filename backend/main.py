"""AOCC Copilot HTTP API.

Repo kökünden çalıştırın: uvicorn backend.main:app --reload
"""

import asyncio
import importlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from types import ModuleType
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, field_validator
from starlette.concurrency import run_in_threadpool

from backend import instructions
from backend.agent import run_agent
from backend.cards import CardBuilder
from backend.tools import run_tool, tool_definitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


Emit = Callable[[str, dict], None]


class EventingClient:
    """run_agent'a verilen istemci: model çağrılarını sarar, tool olaylarını üretir.

    Döngü bir turun tool'larını çalıştırınca sonuçları bir sonraki model isteğinin
    son mesajında gönderir; sarmalayıcı o isteğin başında, çalışan her çağrı için
    tool_call'ı ve zarftan kartları yayar (docs/chat.md › Sıra). Çalıştırılmayan
    çağrıların ardından model çağrılmadığı için onlar için olay çıkmaz.
    """

    def __init__(self, client: Any, emit: Emit):
        self._client = client
        self._emit = emit
        self._cards = CardBuilder()
        self._pending: list = []
        self.messages = self

    def create(self, **request: Any) -> Any:
        if self._pending:
            self._emit_turn(self._pending, request["messages"][-1]["content"])
            self._pending = []
        response = self._client.messages.create(**request)
        if response.stop_reason == "tool_use":
            self._pending = [b for b in response.content if b.type == "tool_use"]
        return response

    def _emit_turn(self, calls: list, results: list[dict]) -> None:
        envelopes = {r["tool_use_id"]: json.loads(r["content"]) for r in results}
        for call in calls:
            self._emit(
                "tool_call", {"id": call.id, "name": call.name, "input": call.input}
            )
        for call in calls:
            for event, data in self._cards.cards(call.name, envelopes[call.id]):
                self._emit(event, data)


def run_chat(llm: ModuleType, message: str, version: str, emit: Emit) -> None:
    """Döngüyü çalıştırır ve olayları emit'e verir; thread havuzunda çalışır.

    Son olay done ya da error'dur; hata ayrıntısı yalnızca sunucu loguna yazılır.
    """
    client = EventingClient(llm.client, emit)
    try:
        result = run_agent(message, client=client, instruction_version=version)
    except anthropic.APIError:
        logger.exception("Claude çağrısı başarısız oldu")
        emit("error", {"code": "model_error", "message": ERROR_MESSAGE})
        return
    except Exception:
        logger.exception("Agent döngüsü beklenmedik şekilde kesildi")
        emit("error", {"code": "model_error", "message": ERROR_MESSAGE})
        return

    # Kesik ya da ara metin operatöre gitmez; metin yalnızca tamam'da akar.
    if result.status == "tamam":
        if result.text:
            emit("text_delta", {"text": result.text})
    else:
        emit("error", {"code": result.status, "message": result.reason})
    emit(
        "done",
        {
            "status": result.status,
            "reason": result.reason,
            "turns": len(result.turns),
            "instruction": result.instruction.model_dump(),
        },
    )


async def stream_chat(
    llm: ModuleType, message: str, version: str
) -> AsyncIterator[str]:
    """Döngüyü olay döngüsünü bloklamadan çalıştırır, olayları üretildikçe yazar."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

    def emit(event: str, data: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    def work() -> None:
        try:
            run_chat(llm, message, version, emit)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    task = asyncio.ensure_future(run_in_threadpool(work))
    while (item := await queue.get()) is not None:
        yield sse_event(*item)
    await task


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
    # Talimat, .env yüklendikten sonra COPILOT_INSTRUCTION'a göre okunur; bilinmeyen
    # sürüm de bir ayar hatasıdır. Döngü aynı sürümle çalışır.
    version = instructions.default_version()
    try:
        instructions.load(version)
    except ValueError:
        logger.exception("Talimat sürümü yüklenemedi")
        raise HTTPException(status_code=503, detail=CONFIG_ERROR_MESSAGE) from None

    # text/event-stream için Starlette charset=utf-8'i başlığa kendisi ekler.
    return StreamingResponse(
        stream_chat(llm, request.message, version),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
