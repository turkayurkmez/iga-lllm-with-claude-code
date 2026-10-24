"""Tool seçim doğruluğunu ölçer.

sorular.json'daki her soru REPEATS kez, tek API çağrısıyla sorulur; tool
çalıştırılmaz. İlk yanıttaki tool_use adlarının kümesi beklenen kümeyle tam
eşleşirse deneme doğru sayılır.

Repo kökünden çalıştırın:
    python experiments/function_calling/olc.py <tool_dosyası> <çıktı_yolu>
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Script doğrudan çalıştırıldığında sys.path[0] bu klasör olur; backend paketinin
# bulunabilmesi için repo kökünü ekliyoruz.
sys.path.insert(0, str(HERE.parents[1]))

import anthropic

from backend.llm import MODEL, client

QUESTIONS_FILE = HERE / "sorular.json"
REPEATS = 3


def load_json(path: Path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def ask(question: str, tools: list[dict]) -> dict:
    """Soruyu bir kez sorar; çağrılan tool adlarını ve stop_reason'ı döndürür."""
    try:
        response = client.messages.create(
            model=MODEL,
            # Thinking de çıktı token'ı harcadığı için düşük bir sınır yanıtı kesebilir.
            max_tokens=16000,
            tools=tools,
            messages=[{"role": "user", "content": question}],
        )
    except anthropic.APIError as exc:
        # Ayrıntı yerine yalnızca hata türü kaydedilir; deneme yanlış sayılır.
        return {"tools": None, "stop_reason": None, "error": type(exc).__name__}
    called = sorted({b.name for b in response.content if b.type == "tool_use"})
    return {"tools": called, "stop_reason": response.stop_reason, "error": None}


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool seçim doğruluğu ölçümü")
    parser.add_argument("tools_file", type=Path, help="Tool tanımları (JSON liste)")
    parser.add_argument("out", type=Path, help="Sonuç dosyası (JSON)")
    args = parser.parse_args()

    tools = load_json(args.tools_file)
    questions = load_json(QUESTIONS_FILE)

    results = []
    total_correct = 0
    for item in questions:
        expected = sorted(item["expected"])
        attempts = []
        for _ in range(REPEATS):
            attempt = ask(item["question"], tools)
            attempt["correct"] = attempt["tools"] == expected
            attempts.append(attempt)
        correct = sum(a["correct"] for a in attempts)
        total_correct += correct
        results.append(
            {
                "id": item["id"],
                "question": item["question"],
                "expected": expected,
                "correct": correct,
                "attempts": attempts,
            }
        )
        print(f"{item['id']}: {correct}/{REPEATS}  beklenen={expected}  ", end="")
        print("çağrılan=" + " | ".join(str(a["tools"]) for a in attempts))

    total = len(questions) * REPEATS
    report = {
        "model": MODEL,
        "tools_file": args.tools_file.as_posix(),
        "repeats": REPEATS,
        "correct": total_correct,
        "total": total,
        "accuracy": round(total_correct / total, 3),
        "questions": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(f"Toplam: {total_correct}/{total} ({report['accuracy']:.1%}) -> {args.out}")


if __name__ == "__main__":
    main()
