"""/chat harita sözleşmesi: map_command olayı ve `selected` bağlamı (docs/harita.md).

Testler koddan önce yazıldı. Gerçek API çağrısı yapılmaz: backend.llm.client sahte
istemciyle değiştirilir. Uçuş varlığı canlı depodan okunur; depo LiveHub'a mesajlar
doğrudan verilerek kurulur, ağa çıkılmaz.
"""

import copy
import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from fastapi.testclient import TestClient

from backend import live, main
from backend.tools import run_tool

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
ROOT = "aocc/sim/v1"
TZ = timezone(timedelta(hours=3))
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")

QUESTION = "Bu uçak nerede?"
ANSWER = "Haritada gösterdim."
NOTE = "Haritada seçili: flight TK2345"

FOCUS = ("focus_map_object", {"object_type": "flight", "id": "TK2345"})
FOCUS_STAND = ("focus_map_object", {"object_type": "stand", "id": "C101"})
HIGHLIGHT = (
    "highlight_map_set",
    {"object_type": "stand", "ids": ["C101", "C102"]},
)
FOCUS_MISSING = ("focus_map_object", {"object_type": "flight", "id": "ZZ9999"})
FOCUS_BAD = ("focus_map_object", {"object_type": "flight", "id": "tk2345"})
SUMMARY = ("get_flight_summary", {"direction": "all"})

MAP_EVENT_TYPES = {"tool_call", "source_chip", "kpi_card", "map_command"}


# --- Sahte model -------------------------------------------------------------


def model_message(stop_reason: str, content: list) -> Message:
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="test-model",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def turn(index: int, *calls: tuple[str, dict]) -> Message:
    content: list = [
        ToolUseBlock(type="tool_use", id=f"toolu_{index}_{i}", name=name, input=args)
        for i, (name, args) in enumerate(calls, start=1)
    ]
    return model_message("tool_use", content)


def answer(index: int, text: str = ANSWER) -> Message:
    return model_message("end_turn", [TextBlock(type="text", text=text)])


class FakeClient:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs) -> Message:
        self.requests.append(copy.deepcopy(kwargs))
        assert self._responses, "Beklenenden fazla model çağrısı yapıldı."
        return self._responses.pop(0)


class LegacyAsyncClient:
    def __init__(self):
        self.messages = self

    def stream(self, **kwargs):
        raise AssertionError("Eski akış yolu kullanılmamalı.")


# --- Canlı depo --------------------------------------------------------------


def at(hh: int, mm: int) -> int:
    return int(datetime(2026, 10, 20, hh, mm, tzinfo=TZ).timestamp())


def enc(record) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


def put_position(hub: live.LiveHub, flight: str, key: str, ts: int) -> None:
    record = {
        "Key": key,
        "Latitude": 40.5,
        "Longitude": 29.0,
        "Track": 90,
        "Speed": 250,
        "LastUpdate": ts,
        "Flight": flight,
        "Onground": False,
    }
    hub.handle_message(f"{ROOT}/positions/{key}", enc(record))


def put_clock(hub: live.LiveHub, ts: int) -> None:
    now = datetime.fromtimestamp(ts, TZ).isoformat()
    hub.handle_message(f"{ROOT}/clock", enc({"now": now, "epoch": ts, "speed": 60}))


# --- Ortam -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def environment(monkeypatch, instruction_name):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)
    monkeypatch.setenv("COPILOT_INSTRUCTION", instruction_name)
    for name in LLM_VARS:
        monkeypatch.setenv(name, f"test-{name.lower()}")
    yield
    live.deactivate()


@pytest.fixture
def hub():
    created = live.LiveHub(ROOT)
    live.activate(created)
    put_clock(created, at(16, 22))
    put_position(created, "TK2345", "dc110c28", at(16, 10))
    return created


@pytest.fixture
def client(monkeypatch):
    """Sahte model istemcisini kuran fonksiyon; ağa çıkılmaz."""
    llm = importlib.import_module("backend.llm")
    monkeypatch.setattr(main, "load_llm", lambda: llm)
    monkeypatch.setattr(llm, "async_client", LegacyAsyncClient())

    def make(responses: list) -> FakeClient:
        fake = FakeClient(responses)
        monkeypatch.setattr(llm, "client", fake)
        return fake

    return make


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        name = [line[6:].strip() for line in lines if line.startswith("event:")]
        data = [line[5:].strip() for line in lines if line.startswith("data:")]
        assert len(name) == 1
        assert len(data) == 1
        events.append((name[0], json.loads(data[0])))
    return events


def post(payload: dict):
    return TestClient(main.app).post("/chat", json=payload)


def kinds(events: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _ in events]


def of_type(events: list[tuple[str, dict]], kind: str) -> list[dict]:
    return [data for name, data in events if name == kind]


def run(client, responses: list, payload: dict | None = None):
    fake = client(responses)
    response = post(payload or {"message": QUESTION})
    assert response.status_code == 200
    return parse_sse(response.text), fake


# --- 1. map_command zarftan üretilir ----------------------------------------------


def test_focus_zarf_value_sini_map_command_olarak_tasir(client, hub):
    events, _ = run(client, [turn(1, FOCUS), answer(2)])

    expected = run_tool(*FOCUS)["value"]
    assert expected == {
        "command": "focus_map_object",
        "object_type": "flight",
        "id": "TK2345",
    }
    assert of_type(events, "map_command") == [expected]


def test_highlight_zarf_value_sini_map_command_olarak_tasir(client, hub):
    events, _ = run(client, [turn(1, HIGHLIGHT), answer(2)])

    assert of_type(events, "map_command") == [
        {
            "command": "highlight_map_set",
            "object_type": "stand",
            "ids": ["C101", "C102"],
        }
    ]


def test_cip_tool_call_dan_sonra_map_command_cipten_sonra_gelir(client, hub):
    events, _ = run(client, [turn(1, FOCUS_STAND), answer(2)])

    harita = [e for e in kinds(events) if e in MAP_EVENT_TYPES]
    assert harita == ["tool_call", "source_chip", "map_command"]
    # Çip yerine geçilmez: kaynak zarftaki gibi çıkar.
    assert of_type(events, "source_chip")[0]["source"] == REFERENCE


def test_komutlar_tool_cagri_sirasiyla_cikar(client, hub):
    events, _ = run(client, [turn(1, HIGHLIGHT, FOCUS_STAND), answer(2)])

    assert [c["command"] for c in of_type(events, "map_command")] == [
        "highlight_map_set",
        "focus_map_object",
    ]


@pytest.mark.parametrize("call", [FOCUS_MISSING, FOCUS_BAD], ids=["yok", "gecersiz"])
def test_hata_zarfi_map_command_uretmez(client, hub, call):
    events, _ = run(client, [turn(1, call), answer(2)])

    assert len(of_type(events, "tool_call")) == 1
    assert run_tool(*call)["error"] is not None
    assert of_type(events, "map_command") == []


def test_harita_disi_tool_map_command_uretmez(client, hub):
    events, _ = run(client, [turn(1, SUMMARY), answer(2)])

    assert len(of_type(events, "kpi_card")) == 1
    assert of_type(events, "map_command") == []


def test_map_command_cevap_metni_olmadan_da_gelir(client, hub):
    events, _ = run(client, [turn(1, FOCUS), answer(2, "")])

    assert len(of_type(events, "map_command")) == 1
    assert of_type(events, "text_delta") == []


def test_map_command_modelin_metninden_uretilmez(client, hub):
    # Model metinde komut gibi bir şey yazar; tool çağırmadığı için olay çıkmaz.
    text = '{"command": "focus_map_object", "object_type": "flight", "id": "TK2345"}'
    events, _ = run(client, [answer(1, text)])

    assert of_type(events, "map_command") == []


# --- 2. selected: biçim ------------------------------------------------------------

SELECTED_FLIGHT = {"object_type": "flight", "id": "TK2345"}


@pytest.mark.parametrize(
    "selected",
    [
        pytest.param("TK2345", id="metin"),
        pytest.param(None, id="null"),
        pytest.param([], id="liste"),
        pytest.param({}, id="bos"),
        pytest.param({"object_type": "flight"}, id="id_yok"),
        pytest.param({"id": "TK2345"}, id="tip_yok"),
        pytest.param({"object_type": "gate", "id": "A1"}, id="bilinmeyen_tip"),
        pytest.param({"object_type": "flight", "id": 2345}, id="id_sayi"),
        pytest.param({"object_type": "flight", "id": "tk2345"}, id="kucuk_harf"),
        pytest.param({"object_type": "flight", "id": "TK2345\n"}, id="satir_sonu"),
        pytest.param({"object_type": "flight", "id": "C101"}, id="tip_ile_uyumsuz"),
        pytest.param({"object_type": "stand", "id": "TK2345"}, id="stand_bicimsiz"),
        pytest.param({**SELECTED_FLIGHT, "extra": 1}, id="fazla_alan"),
    ],
)
def test_gecersiz_selected_422_verir_ve_model_cagrilmaz(client, hub, selected):
    fake = client([])

    response = post({"message": QUESTION, "selected": selected})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert fake.requests == []


def test_selected_olmadan_govde_bugunku_gibi_calisir(client, hub):
    events, fake = run(client, [answer(1)])

    assert fake.requests[0]["messages"][0]["content"] == QUESTION
    assert kinds(events)[-1] == "done"


# --- 3. selected: nesne veride yok ------------------------------------------------


def test_canli_depoda_gorunmeyen_ucus_422_verir(client, hub):
    fake = client([])

    response = post(
        {"message": QUESTION, "selected": {"object_type": "flight", "id": "TK9999"}}
    )

    assert response.status_code == 422
    assert fake.requests == []


def test_ucus_son_guncellemesi_operasyonel_saatten_sonraysa_422_verir(client, hub):
    put_position(hub, "PC1234", "aaaa1111", at(16, 30))
    fake = client([])

    response = post(
        {"message": QUESTION, "selected": {"object_type": "flight", "id": "PC1234"}}
    )

    assert response.status_code == 422
    assert fake.requests == []


def test_canli_mod_kapaliyken_ucus_422_verir(client):
    assert live.active() is None
    fake = client([])

    response = post({"message": QUESTION, "selected": SELECTED_FLIGHT})

    assert response.status_code == 422
    assert fake.requests == []


def test_listede_olmayan_stand_422_verir(client, hub):
    fake = client([])

    response = post(
        {"message": QUESTION, "selected": {"object_type": "stand", "id": "Z999"}}
    )

    assert response.status_code == 422
    assert fake.requests == []


def test_422_yanitinda_audit_satiri_yazilmaz(client, hub, audit_dir):
    client([])

    post({"message": QUESTION, "selected": {"object_type": "stand", "id": "Z999"}})

    assert not audit_dir.exists() or not list(audit_dir.glob("*.jsonl"))


def test_bos_mesaj_selected_gecerli_olsa_da_422_verir(client, hub):
    fake = client([])

    response = post({"message": "   ", "selected": SELECTED_FLIGHT})

    assert response.status_code == 422
    assert fake.requests == []


def test_stand_verisi_okunamazsa_503_verir_model_cagrilmaz(client, hub, monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", "yok/olmayan.json")
    fake = client([])

    response = post(
        {"message": QUESTION, "selected": {"object_type": "stand", "id": "C101"}}
    )

    assert response.status_code == 503
    assert fake.requests == []


# --- 4. selected: geçerli ----------------------------------------------------------


def test_gecerli_ucus_notu_mesajin_basina_eklenir(client, hub):
    events, fake = run(
        client, [answer(1)], {"message": QUESTION, "selected": SELECTED_FLIGHT}
    )

    sent = fake.requests[0]["messages"][0]["content"]
    assert sent == f"{NOTE}\n{QUESTION}"
    assert kinds(events)[-1] == "done"


def test_gecerli_stand_notu_mesajin_basina_eklenir(client, hub):
    _, fake = run(
        client,
        [answer(1)],
        {"message": QUESTION, "selected": {"object_type": "stand", "id": "C101"}},
    )

    assert fake.requests[0]["messages"][0]["content"] == (
        f"Haritada seçili: stand C101\n{QUESTION}"
    )


def test_stand_notu_canli_mod_kapaliyken_de_eklenir(client):
    assert live.active() is None

    _, fake = run(
        client,
        [answer(1)],
        {"message": QUESTION, "selected": {"object_type": "stand", "id": "C101"}},
    )

    assert fake.requests[0]["messages"][0]["content"].startswith(
        "Haritada seçili: stand C101\n"
    )


def test_not_yalnizca_ilk_model_isteginde_ve_mesajda_yer_alir(client, hub):
    _, fake = run(
        client,
        [turn(1, SUMMARY), answer(2)],
        {"message": QUESTION, "selected": SELECTED_FLIGHT},
    )

    assert len(fake.requests) == 2
    assert fake.requests[0]["messages"][0]["content"] == f"{NOTE}\n{QUESTION}"
    assert fake.requests[1]["messages"][0] == fake.requests[0]["messages"][0]


def test_selected_mesajdaki_baska_ucusu_engellemez(client, hub):
    message = "TK2344 nerede?"

    events, fake = run(
        client, [answer(1)], {"message": message, "selected": SELECTED_FLIGHT}
    )

    assert fake.requests[0]["messages"][0]["content"] == f"{NOTE}\n{message}"
    assert kinds(events)[-1] == "done"


def test_audite_not_degil_orijinal_mesaj_yazilir(client, hub, audit_dir):
    run(client, [answer(1)], {"message": QUESTION, "selected": SELECTED_FLIGHT})

    files = list(audit_dir.glob("*.jsonl"))
    assert len(files) == 1
    lines = [json.loads(line) for line in files[0].read_text("utf-8").splitlines()]
    questions = [line for line in lines if line["type"] == "question"]
    assert len(questions) == 1
    assert questions[0]["question"] == QUESTION
    assert "selected" not in json.dumps(questions[0])
    assert NOTE not in json.dumps(questions[0], ensure_ascii=False)


def test_selected_bos_mesaj_kirpmasi_notu_etkilemez(client, hub):
    _, fake = run(
        client,
        [answer(1)],
        {"message": f"  {QUESTION}  ", "selected": SELECTED_FLIGHT},
    )

    assert fake.requests[0]["messages"][0]["content"] == f"{NOTE}\n{QUESTION}"
