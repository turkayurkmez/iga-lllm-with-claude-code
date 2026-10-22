"""Bir soruyu agent döngüsünden (backend/agent.py) geçirir ya da sınır vakalarını oynatır.

Her tur için istenen tool'ları (argüman, çalıştı mı, hata kodu), stop_reason'u ve
token sayılarını, sonda durumu ve son cevabı yazdırır.

- Soru verilirse gerçek modelle çalışır; her çalıştırma birkaç ücretli API çağrısı
  yapar (en fazla agent.MAX_TURNS).
- --vaka ile docs/agent.md › Durumlar ve Sınırlar'daki vakalar, model yanıtları
  script'te hazır bir sahte istemciyle oynatılır; API çağrısı yapılmaz, tool'lar
  gerçek run_tool ile çalışır. Her vaka beklenen durum ve "çalıştı mı" deseniyle
  karşılaştırılır; uymayan vaka varsa script 1 ile çıkar.

COPILOT_DATA ortamda ya da .env'de yoksa referans gün verisi kullanılır.

Repo kökünden çalıştırın:
python scripts/agent_run.py "Bugün kaç uçuş var?"
python scripts/agent_run.py --vaka liste | hepsi | <vaka adı>
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

ROOT = Path(__file__).resolve().parent.parent

# Script doğrudan çalıştırıldığında sys.path[0] scripts/ olur; backend paketinin
# bulunabilmesi için repo kökünü ekliyoruz.
sys.path.insert(0, str(ROOT))

from backend import llm
from backend.agent import AgentResult, run_agent

DEFAULT_DATA = "data/referans/seed42-2026-10-20.json"
SUMMARY = "get_flight_summary"
RESOLVE = "resolve_flight_identity"


class UsageRecorder:
    """Gerçek istemciyi sarar; her messages.create yanıtının usage'ını saklar."""

    def __init__(self, client):
        self._client = client
        self.usages = []
        self.messages = self

    def create(self, **kwargs):
        response = self._client.messages.create(**kwargs)
        self.usages.append(response.usage)
        return response


class ScriptedClient:
    """Hazır model yanıtlarını sırayla döndüren sahte istemci; API çağırmaz."""

    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self.messages = self

    def create(self, **kwargs) -> Message:
        if not self._responses:
            raise RuntimeError("Senaryodaki model yanıtları bitti.")
        return self._responses.pop(0)


def model_turn(
    index: int, stop_reason: str, *calls: tuple[str, dict], text: str | None = None
) -> Message:
    """Bir turun model yanıtını kurar; tool_use id'leri tur ve sıra numarasından."""
    content = [] if text is None else [TextBlock(type="text", text=text)]
    content += [
        ToolUseBlock(type="tool_use", id=f"toolu_{index}_{i}", name=name, input=args)
        for i, (name, args) in enumerate(calls, start=1)
    ]
    return Message(
        id=f"msg_{index}",
        type="message",
        role="assistant",
        model="senaryo",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=0, output_tokens=0),
    )


def tool_turns(*turns: list[tuple[str, dict]]) -> list[Message]:
    """Her öğesi bir turun çağrı listesi olan tool_use turları."""
    return [model_turn(i, "tool_use", *calls) for i, calls in enumerate(turns, 1)]


def distinct_lookups(count: int) -> list[list[tuple[str, dict]]]:
    """Her turda farklı argümanla tek resolve_flight_identity çağrısı."""
    return [[(RESOLVE, {"query": f"ZZ{n}"})] for n in range(1, count + 1)]


def answer(index: int) -> Message:
    return model_turn(index, "end_turn", text="(senaryo cevabı)")


@dataclass(frozen=True)
class Scenario:
    description: str
    responses: Callable[[], list[Message]]
    status: str
    executed: list[list[bool]]


ALL = {"direction": "all"}
DIRECTIONS = ["all", "arrival", "departure"]

SCENARIOS = {
    "tamam": Scenario(
        "Tek tool çağrısı, sonra end_turn.",
        lambda: [*tool_turns([(SUMMARY, ALL)]), answer(2)],
        "tamam",
        [[True], []],
    ),
    "tamam_8_turda": Scenario(
        "7 farklı çağrı, 8. turda end_turn; tur sınırına rağmen tamam.",
        lambda: [*tool_turns(*distinct_lookups(7)), answer(8)],
        "tamam",
        [[True]] * 7 + [[]],
    ),
    "max_tokens": Scenario(
        "Kesik metin + tool_use ile max_tokens; tool çalışmaz.",
        lambda: [model_turn(1, "max_tokens", (SUMMARY, ALL), text="Bugün 600 uç")],
        "max_tokens",
        [[False]],
    ),
    "durduruldu_refusal": Scenario(
        "Model refusal ile durur.",
        lambda: [model_turn(1, "refusal")],
        "durduruldu",
        [[]],
    ),
    "durduruldu_taninmayan": Scenario(
        "Tanınmayan stop_reason (pause_turn) + tool_use; tool çalışmaz.",
        lambda: [model_turn(1, "pause_turn", (SUMMARY, ALL))],
        "durduruldu",
        [[False]],
    ),
    "tekrar_hatali_arguman": Scenario(
        'Hatalı argüman {"direction": "ALL"} 3 turda; 3. istek çalışmaz.',
        lambda: tool_turns(*[[(SUMMARY, {"direction": "ALL"})]] * 3),
        "tekrar_siniri",
        [[True], [True], [False]],
    ),
    "tekrar_ayni_turda": Scenario(
        "1. turda aynı çağrı 2 kez; 2. turda 3. istek + farklı çağrı, ikisi de "
        "çalışmaz.",
        lambda: tool_turns(
            [(SUMMARY, ALL), (SUMMARY, ALL)],
            [(SUMMARY, ALL), (SUMMARY, {"direction": "arrival"})],
        ),
        "tekrar_siniri",
        [[True, True], [False, False]],
    ),
    "tekrar_anahtar_sirasi": Scenario(
        "Aynı argüman farklı anahtar sırasıyla 3 kez; aynı çağrı sayılır.",
        lambda: tool_turns(
            [(RESOLVE, {"query": "TK2344", "x": 1})],
            [(RESOLVE, {"x": 1, "query": "TK2344"})],
            [(RESOLVE, {"query": "TK2344", "x": 1})],
        ),
        "tekrar_siniri",
        [[True], [True], [False]],
    ),
    "farkli_arguman_sayilmaz": Scenario(
        "Üç yön ikişer kez (6 tur), sonra end_turn; tekrar sınırına takılmaz.",
        lambda: [
            *tool_turns(*[[(SUMMARY, {"direction": d})] for d in DIRECTIONS * 2]),
            answer(7),
        ],
        "tamam",
        [[True]] * 6 + [[]],
    ),
    "iterasyon_siniri": Scenario(
        "8 turda 8 farklı çağrı; 8. turdaki çalışmaz.",
        lambda: tool_turns(*distinct_lookups(8)),
        "iterasyon_siniri",
        [[True]] * 7 + [[False]],
    ),
}


def print_result(result: AgentResult, usages: list[Usage], fake: bool) -> None:
    label = " (sahte)" if fake else ""
    total_in = total_out = 0
    for turn, usage in zip(result.turns, usages, strict=False):
        total_in += usage.input_tokens
        total_out += usage.output_tokens
        print(
            f"Tur {turn.index}: stop_reason={turn.stop_reason} "
            f"input={usage.input_tokens} output={usage.output_tokens}{label}"
        )
        if not turn.tool_calls:
            print("  tool isteği yok")
        for call in turn.tool_calls:
            arguments = json.dumps(call.input, ensure_ascii=False)
            if not call.executed:
                outcome = "çalıştırılmadı"
            elif call.envelope["error"] is None:
                outcome = "başarılı"
            else:
                outcome = call.envelope["error"]["code"]
            print(f"  {call.name} {arguments} -> {outcome}")

    print(f"\nToplam token: input={total_in} output={total_out}{label}")
    print(f"Durum: {result.status}")
    if result.reason is not None:
        print(f"Neden: {result.reason}")
    print(f"\nCevap:\n{result.text or '(metin yok)'}")


def run_scenario(name: str) -> bool:
    """Vakayı oynatır, çıktıyı yazar; beklenenle uyuşuyorsa True döner."""
    scenario = SCENARIOS[name]
    responses = scenario.responses()
    print(f"=== {name}: {scenario.description}\n")
    result = run_agent(f"[senaryo] {name}", client=ScriptedClient(responses))
    print_result(result, [r.usage for r in responses], fake=True)

    executed = [[c.executed for c in turn.tool_calls] for turn in result.turns]
    ok = result.status == scenario.status and executed == scenario.executed
    if ok:
        print("\nBeklenen: UYDU")
    else:
        print(
            f"\nBeklenen: UYMADI (durum {scenario.status}, çalıştı mı "
            f"{scenario.executed}; gelen durum {result.status}, çalıştı mı {executed})"
        )
    print()
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("soru", nargs="?", help="Gerçek modele sorulacak soru (ücretli)")
    mode.add_argument(
        "--vaka",
        choices=["liste", "hepsi", *SCENARIOS],
        help="Sahte modelle oynatılacak sınır vakası (API çağrısı yok)",
    )
    args = parser.parse_args()

    # backend.llm .env'yi yükledi; COPILOT_DATA hâlâ boşsa referans veri kullanılır.
    if not os.getenv("COPILOT_DATA", "").strip():
        os.environ["COPILOT_DATA"] = DEFAULT_DATA

    if args.vaka == "liste":
        for name, scenario in SCENARIOS.items():
            print(f"{name:<25} {scenario.description}")
        return

    print(f"Veri: {os.environ['COPILOT_DATA']}")
    if args.vaka is not None:
        print("Model: sahte (API çağrısı yok)\n")
        names = list(SCENARIOS) if args.vaka == "hepsi" else [args.vaka]
        outcomes = {name: run_scenario(name) for name in names}
        if len(names) > 1:
            print("Özet:")
            for name, ok in outcomes.items():
                print(f"  {'UYDU  ' if ok else 'UYMADI'} {name}")
        if not all(outcomes.values()):
            sys.exit(1)
        return

    print(f"Model: {llm.MODEL}")
    print(f"Soru: {args.soru}\n")
    recorder = UsageRecorder(llm.client)
    result = run_agent(args.soru, client=recorder)
    print_result(result, recorder.usages, fake=False)


if __name__ == "__main__":
    main()
