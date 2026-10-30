"""Audit kaydı: her soru için bir question, her thumbs down için bir feedback satırı.

Sözleşme docs/audit.md. Satırlar COPILOT_AUDIT_DIR (boşsa logs/audit) altındaki günlük
JSON Lines dosyasına yalnızca sona eklenir. Tool zarfının value'su kayda girmez; zarftan
yalnızca dayanak alanları (source, as_of, stale, tool_version, author, error.code) taşınır.
"""

import json
import os
import threading
import uuid
from pathlib import Path

from backend import clock, injection, instructions
from backend.agent import AgentResult

ENV_VAR = "COPILOT_AUDIT_DIR"
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "logs" / "audit"

# Aynı süreçteki eşzamanlı yazımlar sıraya girer; satırlar iç içe geçmez.
_lock = threading.Lock()


def audit_dir() -> Path:
    raw = os.getenv(ENV_VAR, "").strip()
    return Path(raw) if raw else DEFAULT_DIR


def new_id() -> str:
    return uuid.uuid4().hex


def append(record: dict) -> None:
    """Satırı ts'nin gününe ait dosyanın sonuna tek write ile ekler."""
    line = json.dumps(record, ensure_ascii=False) + "\n"
    directory = audit_dir()
    with _lock:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{record['ts'][:10]}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(line)
            file.flush()


def tool_calls(result: AgentResult | None) -> list[dict]:
    """AgentResult'taki çağrılar, zarfın yalnızca izin verilen alanlarıyla."""
    if result is None:
        return []
    calls = []
    for turn in result.turns:
        for call in turn.tool_calls:
            envelope = call.envelope or {}
            error = envelope.get("error")
            calls.append(
                {
                    "turn": turn.index,
                    "name": call.name,
                    "input": call.input,
                    "executed": call.executed,
                    "source": envelope.get("source"),
                    "as_of": envelope.get("as_of"),
                    "stale": envelope.get("stale"),
                    "tool_version": envelope.get("tool_version"),
                    "author": envelope.get("author"),
                    "error_code": None if error is None else error["code"],
                }
            )
    return calls


def injection_fields(
    question: str, status: str, result: AgentResult | None
) -> tuple[list[str], list[str]]:
    """(injection_flags, unverified_numbers); docs/enjeksiyon.md E5, E6.

    Cevap denetimleri yalnızca cevap kayda girdiğinde (`tamam`) çalışır.
    """
    flags = injection.message_flags(question)
    numbers: list[str] = []
    if status == "tamam" and result is not None:
        envelopes = [
            call.envelope
            for turn in result.turns
            for call in turn.tool_calls
            if call.envelope
        ]
        numbers = injection.unverified_numbers(result.text, question, envelopes)
        if numbers:
            flags.append("unverified_numbers")
        system = instructions.load(result.instruction.name)
        if injection.leaks_instruction(result.text, system):
            flags.append("instruction_leak")
    if status == "tekrar_siniri":
        flags.append("tekrar_siniri")
    return flags, numbers


def write_question(
    question: str,
    *,
    audit_id: str,
    status: str,
    reason: str | None,
    model: str | None,
    instruction: dict | None,
    chips: list[dict],
    client_disconnected: bool,
    result: AgentResult | None = None,
    session_id: str | None = None,
    turn_index: int | None = None,
) -> None:
    """question satırını yazar; yazım hatası çağırana fırlar.

    session_id ve turn_index oturumdaki yeri bildirir (eski satırlarda yoktur). Geçmişin
    içeriği kayda girmez; question ve answer bu turunkilerdir.

    chips akışın source_chip verileridir; value taşımadıkları için olduğu gibi girer.
    """
    flags, numbers = injection_fields(question, status, result)
    append(
        {
            "type": "question",
            "audit_id": audit_id,
            "ts": clock.now().isoformat(),
            "question": question,
            "status": status,
            "reason": reason,
            # Kesik ya da ara metin kayda girmez (docs/chat.md › Kod garantileri 8).
            "answer": result.text if result and status == "tamam" else None,
            "model": model,
            "instruction": instruction,
            "turns": None if result is None else len(result.turns),
            "tool_calls": tool_calls(result),
            "chips": chips,
            "client_disconnected": client_disconnected,
            "injection_flags": flags,
            "unverified_numbers": numbers,
            "session_id": session_id,
            "turn_index": turn_index,
        }
    )


def write_feedback(audit_id: str) -> None:
    append(
        {
            "type": "feedback",
            "audit_id": audit_id,
            "ts": clock.now().isoformat(),
            "rating": "down",
        }
    )
