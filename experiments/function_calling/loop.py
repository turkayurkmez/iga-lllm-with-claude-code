"""get_flight_summary tool'unu gerçekten çalıştıran tool kullanım döngüsü.

Model tool isterse sayılar her çağrıda referans gün verisinden hesaplanır ve
tool_result olarak geri verilir. Döngü en fazla MAX_TOUR API çağrısı sürer.

Repo kökünden çalıştırın: python experiments/function_calling/loop.py
"""

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Script doğrudan çalıştırıldığında sys.path[0] bu klasör olur; backend paketinin
# bulunabilmesi için repo kökünü ekliyoruz.
sys.path.insert(0, str(ROOT))

from backend.llm import MODEL, client

logger = logging.getLogger(__name__)

QUESTION = "Bugün kaç uçuş var"
DATA_FILE = ROOT / "data" / "referans" / "seed42-2026-10-20.json"
MAX_TOUR = 5

# direction değerinin movements.movement_type karşılığı; None tümünü kapsar.
DIRECTIONS = {"all": None, "arrival": "ARRIVAL", "departure": "DEPARTURE"}

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
                "enum": list(DIRECTIONS),
                "description": "all: tüm uçuşlar, arrival: gelen, departure: giden.",
            },
        },
        "required": ["direction"],
    },
}


class ToolError(Exception):
    """Modele is_error ile dönecek, ayrıntı içermeyen tool hatası."""


def get_flight_summary(direction: object) -> dict:
    if direction not in DIRECTIONS:
        raise ToolError(
            "Geçersiz direction; 'all', 'arrival' ya da 'departure' olmalı."
        )

    # Sayılar her çağrıda dosyadan yeniden hesaplanır; önbellek yok.
    try:
        with DATA_FILE.open(encoding="utf-8") as file:
            data = json.load(file)
        movement_type = DIRECTIONS[direction]
        flight_ids = {
            m["flight_id"]
            for m in data["movements"]
            if movement_type is None or m["movement_type"] == movement_type
        }
        cancelled = sum(
            1
            for f in data["flights"]
            if f["flight_id"] in flight_ids and f["cancelled"]
        )
        delayed = len({d["flight_id"] for d in data["delays"]} & flight_ids)
        date = data["meta"]["date"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.exception("Uçuş verisi okunamadı: %s", DATA_FILE)
        raise ToolError("Uçuş verisi şu anda okunamıyor.") from exc

    return {
        "date": date,
        "direction": direction,
        "total": len(flight_ids),
        "cancelled": cancelled,
        "delayed": delayed,
    }


TOOLS = {"get_flight_summary": get_flight_summary}


def run_tool(block) -> dict:
    """tool_use bloğunu çalıştırır ve aynı id ile eşleşen tool_result döndürür."""
    result = {"type": "tool_result", "tool_use_id": block.id}
    try:
        tool = TOOLS.get(block.name)
        if tool is None:
            raise ToolError(f"Bilinmeyen tool: {block.name}")
        if not isinstance(block.input, dict):
            raise ToolError("Tool girdisi bir nesne olmalı.")
        output = tool(block.input.get("direction"))
    except ToolError as exc:
        logger.warning("Tool hatası (%s): %s", block.name, exc)
        result["content"] = str(exc)
        result["is_error"] = True
        return result
    result["content"] = json.dumps(output, ensure_ascii=False)
    return result


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    messages = [{"role": "user", "content": QUESTION}]

    for tour in range(1, MAX_TOUR + 1):
        response = client.messages.create(
            model=MODEL,
            # Thinking de çıktı token'ı harcadığı için düşük bir sınır yanıtı kesebilir.
            max_tokens=16000,
            tools=[FLIGHT_SUMMARY_TOOL],
            messages=messages,
        )
        print(f"Tur {tour}:")
        for index, block in enumerate(response.content):
            print(f"  [{index}] {block.type}")
        print(f"  stop_reason: {response.stop_reason}")

        if response.stop_reason != "tool_use":
            # Yanıtta thinking blokları da olabilir; yalnızca metin bloklarını alıyoruz.
            answer = "".join(
                block.text for block in response.content if block.type == "text"
            )
            print(f"Yanıt: {answer}")
            return

        # Thinking blokları da dahil içerik olduğu gibi geçmişe eklenir.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = run_tool(block)
            tool_input = json.dumps(block.input, ensure_ascii=False)
            print(f"  -> {block.name}({tool_input}) [{block.id}]")
            print(f"  <- {result['content']} is_error={result.get('is_error', False)}")
            results.append(result)
        messages.append({"role": "user", "content": results})

    print(f"Uyarı: {MAX_TOUR} tur içinde son yanıt alınamadı; döngü durduruldu.")


if __name__ == "__main__":
    main()
