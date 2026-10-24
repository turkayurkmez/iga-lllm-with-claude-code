"""sonuc_once.json ve sonuc_sonra.json'u soru başına yan yana karşılaştırır.

Model çağrılmaz; yalnızca olc.py'nin yazdığı raporlar okunur.

Repo kökünden çalıştırın: python experiments/function_calling/compare.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BEFORE_FILE = HERE / "sonuc_once.json"
AFTER_FILE = HERE / "sonuc_sonra.json"


def load_report(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as file:
            report = json.load(file)
        # Gerekli alanlar burada denetlenir; tablo yazılmaya başlamadan hata verilir.
        report["by_id"] = {q["id"]: q["correct"] for q in report["questions"]}
        float(report["accuracy"])
        int(report["repeats"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"Hata: {path.name} okunamadı: {exc}") from None
    return report


def id_key(question_id: str) -> tuple:
    # S2'nin S10'dan önce gelmesi için sayısal kısma göre sıralanır.
    digits = "".join(ch for ch in question_id if ch.isdigit())
    return (int(digits) if digits else 0, question_id)


def main() -> None:
    try:
        before = load_report(BEFORE_FILE)
        after = load_report(AFTER_FILE)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    same_repeats = before["repeats"] == after["repeats"]
    rows = [("ID", "Önce", "Sonra", "Fark")]
    ids = sorted(before["by_id"].keys() | after["by_id"].keys(), key=id_key)
    for qid in ids:
        old = before["by_id"].get(qid)
        new = after["by_id"].get(qid)
        old_cell = "-" if old is None else f"{old}/{before['repeats']}"
        new_cell = "-" if new is None else f"{new}/{after['repeats']}"
        if old is None or new is None or not same_repeats:
            diff = "?"
        else:
            diff = f"{new - old:+d}"
        rows.append((qid, old_cell, new_cell, diff))

    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))

    old_acc = before["accuracy"] * 100
    new_acc = after["accuracy"] * 100
    print()
    print(f"Genel: {old_acc:.1f}% -> {new_acc:.1f}%  ({new_acc - old_acc:+.1f} puan)")
    if not same_repeats:
        print(
            f"Not: tekrar sayıları farklı ({before['repeats']} / {after['repeats']});"
            " soru başına fark yazılmadı."
        )


if __name__ == "__main__":
    main()
