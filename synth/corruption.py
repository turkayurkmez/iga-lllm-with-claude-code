"""Üreteç çıktısını bilinçli olarak bozar (docs/bozulma.md).

Repo kökünden çalıştırın:
    python -m synth.corruption --in girdi.json --scenario S --out çıktı.json
        [--flight-no TK2345] [--field tablo.alan]

Rastgelelik yoktur; aynı girdi ve argümanlar birebir aynı çıktıyı verir. Girdi dosyası
değiştirilmez; hata durumunda çıktı dosyası yazılmaz.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCENARIOS = (
    "stale_position",
    "duplicate_callsign",
    "missing_field",
    "undefined_flight",
)
DEFAULT_FLIGHT_NO = "TK2345"
DEFAULT_FIELD = "flights.estimated_time"
# missing_field yalnızca hedefle flight_id üzerinden doğrudan eşleşen tablolarda çalışır.
FIELD_TABLES = ("flights", "movements", "delays")
KEY_FIELD = "flight_id"
STALE_WINDOW = timedelta(minutes=10)


class CorruptionError(Exception):
    """Bozulma uygulanamadığında fırlatılır; mesaj kullanıcıya gösterilir."""


def find_target(data: dict, flight_no: str) -> dict:
    matches = [f for f in data["flights"] if f["flight_no"] == flight_no]
    if not matches:
        raise CorruptionError(f"'{flight_no}' sefer no'lu uçuş bulunamadı.")
    if len(matches) > 1:
        raise CorruptionError(
            f"'{flight_no}' sefer no'su birden fazla uçuşla eşleşiyor."
        )
    return matches[0]


def stale_position(data: dict, target: dict) -> int:
    """Hedefin izinde son konumdan önceki 10 dakika dışındaki noktaları bırakır."""
    flight_id = target["flight_id"]
    track = [p for p in data["positions"] if p["flight_id"] == flight_id]
    if not track:
        raise CorruptionError(
            f"{flight_id} için konum izi yok (uçuş iptal edilmiş olabilir)."
        )
    cutoff = max(datetime.fromisoformat(p["ts"]) for p in track) - STALE_WINDOW
    before = len(data["positions"])
    data["positions"] = [
        p
        for p in data["positions"]
        if p["flight_id"] != flight_id or datetime.fromisoformat(p["ts"]) <= cutoff
    ]
    return before - len(data["positions"])


def duplicate_callsign(data: dict, target: dict) -> int:
    """flight_id sırasına göre ilk uygun departure'a hedefin callsign'ını verir."""
    departures = {
        m["flight_id"] for m in data["movements"] if m["movement_type"] == "DEPARTURE"
    }
    candidates = [
        f
        for f in data["flights"]
        if f["flight_id"] != target["flight_id"]
        and not f["cancelled"]
        and f["flight_id"] in departures
    ]
    if not candidates:
        raise CorruptionError(
            "Callsign'ı kopyalanacak, iptal edilmemiş ikinci bir departure yok."
        )
    other = min(candidates, key=lambda f: f["flight_id"])
    other["callsign"] = target["callsign"]
    return 1


def missing_field(data: dict, target: dict, field: str) -> int:
    """Hedefin kaydından verilen alanı anahtarıyla birlikte kaldırır."""
    parts = field.split(".")
    if len(parts) != 2 or not all(parts):
        raise CorruptionError(f"--field 'tablo.alan' biçiminde olmalı: '{field}'.")
    table, name = parts
    if table not in FIELD_TABLES:
        raise CorruptionError(
            f"--field tablosu şunlardan biri olmalı: {', '.join(FIELD_TABLES)}."
        )
    if name == KEY_FIELD:
        raise CorruptionError(f"Anahtar alan ({KEY_FIELD}) kaldırılamaz.")
    records = [r for r in data[table] if r[KEY_FIELD] == target[KEY_FIELD]]
    if not records:
        raise CorruptionError(
            f"{target['flight_id']} için '{table}' tablosunda kayıt yok."
        )
    (record,) = records
    if name not in record:
        raise CorruptionError(f"'{table}' kaydında '{name}' alanı yok.")
    del record[name]
    return 1


def undefined_flight(data: dict, target: dict) -> int:
    """Hedefin flights kaydını siler; diğer tablolardaki kayıtları yetim kalır."""
    data["flights"] = [
        f for f in data["flights"] if f["flight_id"] != target["flight_id"]
    ]
    return 1


def apply(
    data: dict, scenario: str, flight_no: str, field: str | None
) -> tuple[dict, int]:
    """Senaryoyu veriye uygular; hedef uçuşu ve etkilenen kayıt sayısını döndürür."""
    if field is not None and scenario != "missing_field":
        raise CorruptionError("--field yalnızca missing_field senaryosunda kullanılır.")
    target = find_target(data, flight_no)
    if scenario == "stale_position":
        affected = stale_position(data, target)
    elif scenario == "duplicate_callsign":
        affected = duplicate_callsign(data, target)
    elif scenario == "missing_field":
        affected = missing_field(data, target, field or DEFAULT_FIELD)
    else:
        affected = undefined_flight(data, target)
    return target, affected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Üreteç çıktısını bilinçli olarak bozar."
    )
    parser.add_argument(
        "--in", dest="input", type=Path, required=True, help="Girdi JSON"
    )
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Çıktı JSON")
    parser.add_argument("--flight-no", default=DEFAULT_FLIGHT_NO)
    parser.add_argument(
        "--field", default=None, help="tablo.alan (yalnızca missing_field)"
    )
    args = parser.parse_args(argv)

    try:
        if args.out.resolve() == args.input.resolve():
            raise CorruptionError("--out, --in ile aynı dosya olamaz.")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        target, affected = apply(data, args.scenario, args.flight_no, args.field)
    except CorruptionError as error:
        print(f"Hata: {error}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Üreteçle aynı yazım biçimi: girdi ile çıktı arasında yalnızca bozulma farkı kalır.
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"senaryo={args.scenario} flight_id={target['flight_id']} "
        f"flight_no={target['flight_no']} etkilenen={affected}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
