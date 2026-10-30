"""AOCC Copilot HTTP API.

Repo kökünden çalıştırın: uvicorn backend.main:app --reload
"""

import asyncio
import importlib
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Annotated, Any, Literal

import anthropic
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from starlette.concurrency import run_in_threadpool

from backend import audit, instructions, live
from backend import session as sessions
from backend.agent import run_agent
from backend.cards import CardBuilder
from backend.rag import search as rag_search
from backend.rag.embed import EmbedConfigError, EmbedError
from backend.session import SESSION_ID_PATTERN, Begin, HistoryTurn
from backend.tools import run_tool, tool_definitions
from backend.tools._ortak import DataError, load_data
from backend.tools.harita import ID_PATTERNS, exists

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# İstemciye yalnızca bu genel mesaj gider; hatanın ayrıntısı sunucu loguna yazılır.
ERROR_MESSAGE = "Yanıt üretilirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
CONFIG_ERROR_MESSAGE = (
    "Sohbet servisi şu anda yapılandırılmamış. Lütfen yöneticinize başvurun."
)
FEEDBACK_ERROR_MESSAGE = (
    "Geri bildirim kaydedilemedi. Lütfen daha sonra tekrar deneyin."
)
INVALID_JSON_MESSAGE = "İstek gövdesi geçerli JSON değil."
UNEXPECTED_MESSAGE = "Beklenmeyen bir hata oluştu."
LIVE_UNAVAILABLE_MESSAGE = "Canlı konum akışı şu anda kullanılamıyor."
STANDS_UNAVAILABLE_MESSAGE = (
    "Stand verisi şu anda okunamıyor. Lütfen daha sonra tekrar deneyin."
)
SELECTED_UNAVAILABLE_MESSAGE = (
    "Seçili nesne şu anda doğrulanamıyor. Lütfen daha sonra tekrar deneyin."
)
SELECTED_NOT_FOUND_MESSAGE = "Seçili nesne haritada bulunamadı."
# docs/rag.md §7: istemciye sabit mesaj gider; ayrıntı (yol, model adı) loga yazılır.
INDEX_NOT_READY_MESSAGE = "Arama indeksi hazır değil. Önce indeksi kurun."
INDEX_MODEL_MISMATCH_MESSAGE = (
    "Arama indeksi ayarlı gömme modeliyle kurulmamış. İndeksi yeniden kurun."
)
SEARCH_UNAVAILABLE_MESSAGE = (
    "Arama şu anda yapılamıyor. Lütfen daha sonra tekrar deneyin."
)
# Olay yokken bağlantıyı canlı tutan yorumun aralığı (docs/canli_akis.md › SSE).
LIVE_PING_INTERVAL_S = 15

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """COPILOT_MQTT_URL doluysa canlı konum tüketicisini sunucuyla birlikte çalıştırır."""
    started = live.start()
    app.state.live = started[0] if started is not None else None
    if started is not None:
        # Canlı mod: tool'ların saati ve get_flight_details konumu depodan.
        live.activate(started[0])
    try:
        yield
    finally:
        app.state.live = None
        if started is not None:
            live.deactivate()
            started[1].stop()


app = FastAPI(title="AOCC Copilot", lifespan=lifespan)


def load_llm() -> ModuleType:
    """backend.llm'i ilk /chat isteğinde yükler; /health API anahtarı olmadan çalışsın diye.

    Başarısız import sys.modules'e girmez, yani her çağrı ayarları yeniden dener.
    """
    # importlib: `from backend import llm` paket özniteliğinde kalan eski modülü döndürebilir.
    return importlib.import_module("backend.llm")


class Selected(BaseModel):
    """Haritada seçili nesne (docs/harita.md › Haritadan sohbete bağlam)."""

    model_config = ConfigDict(extra="forbid")

    object_type: Literal["flight", "stand"]
    id: str

    @model_validator(mode="after")
    def check_id_format(self) -> "Selected":
        if not ID_PATTERNS[self.object_type].fullmatch(self.id):
            raise ValueError(f"Kimlik {self.object_type} biçimine uymuyor.")
        return self


# docs/enjeksiyon.md E4: uzun enjeksiyon yükünü ve maliyeti sınırlar (kod noktası).
MAX_MESSAGE_CHARS = 2000


class ChatRequest(BaseModel):
    # İstemci geçmiş gönderemez: fazla alan (ör. history) reddedilir.
    model_config = ConfigDict(extra="forbid")

    message: str
    selected: Selected | None = None
    # Sunucunun verdiği oturum kimliği; yoksa ya da bilinmiyorsa yeni oturum açılır.
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)

    @field_validator("selected", mode="before")
    @classmethod
    def reject_null_selected(cls, value: Any) -> Any:
        # Alan yoksa varsayılan geçerlidir; açık null ise yanlış biçimdir.
        if value is None:
            raise ValueError("selected nesne olmalı; yoksa alan hiç gönderilmemeli.")
        return value

    @field_validator("message")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Mesaj boş olamaz.")
        if len(value) > MAX_MESSAGE_CHARS:
            raise ValueError(f"Mesaj en fazla {MAX_MESSAGE_CHARS} karakter olabilir.")
        return value


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(pattern=r"^[0-9a-f]{32}$")


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

    def citations(self, text: str) -> list[dict]:
        """Nihai cevabın etiketleri, bu koşuda getirilen parçalarla eşleşmiş olarak."""
        return self._cards.citations(text)

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


def run_chat(
    llm: ModuleType,
    message: str,
    version: str,
    emit: Emit,
    audit_id: str,
    *,
    history: list[HistoryTurn] | None = None,
    session_id: str | None = None,
    session_reset: bool = False,
) -> dict:
    """Döngüyü çalıştırır ve olayları emit'e verir; thread havuzunda çalışır.

    Son olay done ya da error'dur; hata ayrıntısı yalnızca sunucu loguna yazılır.
    Audit satırının sonuç alanlarını döndürür; satırı ChatStream akış bitince yazar.
    """
    client = EventingClient(llm.client, emit)
    try:
        result = run_agent(
            message, client=client, instruction_version=version, history=history
        )
    except Exception as exc:
        if isinstance(exc, anthropic.APIError):
            logger.exception("Claude çağrısı başarısız oldu")
        else:
            logger.exception("Agent döngüsü beklenmedik şekilde kesildi")
        emit("error", {"code": "model_error", "message": ERROR_MESSAGE})
        # Sonuç yok: talimat istekte çözülen sürümden kaydedilir (docs/audit.md).
        return {
            "status": "model_error",
            "reason": ERROR_MESSAGE,
            "model": llm.MODEL,
            "instruction": {
                "name": version,
                "version": instructions.VERSIONS[version],
                "summary": instructions.summary(instructions.load(version)),
            },
        }

    # Kesik ya da ara metin operatöre gitmez; metin yalnızca tamam'da akar.
    if result.status == "tamam":
        if result.text:
            emit("text_delta", {"text": result.text})
            for data in client.citations(result.text):
                emit("citation", data)
    else:
        emit("error", {"code": result.status, "message": result.reason})
    emit(
        "done",
        {
            "status": result.status,
            "reason": result.reason,
            "turns": len(result.turns),
            "instruction": result.instruction.model_dump(),
            "audit_id": audit_id,
            "session_id": session_id,
            "session_reset": session_reset,
        },
    )
    return {
        "status": result.status,
        "reason": result.reason,
        "model": llm.MODEL,
        "instruction": result.instruction.model_dump(),
        "result": result,
    }


class ChatStream:
    """Bir /chat isteğinin akışı ve tek audit satırı (docs/audit.md › /chat).

    Satır akış bitince bir kez yazılır: son olay istemciye iletildiyse hemen,
    istemci akışı kestiyse döngü (thread'de sürer) bittiğinde.
    """

    def __init__(
        self,
        llm: ModuleType,
        message: str,
        version: str,
        prompt: str | None = None,
        session: Begin | None = None,
        history: list[HistoryTurn] | None = None,
    ):
        self._llm = llm
        self._session = session
        self._history = history
        # Audit orijinal mesajı, model not eklenmiş metni alır.
        self._message = message
        self._prompt = message if prompt is None else prompt
        self._version = version
        self.audit_id = audit.new_id()
        self._chips: list[dict] = []
        self._outcome: dict | None = None
        self._task: asyncio.Future | None = None
        self._delivered = False

    async def events(self) -> AsyncIterator[str]:
        """Döngüyü olay döngüsünü bloklamadan çalıştırır, olayları üretildikçe yazar."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()

        def emit(event: str, data: dict) -> None:
            if event == "source_chip":
                self._chips.append(data)
            loop.call_soon_threadsafe(queue.put_nowait, (event, data))

        def work() -> None:
            try:
                self._outcome = run_chat(
                    self._llm,
                    self._prompt,
                    self._version,
                    emit,
                    self.audit_id,
                    history=self._history,
                    session_id=None
                    if self._session is None
                    else self._session.session_id,
                    session_reset=self._session is not None and self._session.reset,
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        self._task = asyncio.ensure_future(run_in_threadpool(work))
        while (item := await queue.get()) is not None:
            yield sse_event(*item)
        await self._task
        # Üreteç son yield'den ancak o olay gönderildikten sonra döner.
        self._delivered = True

    def finish(self) -> None:
        """Yanıt bittiğinde çağrılır; kesilme ve normal bitiş burada ayrılır."""
        if self._delivered:
            self._record(client_disconnected=False)
        elif self._task is not None:
            # Kesilmede döngü durdurulmaz; satır döngü bitince yazılır.
            self._task.add_done_callback(
                lambda _: self._record(client_disconnected=True)
            )

    def _remember(self) -> None:
        """Tamamlanan (tamam) turu oturum geçmişine ekler; diğer turlar girmez."""
        result = None if self._outcome is None else self._outcome.get("result")
        if self._session is None or result is None or result.status != "tamam":
            return
        sessions.STORE.add(
            self._session.session_id,
            {
                # Orijinal mesaj: haritadan seçim notu geçmişe girmez.
                "question": self._message,
                "answer": result.text,
                "tool_calls": [
                    {"name": call.name, "input": call.input}
                    for turn in result.turns
                    for call in turn.tool_calls
                    if call.executed
                ],
            },
        )

    def _record(self, *, client_disconnected: bool) -> None:
        # Yazım hatası akışı etkilemez; ayrıntı yalnızca sunucu loguna yazılır.
        try:
            if self._outcome is None:
                raise RuntimeError("Döngü sonuç üretmeden bitti.")
            self._remember()
            audit.write_question(
                self._message,
                audit_id=self.audit_id,
                chips=self._chips,
                client_disconnected=client_disconnected,
                session_id=None if self._session is None else self._session.session_id,
                turn_index=None if self._session is None else self._session.turn_index,
                **self._outcome,
            )
        except Exception:
            logger.exception("Audit kaydı yazılamadı")


class ChatResponse(StreamingResponse):
    """Akışın nasıl bittiğini (tamamlandı ya da istemci kesti) ChatStream'e bildirir.

    ASGI 2.4'te gönderim hatasında üreteç kapatılmadan bırakılır; bu yüzden bitiş
    üretecin finally'sine değil yanıtın kendisine bağlanır.
    """

    def __init__(self, stream: ChatStream):
        super().__init__(
            stream.events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
        self._stream = stream

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._stream.finish()


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


class LiveResponse(StreamingResponse):
    """GET /live/positions akışı: snapshot, depo olayları ve olay yokken ping.

    Abonelik yanıt düzeyinde bırakılır: ASGI 2.4'te istemci gidince üreteç
    kapatılmaz (bkz. ChatResponse).
    """

    def __init__(self, hub: live.LiveHub):
        self._hub = hub
        snapshot, self._queue = hub.subscribe()
        super().__init__(
            self._events(snapshot),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    async def _events(self, snapshot: dict) -> AsyncIterator[str]:
        yield sse_event("snapshot", snapshot)
        while True:
            try:
                name, data = await asyncio.wait_for(
                    self._queue.get(), LIVE_PING_INTERVAL_S
                )
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield sse_event(name, data)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._hub.unsubscribe(self._queue)


@app.get("/live/positions")
async def live_positions() -> Response:
    hub = getattr(app.state, "live", None)
    if hub is None:
        return json_response({"detail": LIVE_UNAVAILABLE_MESSAGE}, 503)
    return LiveResponse(hub)


@app.get("/map/stands")
def map_stands() -> Response:
    """COPILOT_DATA › stands, kayıtlar aynen ve stand_code sıralı (docs/canli_akis.md)."""
    # Senkron: FastAPI dosya okumasını thread havuzunda çalıştırır.
    try:
        data, _ = load_data(["stands"])
        stands = data["stands"]
        if not isinstance(stands, list) or not all(isinstance(s, dict) for s in stands):
            raise DataError("stands bir nesne listesi değil.")
    except DataError:
        logger.exception("Stand verisi okunamadı.")
        return json_response({"detail": STANDS_UNAVAILABLE_MESSAGE}, 503)
    ordered = sorted(stands, key=lambda stand: str(stand.get("stand_code", "")))
    return json_response({"stands": ordered}, 200)


def reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("q boş olamaz.")
    return value


@app.get("/rag/search")
def rag_search_endpoint(
    q: Annotated[str, AfterValidator(reject_blank)],
    k: Annotated[int, Query(ge=1, le=20)] = rag_search.DEFAULT_K,
    status: str | None = None,
    language: str | None = None,
    type: str | None = None,
    doc_id: str | None = None,
    method: Literal["vector", "bm25", "hybrid"] = "vector",
    priority: bool = False,
) -> Response:
    """İndekste arama (docs/rag.md §7, docs/hibrit.md); zarf değildir.

    `method` yalnızca `vector` dışında, `priority` yalnızca `hybrid` gövdesine girer:
    M5.1 gövdesi (`list(body)`) değişmez. `priority=true` `hybrid` dışında 422.
    `bm25` gömme ayarı istemez.
    """
    if priority and method != "hybrid":
        return json_response(
            {"detail": "priority yalnızca method=hybrid ile kullanılabilir."}, 422
        )
    # Senkron: gömme isteği ve indeks okuması FastAPI'nin thread havuzunda çalışır.
    filters = {
        name: value
        for name, value in (
            ("status", status),
            ("language", language),
            ("type", type),
            ("doc_id", doc_id),
        )
        if value is not None
    }
    try:
        results = rag_search.search(q, k=k, method=method, priority=priority, **filters)
    except rag_search.IndexNotReadyError as exc:
        logger.warning("Arama indeksi hazır değil: %s", exc)
        message, code = INDEX_NOT_READY_MESSAGE, exc.code
    except rag_search.IndexModelMismatchError as exc:
        logger.warning("Arama indeksi modeli uyuşmuyor: %s", exc)
        message, code = INDEX_MODEL_MISMATCH_MESSAGE, exc.code
    except (EmbedError, EmbedConfigError):
        logger.exception("Arama sorusu gömülemedi.")
        return json_response({"detail": SEARCH_UNAVAILABLE_MESSAGE}, 503)
    else:
        body = {"query": q, "k": k, "filters": filters, "results": results}
        if method == "hybrid":
            body = {"query": q, "k": k, "method": method, "priority": priority, **body}
        elif method != "vector":
            body = {"query": q, "k": k, "method": method, **body}
        return json_response(body, 200)
    return json_response({"error": {"code": code, "message": message}}, 503)


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


@app.post("/feedback")
async def feedback(request: FeedbackRequest) -> Response:
    """Thumbs down: ayrı bir feedback satırı yazar (docs/audit.md › POST /feedback).

    backend.llm yüklenmez; audit_id'nin bir soruya ait olduğu denetlenmez.
    """
    try:
        await run_in_threadpool(audit.write_feedback, request.audit_id)
    except Exception:
        logger.exception("Geri bildirim yazılamadı")
        return json_response({"detail": FEEDBACK_ERROR_MESSAGE}, 503)
    return Response(status_code=204)


def selected_note(selected: Selected) -> str:
    """Modele giden sabit biçimli tek satır (docs/harita.md › Haritadan sohbete bağlam)."""
    return f"Haritada seçili: {selected.object_type} {selected.id}"


async def check_selected(selected: Selected) -> None:
    """Seçili nesne veride yoksa 422, veri okunamıyorsa 503; model çağrılmadan önce."""
    try:
        # exists veriyi diskten ve canlı depodan okur; olay döngüsünü bloklamasın.
        found, _ = await run_in_threadpool(exists, selected.object_type, [selected.id])
    except DataError:
        logger.exception("Seçili nesne doğrulanamadı")
        raise HTTPException(
            status_code=503, detail=SELECTED_UNAVAILABLE_MESSAGE
        ) from None
    if not found:
        # FastAPI doğrulama gövdesiyle aynı biçim (docs/chat.md › Uç).
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["body", "selected"],
                    "msg": SELECTED_NOT_FOUND_MESSAGE,
                }
            ],
        )


@app.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    # Doğrulama modelden ve ayar denetiminden önce: geçersiz istek hiçbir şeyi tetiklemez.
    prompt = None
    if request.selected is not None:
        await check_selected(request.selected)
        prompt = f"{selected_note(request.selected)}\n{request.message}"
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

    # Oturum ayar denetimlerinden sonra açılır; 503 yolları oturum bırakmaz.
    session = sessions.STORE.begin(request.session_id)
    history = sessions.STORE.history(session.session_id)

    # text/event-stream için Starlette charset=utf-8'i başlığa kendisi ekler.
    return ChatResponse(
        ChatStream(llm, request.message, version, prompt, session, history)
    )
