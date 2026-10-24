"""Aynı soruyu önce tool'suz, sonra get_flight_summary tool'uyla sorar.

Tool çalıştırılmaz; yalnızca yanıttaki blokların türleri ve stop_reason yazdırılır.

Repo kökünden çalıştırın: python experiments/function_calling/single_call.py
"""

import json
import sys
from pathlib import Path

# Script doğrudan çalıştırıldığında sys.path[0] bu klasör olur; backend paketinin
# bulunabilmesi için repo kökünü ekliyoruz.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.llm import MODEL, client

QUESTION = "Bugün kaç uçuş var"

FLIGHT_SUMMARY_TOOL = {
    "name": "get_flight_summary",
    "description": (
        "Bugünkü uçuşların sayısal özetini döndürür. Uçuş sayısı sorulduğunda "
        "kullanılır; yön belirtilmezse 'all' verilir."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["all", "arrival", "departure"],
                "description": "all: tüm uçuşlar, arrival: gelen, departure: giden.",
            },
        },
        "required": ["direction"],
    },
}


def ask(tools: list[dict] | None) -> None:
    kwargs = {"tools": tools} if tools else {}
    response = client.messages.create(
        model=MODEL,
        # Thinking de çıktı token'ı harcadığı için düşük bir sınır yanıtı kesebilir.
        max_tokens=16000,
        messages=[{"role": "user", "content": QUESTION}],
        **kwargs,
    )

    for index, block in enumerate(response.content):
        line = f"  [{index}] {block.type}"
        if block.type == "tool_use":
            tool_input = json.dumps(block.input, ensure_ascii=False)
            line += f" -> {block.name}({tool_input})"
        print(line)
    print(f"  stop_reason: {response.stop_reason}")


def main() -> None:
    print("Tool'suz:")
    ask(None)
    print("get_flight_summary ile:")
    ask([FLIGHT_SUMMARY_TOOL])


if __name__ == "__main__":
    main()
