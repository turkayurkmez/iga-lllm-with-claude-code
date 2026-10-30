"""Agent döngüsü: soruyu modele verir, istenen tool'ları çalıştırır, sonucu döndürür.

Sözleşme docs/agent.md'de, testleri tests/test_agent.py'dedir. Döngü hesap yapmaz
ve cevap yazmaz; tool'ları yalnızca run_tool ile çalıştırır, zarfı modele olduğu
gibi verir, sınırları uygular ve nasıl bittiğini status ile bildirir.
"""

import importlib
import itertools
import json
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel

from backend import injection, instructions
from backend.envelope import ErrorCode
from backend.session import HistoryTurn, render_history
from backend.tools import run_tool, tool_definitions

MAX_TURNS = 8
MAX_REPEATS = 3
MAX_TOKENS = 16000

Status = Literal[
    "tamam", "tekrar_siniri", "iterasyon_siniri", "max_tokens", "durduruldu"
]

REASON_MAX_TOKENS = "Yanıt uzunluk sınırına ulaştı."
REASON_REFUSAL = "Model yanıt vermeyi reddetti."
REASON_UNEXPECTED = "Beklenmeyen durma nedeni."
REASON_REPEAT = "Aynı tool çağrısı {n}. kez istendi: {name}."
REASON_TURNS = "Tur sınırına ({n}) ulaşıldı."


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]
    executed: bool = False
    envelope: dict[str, Any] | None = None


class Turn(BaseModel):
    index: int
    stop_reason: str | None
    tool_calls: list[ToolCall]


class Instruction(BaseModel):
    """Modele giden system talimatı: dosya adı, tam sürüm ve metnin SHA-256 özeti."""

    name: str
    version: str
    summary: str


class AgentResult(BaseModel):
    status: Status
    reason: str | None
    text: str
    turns: list[Turn]
    instruction: Instruction


def _call_key(call: ToolCall) -> tuple[str, str]:
    # Anahtar sırası farklı ama değeri aynı argümanlar aynı çağrı sayılır.
    return call.name, json.dumps(call.input, sort_keys=True, ensure_ascii=False)


def _verdict(
    turn: Turn, requested: Counter[tuple[str, str]]
) -> tuple[Status, str | None] | None:
    """Turun döngüyü bitirip bitirmediğine karar verir; sürüyorsa None döner.

    Sıra docs/agent.md › Durumlar tablosundaki sıradır; ilk eşleşen geçerlidir.
    """
    if turn.stop_reason == "end_turn":
        return "tamam", None
    if turn.stop_reason == "max_tokens":
        return "max_tokens", REASON_MAX_TOKENS
    if turn.stop_reason != "tool_use":
        reason = REASON_REFUSAL if turn.stop_reason == "refusal" else REASON_UNEXPECTED
        return "durduruldu", reason

    repeated = None
    for call in turn.tool_calls:
        key = _call_key(call)
        requested[key] += 1
        if repeated is None and requested[key] >= MAX_REPEATS:
            repeated = call.name
    if repeated is not None:
        return "tekrar_siniri", REASON_REPEAT.format(n=MAX_REPEATS, name=repeated)
    if turn.index >= MAX_TURNS:
        return "iterasyon_siniri", REASON_TURNS.format(n=MAX_TURNS)
    return None


def _execute(call: ToolCall) -> dict:
    """Çağrıyı run_tool ile çalıştırır, zarfı kaydeder ve tool_result bloğunu kurar."""
    envelope = run_tool(call.name, call.input)
    call.executed = True
    call.envelope = envelope
    error = envelope["error"]
    # Yalnızca şema hatası modele hata olarak gider; diğer kodlar geçerli sonuçtur.
    is_error = error is not None and error["code"] == ErrorCode.SCHEMA_VALIDATION_FAILED
    return {
        "type": "tool_result",
        "tool_use_id": call.id,
        # Model girdisi güvenilmez metni sınırlar; kayıtlı zarf ham kalır (docs/enjeksiyon.md E1).
        "content": injection.render_tool_result(call.name, envelope),
        "is_error": is_error,
    }


def run_agent(
    question: str,
    client: Any = None,
    instruction_version: str | None = None,
    history: list[HistoryTurn] | None = None,
) -> AgentResult:
    """Soruyu agent döngüsünden geçirir; API ve ayar hataları çağırana fırlar.

    instruction_version verilmezse COPILOT_INSTRUCTION (boşsa v3) kullanılır.
    history, sunucunun kendi sakladığı önceki turlardır (backend.session); soru
    bu turlardan sonra gelir. Yoksa ya da boşsa istek geçmişsiz davranışla aynıdır.
    """
    if not question.strip():
        raise ValueError("Soru boş olamaz.")
    # Verilen bilinmeyen sürüm, ayar yüklenmeden ve model çağrılmadan ValueError verir.
    if instruction_version is not None:
        instructions.load(instruction_version)

    # backend.llm ilk çağrıda yüklenir; böylece bu modülü import etmek .env istemez.
    llm = importlib.import_module("backend.llm")
    if client is None:
        client = llm.client

    # Ortamdaki sürüm .env yüklendikten sonra okunur; geçersizse API çağrısından önce
    # ValueError verir.
    name = instruction_version or instructions.default_version()
    system = instructions.load(name)
    instruction = Instruction(
        name=name,
        version=instructions.VERSIONS[name],
        summary=instructions.summary(system),
    )

    request = {
        "model": llm.MODEL,
        "system": system,
        "tools": tool_definitions(),
        "max_tokens": MAX_TOKENS,
    }
    messages: list[dict] = [
        *render_history(history or []),
        {"role": "user", "content": question},
    ]
    requested: Counter[tuple[str, str]] = Counter()
    turns: list[Turn] = []

    for index in itertools.count(1):
        response = client.messages.create(**request, messages=messages)
        calls = [
            ToolCall(id=block.id, name=block.name, input=block.input)
            for block in response.content
            if block.type == "tool_use"
        ]
        turn = Turn(index=index, stop_reason=response.stop_reason, tool_calls=calls)
        turns.append(turn)

        verdict = _verdict(turn, requested)
        if verdict is not None:
            status, reason = verdict
            text = "".join(b.text for b in response.content if b.type == "text")
            return AgentResult(
                status=status,
                reason=reason,
                text=text,
                turns=turns,
                instruction=instruction,
            )

        # Thinking blokları da dahil asistan içeriği olduğu gibi geri gönderilir.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": [_execute(c) for c in calls]})

    raise AssertionError("Ulaşılamaz: döngü en geç MAX_TURNS'te biter.")
