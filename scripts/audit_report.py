"""Audit kayıtlarını okur ve özetler (docs/audit.md › Okuma scripti).

- Parametresiz: tüm günlerden en yeni 5 soru; içlerinde thumbs down alanlar önce.
- --id: bir sorunun yolculuğu (soru → tool çağrıları → çipler → cevap → geri bildirim).
  Kimlik tam audit_id ya da en az 6 karakterlik benzersiz önekidir.
- --tarih: o günün bütün soruları, thumbs down alanlar önce; soru → cevap → geri bildirim.

Kayıtları yalnızca okur; model ya da API çağrısı yapmaz. Klasör COPILOT_AUDIT_DIR,
boşsa logs/audit. Repo kökünden çalıştırın:
$env:PYTHONIOENCODING="utf-8"; python scripts/audit_report.py [--id KİMLİK | --tarih YYYY-MM-DD]
"""

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import audit

LATEST = 5
ANSWER_LIMIT = 80
MIN_PREFIX = 6
ID_PATTERN = re.compile(r"^[0-9a-f]+$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NO_RECORDS = "Kayıt yok."
NO_ANSWER = "(cevap yok)"


class ReportError(Exception):
    """Kullanıcıya "Hata: ..." olarak gösterilen, 1 ile çıkışa yol açan hata."""


def read_records(directory: Path) -> tuple[list[tuple[str, dict]], list[dict]]:
    """Klasördeki (dosya günü, question) çiftleri ve tüm feedback satırları."""
    if not directory.is_dir():
        raise ReportError(f"Audit klasörü bulunamadı: {directory}")
    questions: list[tuple[str, dict]] = []
    feedbacks: list[dict] = []
    for path in sorted(directory.glob("*.jsonl")):
        lines = path.read_text(encoding="utf-8").split("\n")
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                print(f"Uyarı: {path}:{number} okunamadı.", file=sys.stderr)
                continue
            if not isinstance(record, dict):
                print(f"Uyarı: {path}:{number} okunamadı.", file=sys.stderr)
            elif record.get("type") == "question":
                questions.append((path.stem, record))
            elif record.get("type") == "feedback":
                feedbacks.append(record)
    return questions, feedbacks


def feedback_index(feedbacks: list[dict]) -> dict[str, list[str]]:
    """audit_id → geri bildirim zamanları; gün dosyasından bağımsız eşleşir."""
    index: dict[str, list[str]] = {}
    for record in feedbacks:
        index.setdefault(record.get("audit_id"), []).append(record.get("ts", ""))
    return index


def moment(record: dict) -> datetime:
    return datetime.fromisoformat(record["ts"])


def prioritized(questions: list[dict], negatives: dict[str, list[str]]) -> list[dict]:
    """Thumbs down alanlar önce, sonra kalanlar; ikisi de yeniden eskiye."""
    newest = sorted(questions, key=moment, reverse=True)
    return [q for q in newest if q["audit_id"] in negatives] + [
        q for q in newest if q["audit_id"] not in negatives
    ]


def answer_text(record: dict) -> str:
    answer = record.get("answer")
    return NO_ANSWER if answer is None else answer


def indented(text: str, width: int) -> str:
    """Çok satırlı metnin devam satırlarını etiketin hizasına kaydırır."""
    return text.replace("\n", "\n" + " " * width)


def summary_line(record: dict, negatives: dict[str, list[str]]) -> str:
    answer = answer_text(record).replace("\n", " ")
    if len(answer) > ANSWER_LIMIT:
        answer = answer[:ANSWER_LIMIT] + "…"
    flag = "  [olumsuz]" if record["audit_id"] in negatives else ""
    stamp = f"{record['ts'][:10]} {record['ts'][11:16]}"
    return (
        f"{stamp}  {record['audit_id'][:8]}  {record['status']}{flag}  "
        f"{record['question']}  → {answer}"
    )


def feedback_lines(record: dict, negatives: dict[str, list[str]]) -> list[str]:
    times = negatives.get(record["audit_id"], [])
    if not times:
        return ["  Geri bildirim yok."]
    return [f"  Geri bildirim: olumsuz — {ts}" for ts in times]


def latest(questions: list[dict], negatives: dict[str, list[str]]) -> list[str]:
    newest = sorted(questions, key=moment, reverse=True)[:LATEST]
    return [summary_line(q, negatives) for q in prioritized(newest, negatives)]


def call_line(call: dict) -> str:
    args = json.dumps(call.get("input"), ensure_ascii=False)
    head = f"    {call.get('turn')}. tur  {call.get('name')} {args}"
    if not call.get("executed"):
        return f"{head} — çalıştırılmadı"
    stale = "eski işaretli" if call.get("stale") else "eski değil"
    error = call.get("error_code") or "yok"
    return (
        f"{head} — çalıştı; kaynak {call.get('source')}, "
        f"veri zamanı {call.get('as_of')}, {stale}, hata {error}"
    )


def chip_line(chip: dict) -> str:
    parts = [str(chip.get("tool")), str(chip.get("source")), str(chip.get("as_of"))]
    if chip.get("stale"):
        parts.append("eski işaretli")
    if chip.get("error_code"):
        parts.append(str(chip["error_code"]))
    return "    - " + " · ".join(parts)


def journey(record: dict, negatives: dict[str, list[str]]) -> list[str]:
    instruction = record.get("instruction") or {}
    status = record["status"]
    if record.get("reason"):
        status += f" ({record['reason']})"
    calls = record.get("tool_calls") or []
    chips = record.get("chips") or []
    client = (
        "akışı yarıda kesti"
        if record.get("client_disconnected")
        else "akışı sonuna kadar aldı"
    )
    instruction_text = f"{instruction.get('name')} ({instruction.get('version')})"
    return [
        f"Soru {record['audit_id']}",
        f"  Zaman:   {record['ts']}",
        f"  Soru:    {record['question']}",
        f"  Talimat: {instruction_text}, model {record.get('model')}",
        "  Tool çağrıları:" if calls else "  Tool çağrısı yok.",
        *(call_line(call) for call in calls),
        "  Çipler:" if chips else "  Çip yok.",
        *(chip_line(chip) for chip in chips),
        f"  Durum:   {status}",
        f"  Cevap:   {indented(answer_text(record), 11)}",
        f"  İstemci: {client}",
        *feedback_lines(record, negatives),
    ]


def find(questions: list[dict], key: str) -> dict:
    if len(key) < MIN_PREFIX:
        raise ReportError(f"Kimlik en az {MIN_PREFIX} karakter olmalı: {key!r}")
    if not ID_PATTERN.match(key):
        raise ReportError(f"Kimlik küçük harf hex olmalı: {key!r}")
    matches = [q for q in questions if q["audit_id"].startswith(key)]
    if not matches:
        raise ReportError(f"Bu kimlikle soru bulunamadı: {key}")
    if len(matches) > 1:
        ids = "\n".join(f"  {q['audit_id']}" for q in matches)
        raise ReportError(f"Kimlik birden çok soruya uyuyor: {key}\n{ids}")
    return matches[0]


def day_block(record: dict, negatives: dict[str, list[str]]) -> list[str]:
    flag = "  [olumsuz]" if record["audit_id"] in negatives else ""
    return [
        f"{record['audit_id'][:8]}  {record['ts'][11:16]}  {record['status']}{flag}",
        f"  Soru:  {record['question']}",
        f"  Cevap: {indented(answer_text(record), 9)}",
        *feedback_lines(record, negatives),
        "",
    ]


def parse_day(value: str) -> str:
    try:
        if not DATE_PATTERN.match(value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise ReportError(f"Tarih YYYY-MM-DD biçiminde olmalı: {value!r}") from None
    return value


def report(args: argparse.Namespace) -> list[str]:
    day = None if args.tarih is None else parse_day(args.tarih)
    pairs, feedbacks = read_records(audit.audit_dir())
    negatives = feedback_index(feedbacks)
    questions = [record for _, record in pairs]

    if args.id is not None:
        return journey(find(questions, args.id), negatives)
    if day is not None:
        selected = [record for stem, record in pairs if stem == day]
        if not selected:
            return [NO_RECORDS]
        return [
            line
            for record in prioritized(selected, negatives)
            for line in day_block(record, negatives)
        ]
    return latest(questions, negatives) if questions else [NO_RECORDS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit kayıtlarını özetler.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--id", help="audit_id ya da en az 6 karakterlik öneki")
    group.add_argument("--tarih", help="YYYY-MM-DD; o günün soruları")
    args = parser.parse_args(argv)
    try:
        lines = report(args)
    except ReportError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines).rstrip("\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
