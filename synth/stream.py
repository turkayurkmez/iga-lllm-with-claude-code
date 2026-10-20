"""Konum kayıtlarını simüle zamanla stdout'a akıtır (docs/bozulma.md › Akış).

Repo kökünden çalıştırın:
    python -m synth.stream --in girdi.json --from HH:MM [--speed 60] [--no-wait]

stdout'a yalnızca NDJSON konum satırları yazılır; özet ve hatalar stderr'e gider. Çıktı
yalnızca girdiden ve --from'dan türer; --speed ve --no-wait yalnızca yazılma anını etkiler.
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))
DEFAULT_SPEED = 60.0
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FROM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class StreamError(Exception):
    """Girdi ya da argüman geçersiz; mesaj kullanıcıya gösterilir."""


def load_input(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except OSError as error:
        raise StreamError(f"Girdi okunamadı: {path} ({error.strerror})") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StreamError(f"Girdi geçerli bir JSON değil: {path}") from None
    if not isinstance(data, dict):
        raise StreamError("Girdi bir JSON nesnesi olmalı.")
    return data


def parse_day(data: dict) -> date:
    meta = data.get("meta")
    value = meta.get("date") if isinstance(meta, dict) else None
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise StreamError("Girdide YYYY-MM-DD biçiminde meta.date yok.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise StreamError(f"meta.date geçerli bir tarih değil: {value}") from None


def parse_from(value: str | None, day: date) -> datetime:
    match = FROM_RE.match(value or "")
    if not match:
        raise StreamError("--from HH:MM biçiminde, 00:00–23:59 arasında olmalı.")
    hour, minute = int(match.group(1)), int(match.group(2))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def parse_speed(value: str) -> float:
    try:
        speed = float(value)
    except ValueError:
        raise StreamError(f"--speed bir sayı olmalı: {value}") from None
    # nan da bu kontrolden geçemez.
    if not speed > 0:
        raise StreamError("--speed 0'dan büyük olmalı.")
    return speed


def select(data: dict, start: datetime) -> list[tuple[datetime, dict]]:
    """--from ve sonrasındaki kayıtları (ts, flight_id) sırasıyla döndürür."""
    positions = data.get("positions")
    if not isinstance(positions, list):
        raise StreamError("Girdide positions listesi yok.")
    selected = []
    for record in positions:
        try:
            ts = datetime.fromisoformat(record["ts"])
            flight_id = record["flight_id"]
        except (TypeError, KeyError, ValueError):
            raise StreamError(f"Geçersiz konum kaydı: {record!r}") from None
        if ts.tzinfo is None:
            raise StreamError(f"Konum zamanında saat dilimi yok: {record['ts']}")
        if ts >= start:
            selected.append((ts, flight_id, record))
    # ts zaman olarak karşılaştırılır; eşit anlar flight_id ile sıralanır.
    selected.sort(key=lambda item: (item[0], item[1]))
    return [(ts, record) for ts, _, record in selected]


def emit(
    selected: list[tuple[datetime, dict]], start: datetime, speed: float, wait: bool
):
    out = sys.stdout.buffer
    started = time.perf_counter()
    index = 0
    while index < len(selected):
        ts = selected[index][0]
        if wait:
            # Hedef an başlangıçtan hesaplanır; bekleme süreleri toplanmadığı için kayma birikmez.
            due = started + (ts - start).total_seconds() / speed
            delay = due - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        while index < len(selected) and selected[index][0] == ts:
            record = selected[index][1]
            out.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
            index += 1
        out.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Konum kayıtlarını simüle zamanla akıtır."
    )
    parser.add_argument(
        "--in", dest="input", help="Üreteç ya da bozulma çıktısı (JSON)"
    )
    parser.add_argument("--from", dest="start", help="Simüle başlangıç saati, HH:MM")
    parser.add_argument(
        "--speed", default=str(DEFAULT_SPEED), help="Simüle sn / gerçek sn"
    )
    parser.add_argument("--no-wait", action="store_true", help="Beklemeden yaz")
    args = parser.parse_args(argv)

    # Tüm doğrulama ilk satırdan önce yapılır; hata durumunda stdout boş kalır.
    try:
        if not args.input:
            raise StreamError("--in verilmeli.")
        data = load_input(args.input)
        day = parse_day(data)
        start = parse_from(args.start, day)
        speed = parse_speed(args.speed)
        selected = select(data, start)
    except StreamError as error:
        print(f"Hata: {error}", file=sys.stderr)
        return 1

    try:
        emit(selected, start, speed, wait=not args.no_wait)
    except BrokenPipeError:
        # Okuyan taraf kapandı (ör. Select-Object -First); sessizce bit.
        return 0
    except KeyboardInterrupt:
        return 130

    first = selected[0][1]["ts"] if selected else "-"
    last = selected[-1][1]["ts"] if selected else "-"
    print(f"yayınlanan={len(selected)} ilk={first} son={last}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
