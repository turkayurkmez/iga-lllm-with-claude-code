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

from backend import clock
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
) -> None:
    """question satırını yazar; yazım hatası çağırana fırlar.

    chips akışın source_chip verileridir; value taşımadıkları için olduğu gibi girer.
    """
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
