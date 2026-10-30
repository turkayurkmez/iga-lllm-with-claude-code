"""Sohbet oturumları: sunucu tarafı konuşma geçmişi (spec: 2026-10-30-…-design.md › A).

Geçmişi yalnızca sunucu tutar; istemci yalnızca session_id taşır, bu yüzden sahte
asistan turu enjekte edilemez. Saklanan şey her tamamlanan turun soru, cevap
metni ve çağrılan tool'ların adı ile argümanlarıdır; tool sonuçları ve sayılar
saklanmaz (yeni sayı yalnızca o turun tool çağrısından gelir). Bellekte tutulur,
kalıcılık yoktur. Saat yalnızca backend.clock.now()'dan okunur.
"""

import json
import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple, TypedDict

from backend import clock

SESSION_ID_PATTERN = r"^[0-9a-f]{32}$"
MAX_SESSIONS = 100
MAX_TURNS = 20
TTL = timedelta(hours=2)
# Modele giden görünüm: son MODEL_TURNS tur ve toplam MODEL_CHARS karakter.
MODEL_TURNS = 6
MODEL_CHARS = 12000


class HistoryTurn(TypedDict):
    question: str
    answer: str
    # Her çağrı {"name": str, "input": dict}.
    tool_calls: list[dict]


class Begin(NamedTuple):
    session_id: str
    # İstek bir session_id taşıyıp oturum bulunamadıysa True.
    reset: bool
    # Oturumdaki kayıtlı tur sayısı + 1.
    turn_index: int


@dataclass
class _Session:
    turns: list[HistoryTurn]
    last_used: datetime


def _tool_note(turn: HistoryTurn) -> str:
    calls = "; ".join(
        f"{call['name']} {json.dumps(call['input'], ensure_ascii=False, separators=(',', ':'))}"
        for call in turn["tool_calls"]
    )
    return f"\n\n[Önceki turda çağrılan araçlar: {calls}]" if calls else ""


def _assistant_text(turn: HistoryTurn) -> str:
    return turn["answer"] + _tool_note(turn)


def render_history(turns: list[HistoryTurn]) -> list[dict]:
    """Geçmişi modele düz metin user/assistant turları olarak çevirir.

    tool_use/tool_result bloğu kullanılmaz: o blok kuralları yalnızca bir turun
    kendi döngüsü içindir. Tool çağrıları asistan metninin sonuna not olarak girer.
    """
    messages: list[dict] = []
    for turn in turns:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": _assistant_text(turn)})
    return messages


class SessionStore:
    """session_id → geçmiş; LRU, hareketsizlikte sona erme, kilitli."""

    def __init__(
        self,
        *,
        max_sessions: int = MAX_SESSIONS,
        max_turns: int = MAX_TURNS,
        ttl: timedelta = TTL,
    ):
        self._max_sessions = max_sessions
        self._max_turns = max_turns
        self._ttl = ttl
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = threading.Lock()

    def _live(self, session_id: str, moment: datetime) -> _Session | None:
        found = self._sessions.get(session_id)
        if found is None:
            return None
        if moment - found.last_used > self._ttl:
            del self._sessions[session_id]
            return None
        return found

    def begin(self, session_id: str | None) -> Begin:
        """İstek için oturumu açar ya da sürdürür; bulunamayan id yeni oturum olur."""
        moment = clock.now()
        with self._lock:
            found = None if session_id is None else self._live(session_id, moment)
            if found is not None:
                found.last_used = moment
                self._sessions.move_to_end(session_id)
                return Begin(session_id, False, len(found.turns) + 1)
            new_id = secrets.token_hex(16)
            self._sessions[new_id] = _Session(turns=[], last_used=moment)
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
            return Begin(new_id, session_id is not None, 1)

    def history(self, session_id: str) -> list[HistoryTurn]:
        """Modele gidecek görünüm; kopya döner. Turlar eskiden yeniye, bölünmez."""
        with self._lock:
            found = self._sessions.get(session_id)
            turns = [] if found is None else list(found.turns[-MODEL_TURNS:])
        chosen: list[HistoryTurn] = []
        total = 0
        for turn in reversed(turns):
            size = len(_assistant_text(turn))
            if total + size > MODEL_CHARS:
                break
            chosen.append(turn)
            total += size
        return chosen[::-1]

    def add(self, session_id: str, turn: HistoryTurn) -> None:
        """Tamamlanan turu ekler; oturum yoksa (atıldı) sessizce bırakılır."""
        moment = clock.now()
        with self._lock:
            found = self._sessions.get(session_id)
            if found is None:
                return
            found.turns.append(turn)
            del found.turns[: -self._max_turns]
            found.last_used = moment
            self._sessions.move_to_end(session_id)


STORE = SessionStore()
