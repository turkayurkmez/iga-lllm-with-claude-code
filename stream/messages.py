"""Topic adları, mesaj kurucu ve ayrıştırıcıları (docs/canli_akis.md › Topic'ler, Mesajlar).

Konum ve uçuş gövdesi kaynak kaydın kendisidir; burada yalnızca saat ve durum
mesajları kurulur. Ayrıştırıcılar geçersiz gövdede None döner (Tüketici › Mesaj
doğrulama). Bayatlık eşiği yalnızca burada tanımlıdır.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

TZ = timezone(timedelta(hours=3))
DEFAULT_ROOT = "aocc/sim/v1"
BROKER_RE = re.compile(r"^mqtt://([^:/\s]+)(?::(\d{1,5}))?$")
DEFAULT_PORT = 1883
CLOCK_STEP_S = 30
STALE_AFTER_S = 300

STATE_ON = "yayinda"
STATE_DONE = "bitti"
STATE_LOST = "koptu"
# Yayınlanamaz; yalnızca tüketici broker'a bağlı değilken kullanır.
STATE_NO_BROKER = "broker_yok"
PUBLISHED_STATES = (STATE_ON, STATE_DONE, STATE_LOST)


class Message(NamedTuple):
    topic: str
    payload: bytes
    qos: int
    retain: bool


def parse_broker_url(value: str) -> tuple[str, int]:
    """`mqtt://host[:port]` → (host, port); geçersizse ValueError."""
    match = BROKER_RE.match(value)
    if not match:
        raise ValueError(f"mqtt://host:port biçiminde olmalı: {value}")
    port = int(match.group(2)) if match.group(2) else DEFAULT_PORT
    if not 0 < port < 65536:
        raise ValueError(f"Port 1–65535 arasında olmalı: {value}")
    return match.group(1), port


def encode(record: dict) -> bytes:
    """Tek satır UTF-8 JSON; Türkçe karakterler kaçışsız kalır."""
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


def status_topic(root: str) -> str:
    return f"{root}/status"


def clock_topic(root: str) -> str:
    return f"{root}/clock"


def flight_topic(root: str, flight_id: str) -> str:
    return f"{root}/flights/{flight_id}"


def position_topic(root: str, key: str) -> str:
    return f"{root}/positions/{key}"


def position(root: str, record: dict) -> Message:
    return Message(position_topic(root, record["Key"]), encode(record), 0, True)


def position_clear(root: str, key: str) -> Message:
    # Boş retained gövde broker'daki son konumu siler.
    return Message(position_topic(root, key), b"", 0, True)


def flight(root: str, record: dict) -> Message:
    return Message(flight_topic(root, record["_id"]), encode(record), 1, True)


def clock(root: str, epoch: int, speed: float) -> Message:
    now = datetime.fromtimestamp(epoch, TZ).isoformat()
    # Tam sayı hız tamsayı yazılır (60, 60.0 değil).
    speed_value = int(speed) if speed.is_integer() else speed
    body = {"now": now, "epoch": epoch, "speed": speed_value}
    return Message(clock_topic(root), encode(body), 0, True)


def status(root: str, state: str, **fields: str) -> Message:
    return Message(status_topic(root), encode({"state": state, **fields}), 1, True)


def decode_object(payload: bytes) -> dict | None:
    """UTF-8 JSON nesnesi değilse None."""
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def is_int(value) -> bool:
    # bool, int'in alt sınıfıdır; true/false tamsayı sayılmaz.
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def parse_position(key: str, payload: bytes) -> dict | None:
    record = decode_object(payload)
    if (
        record is None
        or record.get("Key") != key
        or not is_int(record.get("LastUpdate"))
    ):
        return None
    return record


def parse_flight(flight_id: str, payload: bytes) -> dict | None:
    record = decode_object(payload)
    if record is None or record.get("_id") != flight_id:
        return None
    return record


def parse_clock(payload: bytes) -> dict | None:
    body = decode_object(payload)
    if (
        body is None
        or not isinstance(body.get("now"), str)
        or not is_int(body.get("epoch"))
        or not is_number(body.get("speed"))
    ):
        return None
    return body


def parse_status(payload: bytes) -> str | None:
    body = decode_object(payload)
    state = body.get("state") if body is not None else None
    return state if state in PUBLISHED_STATES else None
