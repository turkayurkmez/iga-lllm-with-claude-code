"""/chat olay akışı sözleşme testleri (docs/chat.md › Kod garantileri).

Testler koddan önce yazıldı; /chat agent döngüsüne bağlanana kadar kırmızıdır.
Gerçek API çağrısı yapılmaz: backend.llm'in client'ı sahte senkron istemciyle,
async_client'ı eski /chat'in tek akışını taklit eden sahte istemciyle değiştirilir
(eski kod yolu ağa çıkmadan, okunur bir assertion hatasıyla kırmızı kalsın diye).
Veri ve saat referans güne sabitlenir; zarflar run_tool'dan, kart açıklamaları
kontrattan hesaplanır.
"""

import asyncio
import copy
import importlib
import json
import re
from pathlib import Path

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from fastapi.testclient import TestClient

from backend import agent, main
from backend.envelope import MESSAGES, ErrorCode
from backend.tools import run_tool

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")
SUMMARY_CONTRACT = REPO_ROOT / "backend/tools/contracts/get_flight_summary.json"

QUESTION = "Bugün kaç uçuş var?"
ANSWER = "Bugün 600 uçuş var; 4'ü iptal, 115'i gecikmeli."
INTERIM = "Kontrol ediyorum."
TRUNCATED = "Bugün 600 uç"
SECRET = "GIZLI-AYRINTI req_011CSecret"

EVENT_TYPES = {
    "tool_call",
    "source_chip",
    "kpi_card",
    "selection_card",
    "text_delta",
    "error",
    "done",
}
CARD_TYPES = ("source_chip", "kpi_card", "selection_card")

SUMMARY_ALL = ("get_flight_summary", {"direction": "all"})
SUMMARY_ARRIVAL = ("get_flight_summary", {"direction": "arrival"})
SUMMARY_BAD = ("get_flight_summary", {"direction": "ALL"})
AMBIGUOUS = ("resolve_flight_identity", {"query": "TC-LSD"})
MISSING = ("resolve_flight_identity", {"query": "ZZ9999"})
OUT_OF_SCOPE = ("get_weather", {})


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


def turn(
    index: int, stop_reason: str, *calls: tuple[str, dict], text: str | None = None
) -> Message:
    """Bir turun model yanıtı; tool_use id'leri tur ve sıra numarasından üretilir."""
    content: list = [] if text is None else [TextBlock(type="text", text=text)]
    content += [
        ToolUseBlock(type="tool_use", id=f"toolu_{index}_{i}", name=name, input=args)
        for i, (name, args) in enumerate(calls, start=1)
    ]
    return model_message(stop_reason, content)


def answer(index: int, text: str = ANSWER) -> Message:
    return turn(index, "end_turn", text=text)


class FakeClient:
    """messages.create çağrılarını kaydeden, yanıtları sırayla döndüren istemci.

    Listedeki bir exception yanıt yerine fırlatılır. Her çağrıda çalışan bir olay
    döngüsü olup olmadığı kaydedilir (Kod garantileri 10).
    """

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.loop_running: list[bool] = []
        self.messages = self

    def create(self, **kwargs) -> Message:
        self.requests.append(copy.deepcopy(kwargs))
        try:
            asyncio.get_running_loop()
            self.loop_running.append(True)
        except RuntimeError:
            self.loop_running.append(False)
        assert self._responses, "Beklenenden fazla model çağrısı yapıldı."
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class LegacyStream:
    """Eski /chat'in messages.stream yolunun taklidi: tek parça metin, end_turn."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        async def chunks():
            yield "Eski akış."

        return chunks()

    async def get_final_message(self):
        return model_message("end_turn", [])


class LegacyAsyncClient:
    def __init__(self):
        self.messages = self

    def stream(self, **kwargs):
        return LegacyStream()


def api_error() -> anthropic.APIError:
    """Mesajında istemciye gitmemesi gereken ayrıntı taşıyan API hatası."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(message=SECRET, request=request)


# --- Ortam -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def environment(monkeypatch, instruction_name):
    # source, COPILOT_DATA'nın değeri olduğu gibi döner; göreli yol için kök sabitlenir.
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)
    monkeypatch.setenv("COPILOT_INSTRUCTION", instruction_name)
    # backend.llm import edilirken .env gerekmesin; ortamdaki değer .env'yi ezer.
    for name in LLM_VARS:
        monkeypatch.setenv(name, f"test-{name.lower()}")


@pytest.fixture
def chat(monkeypatch):
    """Sahte yanıtlarla /chat'i çağırıp olay listesini döndüren fonksiyon.

    Döngü hangi istemciyi kullanırsa kullansın (llm.client ya da run_agent'ın
    varsayılanı) sahte istemciye düşer; ağa çıkılmaz (Kod garantileri 11).
    """
    llm = importlib.import_module("backend.llm")
    monkeypatch.setattr(main, "load_llm", lambda: llm)
    monkeypatch.setattr(llm, "async_client", LegacyAsyncClient())

    def send(responses: list, message: str = QUESTION):
        client = FakeClient(responses)
        monkeypatch.setattr(llm, "client", client)
        response = TestClient(main.app).post("/chat", json={"message": message})
        assert response.status_code == 200
        return parse_sse(response.text), client

    return send


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Akışı (tip, veri) çiftlerine ayırır; çerçeve docs/chat.md › Çerçeve'deki gibi."""
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        names = [line[6:].strip() for line in lines if line.startswith("event:")]
        data = [line[5:].strip() for line in lines if line.startswith("data:")]
        assert len(names) == 1, f"Olayın tek event satırı olmalı: {block!r}"
        assert len(data) == 1, f"Olayın tek data satırı olmalı: {block!r}"
        events.append((names[0], json.loads(data[0])))
    return events


def of_type(events: list[tuple[str, dict]], kind: str) -> list[dict]:
    return [data for name, data in events if name == kind]


def kinds(events: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _ in events]


def expected_kpi(envelope: dict) -> dict:
    """Kontrattaki value_schema sırasıyla tamsayı alanlar ve açıklamaları."""
    contract = json.loads(SUMMARY_CONTRACT.read_text(encoding="utf-8"))
    properties = contract["value_schema"]["properties"]
    items = [
        {
            "field": field,
            "description": spec["description"],
            "value": envelope["value"][field],
        }
        for field, spec in properties.items()
        if spec.get("type") == "integer"
    ]
    return {
        "tool": "get_flight_summary",
        "items": items,
        "source": envelope["source"],
        "as_of": envelope["as_of"],
    }


# Döngü vakaları: (yanıtlar, beklenen status); docs/agent.md › Durumlar.
LOOP_CASES = [
    pytest.param(
        lambda: [turn(1, "tool_use", SUMMARY_ALL), answer(2)], "tamam", id="tamam"
    ),
    pytest.param(
        lambda: [turn(1, "max_tokens", SUMMARY_ALL, text=TRUNCATED)],
        "max_tokens",
        id="max_tokens",
    ),
    pytest.param(
        lambda: [turn(1, "refusal", text=INTERIM)], "durduruldu", id="durduruldu"
    ),
    pytest.param(
        lambda: [turn(i, "tool_use", SUMMARY_BAD) for i in (1, 2, 3)],
        "tekrar_siniri",
        id="tekrar_siniri",
    ),
    pytest.param(
        lambda: [
            turn(i, "tool_use", ("resolve_flight_identity", {"query": f"ZZ{i}"}))
            for i in range(1, 9)
        ],
        "iterasyon_siniri",
        id="iterasyon_siniri",
    ),
]
NON_FINAL_CASES = [case for case in LOOP_CASES if case.id != "tamam"]


# --- 1. Kartlar zarftan üretilir -----------------------------------------------


def test_kartlar_zarftan_uretilir_model_metninden_degil(chat):
    # Model zarfla çelişen sayı ve kaynak yazar; kartlar yine zarfa uyar.
    misleading = "Bugün 999 uçuş var. Kaynak: sahte.json, 09:00 itibarıyla."
    events, _ = chat([turn(1, "tool_use", SUMMARY_ALL), answer(2, misleading)])
    envelope = run_tool(*SUMMARY_ALL)

    assert of_type(events, "kpi_card") == [expected_kpi(envelope)]
    chips = of_type(events, "source_chip")
    assert [chip["source"] for chip in chips] == [REFERENCE]
    assert "sahte.json" not in json.dumps([of_type(events, k) for k in CARD_TYPES])


# --- 2. Kartlar zarfı yorumlamaz -----------------------------------------------


def test_kpi_karti_zarf_ve_kontrat_alanlarini_oldugu_gibi_tasir(chat):
    events, _ = chat([turn(1, "tool_use", SUMMARY_ALL), answer(2)])

    assert of_type(events, "kpi_card") == [expected_kpi(run_tool(*SUMMARY_ALL))]


def test_secim_karti_zarfi_oldugu_gibi_tasir(chat):
    events, _ = chat([turn(1, "tool_use", AMBIGUOUS), answer(2)])
    envelope = run_tool(*AMBIGUOUS)

    assert envelope["error"]["code"] == ErrorCode.AMBIGUOUS_ENTITY
    assert of_type(events, "selection_card") == [
        {
            "query": envelope["filters"]["query"],
            "message": envelope["error"]["message"],
            "candidates": envelope["value"],
            "source": envelope["source"],
            "as_of": envelope["as_of"],
        }
    ]


def test_kpi_karti_yalnizca_basarili_ozet_zarfindan_cikar(chat):
    events, _ = chat([turn(1, "tool_use", SUMMARY_BAD, MISSING, AMBIGUOUS), answer(2)])

    # Üç çağrı da çalıştı ve bildirildi; hiçbiri başarılı özet değil.
    assert len(of_type(events, "tool_call")) == 3
    assert len(of_type(events, "selection_card")) == 1
    assert of_type(events, "kpi_card") == []


# --- 3. Çip kuralları -----------------------------------------------------------


def test_kaynaksiz_zarf_cip_uretmez(chat):
    events, _ = chat([turn(1, "tool_use", OUT_OF_SCOPE, SUMMARY_BAD), answer(2)])

    assert len(of_type(events, "tool_call")) == 2
    assert of_type(events, "source_chip") == []


def test_ayni_dortlu_tek_cip_olur(chat):
    events, _ = chat(
        [
            turn(1, "tool_use", SUMMARY_ALL, SUMMARY_ARRIVAL),
            turn(2, "tool_use", MISSING),
            answer(3),
        ]
    )

    assert of_type(events, "source_chip") == [
        {
            "tool": "get_flight_summary",
            "source": REFERENCE,
            "as_of": NOW,
            "stale": False,
            "error_code": None,
        },
        {
            "tool": "resolve_flight_identity",
            "source": REFERENCE,
            "as_of": NOW,
            "stale": False,
            "error_code": "NOT_FOUND",
        },
    ]


# --- 4. Bayat veri ---------------------------------------------------------------


def test_bayat_zarf_bayat_isaretli_cip_uretir(chat, monkeypatch):
    # Üç tool'da tazelik eşiği yok (docs/tools.md); bayat zarf run_tool taklidiyle verilir.
    old = "2026-10-20T16:12:00+03:00"
    stale = run_tool(*SUMMARY_ALL) | {
        "as_of": old,
        "stale": True,
        "error": {"code": "STALE_DATA", "message": MESSAGES[ErrorCode.STALE_DATA]},
        "author": "layer",
    }
    monkeypatch.setattr(agent, "run_tool", lambda name, args: copy.deepcopy(stale))

    events, client = chat([turn(1, "tool_use", SUMMARY_ALL), answer(2)])

    assert of_type(events, "source_chip") == [
        {
            "tool": "get_flight_summary",
            "source": REFERENCE,
            "as_of": old,
            "stale": True,
            "error_code": "STALE_DATA",
        }
    ]
    # Zarf modele değiştirilmeden gider: son bilinen değer ve as_of korunur.
    result = client.requests[1]["messages"][-1]["content"][0]
    assert json.loads(result["content"]) == stale


# --- 5. Belirsizlik döngüyü durdurmaz ---------------------------------------------


def test_belirsizlik_donguyu_durdurmaz_ve_aday_secilmez(chat):
    clarify = "Birden fazla uçuş eşleşti; sefer no ya da tescille netleştirin."
    events, client = chat([turn(1, "tool_use", AMBIGUOUS), answer(2, clarify)])

    assert kinds(events) == [
        "tool_call",
        "source_chip",
        "selection_card",
        "text_delta",
        "done",
    ]
    assert of_type(events, "done")[0]["status"] == "tamam"
    # Zarf modele gider; ikinci tur onu görerek cevap yazar.
    assert len(client.requests) == 2
    result = client.requests[1]["messages"][-1]["content"][0]
    assert json.loads(result["content"]) == run_tool(*AMBIGUOUS)
    # Kart adayların hepsini taşır; kod birini seçip yeni tool çağırmaz.
    assert len(of_type(events, "selection_card")[0]["candidates"]) > 1
    assert len(of_type(events, "tool_call")) == 1


# --- 6. tool_call tam argümanla, sonuçtan önce -------------------------------------


def test_tool_call_tam_argumanla_ve_sonuclardan_once_cikar(chat):
    events, _ = chat([turn(1, "tool_use", SUMMARY_ALL, SUMMARY_ARRIVAL), answer(2)])

    assert of_type(events, "tool_call") == [
        {
            "id": "toolu_1_1",
            "name": "get_flight_summary",
            "input": {"direction": "all"},
        },
        {
            "id": "toolu_1_2",
            "name": "get_flight_summary",
            "input": {"direction": "arrival"},
        },
    ]
    # Sıra: turun tüm tool_call'ları, sonra istek sırasıyla çip ve kartlar.
    assert kinds(events) == [
        "tool_call",
        "tool_call",
        "source_chip",
        "kpi_card",
        "kpi_card",
        "text_delta",
        "done",
    ]


# --- 7. Olaylar AgentResult ile tutarlı --------------------------------------------


@pytest.mark.parametrize(("responses", "status"), LOOP_CASES)
def test_olaylar_agent_sonucuyla_tutarli(chat, responses, status):
    result = agent.run_agent(QUESTION, client=FakeClient(responses()))
    assert result.status == status

    events, _ = chat(responses())

    executed = [
        {"id": call.id, "name": call.name, "input": call.input}
        for t in result.turns
        for call in t.tool_calls
        if call.executed
    ]
    assert of_type(events, "tool_call") == executed
    done = of_type(events, "done")
    assert len(done) == 1
    # audit_id rastgeledir; biçimi ve kayıtla eşleşmesi tests/test_audit.py'de sınanır.
    assert re.fullmatch(r"[0-9a-f]{32}", done[0].pop("audit_id", None) or "")
    assert done == [
        {
            "status": result.status,
            "reason": result.reason,
            "turns": len(result.turns),
            "instruction": result.instruction.model_dump(),
        }
    ]


def test_calistirilmayan_cagri_icin_tool_call_cikmaz(chat):
    events, _ = chat([turn(1, "max_tokens", SUMMARY_ALL, text=TRUNCATED)])

    # Kesik yanıttaki tool_use çalıştırılmaz; akışta yalnızca bitiş olayları var.
    assert kinds(events) == ["error", "done"]


@pytest.mark.parametrize(("responses", "status"), NON_FINAL_CASES)
def test_tamam_disi_durumda_error_sonra_done_gelir(chat, responses, status):
    result = agent.run_agent(QUESTION, client=FakeClient(responses()))

    events, _ = chat(responses())

    assert kinds(events)[-2:] == ["error", "done"]
    assert of_type(events, "error") == [{"code": status, "message": result.reason}]


@pytest.mark.parametrize(("responses", "status"), LOOP_CASES)
def test_akis_tek_son_olayla_biter_ve_olay_tipleri_kapali(chat, responses, status):
    events, _ = chat(responses())

    assert set(kinds(events)) <= EVENT_TYPES
    assert kinds(events)[-1] == "done"
    assert kinds(events).count("done") == 1


# --- 8. Kısmi cevap üretilmez ---------------------------------------------------------


def test_text_delta_birlesimi_cevap_metnine_esit(chat):
    events, _ = chat([turn(1, "tool_use", SUMMARY_ALL), answer(2)])

    deltas = of_type(events, "text_delta")
    assert "".join(d["text"] for d in deltas) == ANSWER
    # text_delta'lar art arda gelir; ardından yalnızca done.
    assert kinds(events)[-len(deltas) - 1 :] == ["text_delta"] * len(deltas) + ["done"]


def test_ara_metin_operatore_gitmez(chat):
    events, _ = chat([turn(1, "tool_use", SUMMARY_ALL, text=INTERIM), answer(2)])

    text = "".join(d["text"] for d in of_type(events, "text_delta"))
    assert text == ANSWER
    assert INTERIM not in json.dumps([data for _, data in events], ensure_ascii=False)


@pytest.mark.parametrize(("responses", "status"), NON_FINAL_CASES)
def test_text_delta_yalnizca_tamam_durumunda(chat, responses, status):
    events, _ = chat(responses())

    assert kinds(events)[-2:] == ["error", "done"]
    assert of_type(events, "text_delta") == []
    body = json.dumps([data for _, data in events], ensure_ascii=False)
    assert TRUNCATED not in body
    assert INTERIM not in body


def test_tamam_ama_bos_metinde_text_delta_yok(chat):
    events, _ = chat([turn(1, "end_turn")])

    assert kinds(events) == ["done"]
    assert of_type(events, "done")[0]["status"] == "tamam"


# --- 9. Hata ayrıntısı gitmez ---------------------------------------------------------


def test_ilk_turda_model_hatasi_genel_mesajla_biter(chat):
    events, _ = chat([api_error()])

    assert events == [("error", {"code": "model_error", "message": main.ERROR_MESSAGE})]


def test_sonraki_turda_model_hatasi_done_olmadan_biter(chat):
    events, _ = chat([turn(1, "tool_use", SUMMARY_ALL), api_error()])

    assert kinds(events) == ["tool_call", "source_chip", "kpi_card", "error"]
    assert of_type(events, "error") == [
        {"code": "model_error", "message": main.ERROR_MESSAGE}
    ]


def test_hata_ayrintisi_hicbir_olaya_girmez(chat):
    events, _ = chat([turn(1, "tool_use", SUMMARY_ALL), api_error()])

    # Hata model çağrısında oldu ve akış error ile bitti.
    assert kinds(events)[-1] == "error"
    body = json.dumps(events, ensure_ascii=False)
    assert SECRET not in body
    assert "req_" not in body
    assert "APIConnectionError" not in body


# --- 10. Olay döngüsü bloklanmaz -------------------------------------------------------


def test_model_cagrisi_olay_dongusu_disinda_yapilir(chat):
    _, client = chat([turn(1, "tool_use", SUMMARY_ALL), answer(2)])

    assert client.loop_running == [False, False]


# --- 10. Mesaj uzunluk sınırı (docs/enjeksiyon.md E4) -------------------------------


def test_mesaj_sinir_uzunlugunda_kabul_edilir(chat):
    assert main.MAX_MESSAGE_CHARS == 2000

    events, client = chat([answer(1)], message="a" * main.MAX_MESSAGE_CHARS)

    assert of_type(events, "done")[0]["status"] == "tamam"
    assert len(client.requests) == 1


def test_mesaj_siniri_asilinca_422():
    response = TestClient(main.app).post(
        "/chat", json={"message": "a" * (main.MAX_MESSAGE_CHARS + 1)}
    )

    assert response.status_code == 422
    assert str(main.MAX_MESSAGE_CHARS) in json.dumps(response.json(), ensure_ascii=False)


def test_sinir_kod_noktasiyla_sayilir(chat):
    events, _ = chat([answer(1)], message="ş" * main.MAX_MESSAGE_CHARS)
    assert of_type(events, "done")[0]["status"] == "tamam"

    response = TestClient(main.app).post(
        "/chat", json={"message": "😀" * (main.MAX_MESSAGE_CHARS + 1)}
    )
    assert response.status_code == 422


def test_bosluklar_sinirdan_once_kirpilir(chat):
    message = "  " + "a" * main.MAX_MESSAGE_CHARS + "  "

    events, _ = chat([answer(1)], message=message)

    assert of_type(events, "done")[0]["status"] == "tamam"
