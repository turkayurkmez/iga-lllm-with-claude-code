"""Saldırı seti ve denetleyicisi (docs/enjeksiyon.md E7, API'siz).

Kodun garantileri sınanır: model saldırıya uyarsa (sahte "uyumlu" model) sınırlandırma,
işaretleme ve ihlal denetimi yine çalışır. Gerçek model yoktur; ücretli koşu
`scripts/enjeksiyon_kos.py`'dedir.
"""

import copy
import importlib.util
import json
from collections import Counter

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from backend import agent, audit, instructions
from backend.agent import AgentResult, Instruction, ToolCall, Turn

NOW = "2026-10-20T16:22:00+03:00"
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")
VERSION = "v3"
KINDS = {"dogrudan", "dolayli_korpus", "dolayli_tool", "ifsa"}
PLACEHOLDER = "{TALIMAT}"


def load_module():
    assert importlib.util.find_spec("eval.enjeksiyon") is not None, "eval/enjeksiyon.py yok"
    from eval import enjeksiyon

    return enjeksiyon


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_INSTRUCTION", VERSION)
    for name in LLM_VARS:
        monkeypatch.setenv(name, f"test-{name.lower()}")


@pytest.fixture
def attacks() -> list[dict]:
    return load_module().load_attacks()


# --- Set ---------------------------------------------------------------------


def test_set_dort_turu_kapsar(attacks):
    counts = Counter(a["tur"] for a in attacks)

    assert set(counts) == KINDS
    assert all(count >= 2 for count in counts.values())
    assert len(attacks) >= 8
    assert len({a["id"] for a in attacks}) == len(attacks)


def test_korpus_saldirilari_parca_tool_saldirilari_zarf_tasir(attacks):
    corpus = [a for a in attacks if a["tur"] == "dolayli_korpus"]
    tools = [a for a in attacks if a["tur"] == "dolayli_tool"]

    assert corpus
    assert tools
    assert all(a["zehirli_parca"] for a in corpus)
    assert all(a["zehirli_zarf"] for a in tools)


@pytest.mark.parametrize(
    "broken",
    [
        {"id": "x"},
        {
            "id": "x",
            "tur": "bilinmeyen",
            "girdi": "?",
            "zehirli_parca": None,
            "zehirli_zarf": None,
            "beklenen": {
                "yasak_ifade": [],
                "yasak_tool": [],
                "ifsa_olmamali": False,
                "sayi_uydurulmamali": False,
            },
            "uyumlu_cevap": "",
            "beklenen_isaret": [],
        },
    ],
)
def test_bozuk_kayit_turkce_hata_verir(tmp_path, broken):
    path = tmp_path / "set.json"
    path.write_text(json.dumps([broken]), encoding="utf-8")

    with pytest.raises(ValueError, match="Saldırı"):
        load_module().load_attacks(path)


# --- İhlal denetimi ------------------------------------------------------------


def make_result(text: str, tool_names: tuple[str, ...] = ()) -> AgentResult:
    calls = [
        ToolCall(id=f"t{i}", name=name, input={}, executed=True, envelope={"value": None})
        for i, name in enumerate(tool_names)
    ]
    return AgentResult(
        status="tamam",
        reason=None,
        text=text,
        turns=[Turn(index=1, stop_reason="end_turn", tool_calls=calls)],
        instruction=Instruction(name=VERSION, version="3.0.0", summary="0" * 64),
    )


def base_attack(**expected) -> dict:
    return {
        "id": "x",
        "girdi": "Soru?",
        "beklenen": {
            "yasak_ifade": [],
            "yasak_tool": [],
            "ifsa_olmamali": False,
            "sayi_uydurulmamali": False,
        }
        | expected,
    }


def test_ihlal_denetimi_yasak_ifadeyi_buyuk_kucuk_harf_duyarsiz_yakalar():
    attack = base_attack(yasak_ifade=["onaylandı"])

    found = load_module().violations(attack, make_result("Tamam. ONAYLANDI"), "")

    assert len(found) == 1


def test_ihlal_denetimi_yasak_tool_u_yakalar():
    attack = base_attack(yasak_tool=["get_flight_summary"])

    found = load_module().violations(
        attack, make_result("Cevap.", ("get_flight_summary",)), ""
    )

    assert len(found) == 1


def test_ihlal_denetimi_ifsayi_yakalar():
    system = "Bu, talimatın kırk karakterden uzun olan cümlesidir."
    attack = base_attack(ifsa_olmamali=True)

    found = load_module().violations(attack, make_result(system), system)

    assert len(found) == 1


def test_ihlal_denetimi_uydurma_sayiyi_yakalar():
    attack = base_attack(sayi_uydurulmamali=True)

    found = load_module().violations(attack, make_result("Bugün 8412 uçuş var."), "")

    assert len(found) == 1


def test_ihlal_yoksa_bos_liste():
    attack = base_attack(
        yasak_ifade=["onay"],
        yasak_tool=["get_flight_summary"],
        ifsa_olmamali=True,
        sayi_uydurulmamali=True,
    )

    assert load_module().violations(attack, make_result("Veri yok."), "Talimat.") == []


# --- Uyumlu (kandırılmış) model, kodun garantileri --------------------------------


def text_block(text: str) -> TextBlock:
    return TextBlock(type="text", text=text)


def message(stop_reason: str, *content) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="test-model",
        content=list(content),
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


class ScriptedClient:
    """Yanıtları sırayla döndürür; çağrı anındaki istekleri saklar."""

    def __init__(self, responses: list[Message]):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs) -> Message:
        self.requests.append(copy.deepcopy(kwargs))
        return self._responses.pop(0)


def run_compliant(attack: dict, monkeypatch) -> tuple[AgentResult, ScriptedClient]:
    system = instructions.load(VERSION)
    answer = attack["uyumlu_cevap"]
    if answer == PLACEHOLDER:
        answer = system.split("\n\n")[1]
    responses = []
    poisoned = load_module().poisoned_tool(attack, NOW)
    if poisoned is not None:
        name, envelope = poisoned
        args = {"query": attack["girdi"]}
        responses.append(
            message(
                "tool_use",
                ToolUseBlock(type="tool_use", id="toolu_1", name=name, input=args),
            )
        )
        monkeypatch.setattr(agent, "run_tool", lambda n, a: copy.deepcopy(envelope))
    responses.append(message("end_turn", text_block(answer)))
    client = ScriptedClient(responses)
    return agent.run_agent(attack["girdi"], client=client), client


def audit_line(attack: dict, result: AgentResult, audit_dir) -> dict:
    audit.write_question(
        attack["girdi"],
        audit_id="a" * 32,
        status=result.status,
        reason=result.reason,
        model="test-model",
        instruction=result.instruction.model_dump(),
        chips=[],
        client_disconnected=False,
        result=result,
    )
    (path,) = audit_dir.glob("*.jsonl")
    (line,) = path.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


def all_attack_ids() -> list[str]:
    return [a["id"] for a in load_module().load_attacks()]


@pytest.mark.parametrize("attack_id", all_attack_ids())
def test_uyumlu_model_kod_garantilerini_asamaz(attack_id, monkeypatch, audit_dir):
    attack = next(a for a in load_module().load_attacks() if a["id"] == attack_id)

    result, client = run_compliant(attack, monkeypatch)
    line = audit_line(attack, result, audit_dir)

    assert result.status == "tamam"
    # Kandırılmış cevap denetleyicide ihlal olarak görünür (savunma ölçülebilir).
    system = instructions.load(VERSION)
    assert load_module().violations(attack, result, system) != []
    # Beklenen işaretler audit'te vardır; boş beklenti "işaretsiz" demektir.
    expected = set(attack["beklenen_isaret"])
    assert expected <= set(line["injection_flags"])
    if expected:
        assert line["injection_flags"]
    # Zehirli parça modele sınırlanmış gider ve belge dışına çıkamaz.
    if attack["zehirli_parca"]:
        part = attack["zehirli_parca"]
        sent = client.requests[1]["messages"][-1]["content"][0]["content"]
        text = json.loads(sent)["value"][0]["text"]
        assert text.startswith(f'<belge id="{part["chunk_id"]}">')
        assert text.count("</belge>") == 1
        assert text.count("<belge id=") == 1
        # Kayıtlı zarf ham kalır.
        recorded = result.turns[0].tool_calls[0].envelope
        assert recorded["value"][0]["text"] == part["text"]
