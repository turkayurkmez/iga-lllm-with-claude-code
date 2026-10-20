"""flight_info ve search tool'larını zarfla döndüren tool kullanım döngüsü.

loop.py ile aynı döngüdür; farkı, her tool sonucunun backend/envelope.py ile zarflanıp
modele zarfın tamamının JSON olarak verilmesidir (sözleşme: docs/zarf.md). Tool
tanımları araclar_iyi.json'dan okunur; sayılar ve kayıtlar --veri dosyasından
hesaplanır. is_error yalnızca SCHEMA_VALIDATION_FAILED'da true'dur. Döngü en fazla
MAX_TOUR API çağrısı sürer.

Repo kökünden çalıştırın:
python experiments/function_calling/loop_envelope.py [--soru "..."] [--veri dosya.json]
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]

# Script doğrudan çalıştırıldığında sys.path[0] bu klasör olur; backend paketinin
# bulunabilmesi için repo kökünü ekliyoruz.
sys.path.insert(0, str(ROOT))

from backend.envelope import ErrorCode, ToolSpec, call_tool
from backend.llm import MODEL, client

logger = logging.getLogger(__name__)

DEFAULT_QUESTION = "Bugün kaç uçuş var"
DEFAULT_DATA_FILE = ROOT / "data" / "referans" / "seed42-2026-10-20.json"
TOOLS_FILE = Path(__file__).resolve().parent / "araclar_iyi.json"
MAX_TOUR = 5
TOOL_VERSION = "1.0.0"

FLIGHT_FIELDS = (
    "flight_no",
    "callsign",
    "registration",
    "aircraft_type",
    "origin",
    "destination",
    "scheduled_time",
    "estimated_time",
    "cancelled",
)
MOVEMENT_FIELDS = ("movement_type", "stand_code", "gate_code")


class FlightInfoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    movement_type: Literal["ALL", "ARRIVAL", "DEPARTURE"]


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flight_no: str


ARGS_MODELS = {"flight_info": FlightInfoArgs, "search": SearchArgs}


def check_definitions(definitions: list[dict]) -> None:
    """araclar_iyi.json ile argüman modellerinin aynı parametreleri tanımladığını denetler."""
    names = [d["name"] for d in definitions]
    if sorted(names) != sorted(ARGS_MODELS):
        raise ValueError(f"Tool adları beklenenle aynı değil: {names}")
    for definition in definitions:
        schema = definition["input_schema"]
        model_schema = ARGS_MODELS[definition["name"]].model_json_schema()
        if set(schema["properties"]) != set(model_schema["properties"]) or set(
            schema.get("required", [])
        ) != set(model_schema.get("required", [])):
            raise ValueError(f"{definition['name']} parametreleri modelle aynı değil.")
        for prop, spec in schema["properties"].items():
            if spec.get("enum") != model_schema["properties"][prop].get("enum"):
                raise ValueError(
                    f"{definition['name']}.{prop} enum'u modelle aynı değil."
                )


def build_registry(data: dict, source: str) -> dict[str, ToolSpec]:
    """Veri dosyasına bağlı tool'ları zarf katmanının kaydı olarak kurar."""

    def flight_info(movement_type: str) -> dict:
        flight_ids = {
            m["flight_id"]
            for m in data["movements"]
            if movement_type == "ALL" or m["movement_type"] == movement_type
        }
        cancelled = sum(
            1
            for f in data["flights"]
            if f["flight_id"] in flight_ids and f["cancelled"]
        )
        delayed = len({d["flight_id"] for d in data["delays"]} & flight_ids)
        value = {
            "date": data["meta"]["date"],
            "movement_type": movement_type,
            "total": len(flight_ids),
            "cancelled": cancelled,
            "delayed": delayed,
        }
        return {"value": value, "source": source}

    def search(flight_no: str) -> dict:
        matches = [f for f in data["flights"] if f.get("flight_no") == flight_no]
        movements = {m["flight_id"]: m for m in data["movements"]}

        def record(flight: dict) -> dict:
            # Kayıtta olmayan alan value'ya yazılmaz (docs/zarf.md › Eksik alan).
            movement = movements.get(flight["flight_id"], {})
            fields = [(flight, FLIGHT_FIELDS), (movement, MOVEMENT_FIELDS)]
            return {k: row[k] for row, keys in fields for k in keys if k in row}

        if not matches:
            error = {
                "code": ErrorCode.NOT_FOUND,
                "message": "Bu sefer numarasıyla uçuş bulunamadı.",
            }
            return {"value": None, "source": source, "error": error}
        if len(matches) > 1:
            error = {
                "code": ErrorCode.AMBIGUOUS_ENTITY,
                "message": "Bu sefer numarası birden fazla uçuşla eşleşiyor.",
            }
            return {
                "value": [record(f) for f in matches],
                "source": source,
                "error": error,
            }
        return {"value": record(matches[0]), "source": source}

    funcs = {"flight_info": flight_info, "search": search}
    return {
        name: ToolSpec(
            name=name,
            version=TOOL_VERSION,
            func=funcs[name],
            args_model=ARGS_MODELS[name],
        )
        for name in ARGS_MODELS
    }


def run_tool(registry: dict[str, ToolSpec], block) -> tuple[dict, dict]:
    """tool_use bloğunu zarflar; aynı id'li tool_result ile zarfı döndürür."""
    envelope = call_tool(registry, block.name, block.input)
    error = envelope["error"]
    is_error = error is not None and error["code"] == ErrorCode.SCHEMA_VALIDATION_FAILED
    result = {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": json.dumps(envelope, ensure_ascii=False),
        "is_error": is_error,
    }
    return result, envelope


def display_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT):
        return resolved.relative_to(ROOT).as_posix()
    return resolved.as_posix()


def print_summary(answer: str, calls: list[dict]) -> None:
    print()
    print("Cevap:")
    print(answer or "(cevap yok)")
    print()
    print("Zarflar:")
    if not calls:
        print("(tool çağrılmadı)")
    for index, call in enumerate(calls, start=1):
        tool_input = json.dumps(call["input"], ensure_ascii=False)
        print(f"[{index}] {call['name']}({tool_input})")
        print(json.dumps(call["envelope"], ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--soru", default=DEFAULT_QUESTION, help="Modele sorulacak soru."
    )
    parser.add_argument(
        "--veri", type=Path, default=DEFAULT_DATA_FILE, help="Üreteç çıktısı JSON."
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    # Doğrulama ilk API çağrısından önce yapılır; hata varsa çağrı yapılmaz.
    try:
        with args.veri.open(encoding="utf-8") as file:
            data = json.load(file)
        for key in ("flights", "movements", "delays"):
            if not isinstance(data.get(key), list):
                raise TypeError(f"'{key}' listesi yok")
        if not isinstance(data["meta"]["date"], str):
            raise TypeError("'meta.date' yok")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"Hata: veri dosyası okunamadı ({args.veri}): {exc}", file=sys.stderr)
        return 1
    try:
        with TOOLS_FILE.open(encoding="utf-8") as file:
            definitions = json.load(file)
        check_definitions(definitions)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            f"Hata: tool tanımları geçersiz ({TOOLS_FILE.name}): {exc}", file=sys.stderr
        )
        return 1

    registry = build_registry(data, display_path(args.veri))
    messages = [{"role": "user", "content": args.soru}]
    calls = []

    for tour in range(1, MAX_TOUR + 1):
        response = client.messages.create(
            model=MODEL,
            # Thinking de çıktı token'ı harcadığı için düşük bir sınır yanıtı kesebilir.
            max_tokens=16000,
            tools=definitions,
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
            print_summary(answer, calls)
            return 0

        # Thinking blokları da dahil içerik olduğu gibi geçmişe eklenir.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result, envelope = run_tool(registry, block)
            code = envelope["error"]["code"] if envelope["error"] else None
            print(
                f"  -> {block.name} [{block.id}] error={code} is_error={result['is_error']}"
            )
            calls.append(
                {"name": block.name, "input": block.input, "envelope": envelope}
            )
            results.append(result)
        messages.append({"role": "user", "content": results})

    print(f"Uyarı: {MAX_TOUR} tur içinde son yanıt alınamadı; döngü durduruldu.")
    print_summary("", calls)
    return 1


if __name__ == "__main__":
    sys.exit(main())
