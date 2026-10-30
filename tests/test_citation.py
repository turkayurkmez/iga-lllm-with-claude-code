"""/chat citation olayı sözleşmesi (docs/chat.md › Atıf olayı, docs/kaynakli.md › Atıf).

Testler koddan önce yazıldı; /chat `citation` üretene kadar etiket bekleyen testler
kırmızıdır, "olay yok" diyen testler regresyon korumasıdır. Gerçek API ve arama
yoktur: model sahte senkron istemcidir, `search_documents` zarfı `agent.run_tool`
taklidiyle verilir (Voyage, indeks ve ağ devreye girmez). Veri ve saat sabitlenir.
"""

import copy
import importlib
import json
from pathlib import Path

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from fastapi.testclient import TestClient

from backend import agent, main
from backend.tools import run_tool

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")

QUESTION = "Düşük görüşte hangi prosedür uygulanır?"
CORPUS = "data/korpus"
SEARCH = ("search_documents", {"query": "düşük görüş prosedürü"})
SEARCH_OLD = (
    "search_documents",
    {"query": "düşük görüş prosedürü", "include_superseded": True},
)
SUMMARY = ("get_flight_summary", {"direction": "all"})

CITATION_FIELDS = {
    "chunk_id",
    "dogrulandi",
    "title",
    "section",
    "revision",
    "effective_from",
    "status",
}
DOCUMENT_FIELDS = CITATION_FIELDS - {"chunk_id", "dogrulandi"}


def chunk(chunk_id: str, **overrides) -> dict:
    """search_documents kontratındaki biçimde bir parça (docs/kaynakli.md › Tool)."""
    doc_id = chunk_id.split("#")[0]
    base = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "title": f"Belge {doc_id}",
        "section": f"Bölüm > {chunk_id}",
        "revision": "2",
        "effective_from": "2026-03-01",
        "status": "active",
        "authority": "Gökçe Havalimanı Meydan Müdürlüğü",
        "priority_level": 3,
        "language": "tr",
        "text": f"{chunk_id} metni.",
    }
    return base | overrides


D03 = chunk("D03#02", title="Aerodrome Manual — Düşük Görüş", revision="2")
D04 = chunk("D04#01", title="SOP — Buzlanma Önleme", effective_from="2025-01-01")
D02_OLD = chunk(
    "D02#01",
    title="Aerodrome Manual — Düşük Görüş (eski)",
    revision="1",
    effective_from="2024-11-01",
    status="superseded",
    superseded_by="D03",
)


def search_envelope(chunks: list[dict] | None) -> dict:
    """Başarılı (ya da chunks None ise NOT_FOUND) search_documents zarfı."""
    error = (
        None
        if chunks is not None
        else {
            "code": "NOT_FOUND",
            "message": "Belgelerde bu konuda kaynak bulunamadı.",
        }
    )
    return {
        "value": chunks,
        "source": CORPUS,
        "as_of": NOW,
        "filters": {"query": SEARCH[1]["query"], "include_superseded": False},
        "stale": False,
        "tool_version": "1.0.0",
        "error": error,
        "author": "tool",
    }


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


def answer(text: str) -> Message:
    return model_message("end_turn", [TextBlock(type="text", text=text)])


class FakeClient:
    """messages.create çağrılarını kaydeden, yanıtları sırayla döndüren istemci."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.messages = self

    def create(self, **kwargs) -> Message:
        self.requests.append(copy.deepcopy(kwargs))
        assert self._responses, "Beklenenden fazla model çağrısı yapıldı."
        return self._responses.pop(0)


# --- Ortam -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def environment(monkeypatch, instruction_name):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)
    monkeypatch.setenv("COPILOT_INSTRUCTION", instruction_name)
    # backend.llm import edilirken .env gerekmesin; ortamdaki değer .env'yi ezer.
    for name in LLM_VARS:
        monkeypatch.setenv(name, f"test-{name.lower()}")


@pytest.fixture
def chat(monkeypatch):
    """Sahte model ve sahte arama zarflarıyla /chat'i çağırıp olay listesi döndürür.

    `searches` her search_documents çağrısına sırayla verilecek zarfları sıralar;
    diğer tool'lar gerçek `run_tool` ile çalışır. Ağa çıkılmaz (Kod garantileri 11).
    """
    llm = importlib.import_module("backend.llm")
    monkeypatch.setattr(main, "load_llm", lambda: llm)

    def send(responses: list, searches: list[dict] | None = None):
        client = FakeClient(responses)
        monkeypatch.setattr(llm, "client", client)
        pending = [copy.deepcopy(envelope) for envelope in searches or []]
        calls: list[dict] = []

        def fake_run_tool(name: str, args: dict) -> dict:
            if name != "search_documents":
                return run_tool(name, args)
            calls.append(args)
            assert pending, "Beklenenden fazla search_documents çağrısı."
            return pending.pop(0)

        monkeypatch.setattr(agent, "run_tool", fake_run_tool)
        response = TestClient(main.app).post("/chat", json={"message": QUESTION})
        assert response.status_code == 200
        assert not pending, "Verilen arama zarflarının hepsi kullanılmadı."
        return parse_sse(response.text), calls

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


def verified(found: dict) -> dict:
    """Eşleşen parçadan beklenen citation verisi: belge alanları olduğu gibi."""
    return {
        "chunk_id": found["chunk_id"],
        "dogrulandi": True,
        "title": found["title"],
        "section": found["section"],
        "revision": found["revision"],
        "effective_from": found["effective_from"],
        "status": found["status"],
    }


def unverified(chunk_id: str) -> dict:
    return {"chunk_id": chunk_id, "dogrulandi": False}


# --- 1. Eşleşen etiket ----------------------------------------------------------


def test_eslesen_etiket_belge_alanlariyla_dogrulandi_olur(chat):
    events, _ = chat(
        [turn(1, SEARCH), answer("Düşük görüşte yeni prosedür uygulanır. [D03#02]")],
        searches=[search_envelope([D03, D04])],
    )

    assert len(of_type(events, "citation")) == 1
    assert of_type(events, "citation") == [verified(D03)]


def test_citation_alanlari_kapali_kumedir(chat):
    events, _ = chat(
        [turn(1, SEARCH), answer("Kural budur. [D03#02] Şu da var. [D99#01]")],
        searches=[search_envelope([D03])],
    )

    citations = of_type(events, "citation")
    assert len(citations) == 2
    assert set(citations[0]) == CITATION_FIELDS
    assert set(citations[1]) == {"chunk_id", "dogrulandi"}


def test_belge_alanlari_zarftan_gelir_modelin_yazdigindan_degil(chat):
    # Model belge adı ve revizyonu kendi uydurur; olay yine zarftaki değerleri taşır.
    text = "Aerodrome Manual rev. 9, 01.01.2030 [D03#02]: kural budur."
    events, _ = chat([turn(1, SEARCH), answer(text)], searches=[search_envelope([D03])])

    assert of_type(events, "citation") == [verified(D03)]
    assert "2030" not in json.dumps(of_type(events, "citation"))


def test_citation_zarf_alanlarini_yorumlamaz(chat):
    # Tarih, revizyon ve bölüm yolu çevrilmeden, biçimlendirilmeden taşınır.
    odd = chunk(
        "D07#05",
        section="Ek-3 > Düşük Görüş > Başlatma Koşulları",
        revision="3b",
        effective_from="2026-12-31",
    )
    events, _ = chat(
        [turn(1, SEARCH), answer("Başlatma koşulu budur. [D07#05]")],
        searches=[search_envelope([odd])],
    )

    assert of_type(events, "citation") == [
        {
            "chunk_id": "D07#05",
            "dogrulandi": True,
            "title": odd["title"],
            "section": "Ek-3 > Düşük Görüş > Başlatma Koşulları",
            "revision": "3b",
            "effective_from": "2026-12-31",
            "status": "active",
        }
    ]


def test_eski_surum_parcasi_status_superseded_tasir(chat):
    text = "Eski sürümde süre farklıydı. [D02#01] Yeni sürümde değişti. [D03#02]"
    events, calls = chat(
        [turn(1, SEARCH_OLD), answer(text)],
        searches=[search_envelope([D03, D02_OLD])],
    )

    assert calls == [SEARCH_OLD[1]]
    assert of_type(events, "citation") == [verified(D02_OLD), verified(D03)]
    assert of_type(events, "citation")[0]["status"] == "superseded"
    assert of_type(events, "citation")[1]["status"] == "active"


# --- 2. Eşleşmeyen etiket -------------------------------------------------------


def test_eslesmeyen_etiket_dogrulandi_false_olur_belge_alani_yok(chat):
    events, _ = chat(
        [turn(1, SEARCH), answer("Kural budur. [D99#01]")],
        searches=[search_envelope([D03, D04])],
    )

    assert of_type(events, "citation") == [unverified("D99#01")]


def test_getirilmeyen_parca_digger_belgede_olsa_da_eslesmez(chat):
    # D04#01 korpusta vardır ama bu koşuda getirilmedi; yalnızca getirilenler sayılır.
    events, _ = chat(
        [turn(1, SEARCH), answer("Kural budur. [D04#01]")],
        searches=[search_envelope([D03])],
    )

    assert of_type(events, "citation") == [unverified("D04#01")]


def test_not_found_zarfinda_her_etiket_dogrulanmaz(chat):
    events, _ = chat(
        [turn(1, SEARCH), answer("Kural budur. [D03#02]")],
        searches=[search_envelope(None)],
    )

    assert of_type(events, "citation") == [unverified("D03#02")]


def test_tool_cagrilmadiysa_etiket_dogrulanmaz(chat):
    events, calls = chat([answer("Kural budur. [D03#02]")])

    assert calls == []
    assert of_type(events, "tool_call") == []
    assert of_type(events, "citation") == [unverified("D03#02")]


def test_baska_tool_parcalari_eslesmeye_katilmaz(chat):
    # Özet tool'u çağrıldı ama arama yok; etiket bu yüzden doğrulanamaz.
    events, calls = chat(
        [turn(1, SUMMARY), answer("Kural budur. [D03#02]")],
    )

    assert calls == []
    assert len(of_type(events, "tool_call")) == 1
    assert of_type(events, "citation") == [unverified("D03#02")]


# --- 3. Sıra ve tekrar ----------------------------------------------------------


def test_citation_cevaptaki_ilk_gecis_sirasiyla_cikar(chat):
    text = "İlk kural. [D04#01] İkinci kural. [D03#02] Üçüncü kural. [D99#01]"
    events, _ = chat(
        [turn(1, SEARCH), answer(text)], searches=[search_envelope([D03, D04])]
    )

    assert [c["chunk_id"] for c in of_type(events, "citation")] == [
        "D04#01",
        "D03#02",
        "D99#01",
    ]
    assert [c["dogrulandi"] for c in of_type(events, "citation")] == [True, True, False]


def test_ayni_kimlik_birden_cok_gecse_tek_olay_cikar(chat):
    text = "Kural budur. [D03#02] Süre de aynı yerde. [D03#02] Sınır da. [D03#02]"
    events, _ = chat([turn(1, SEARCH), answer(text)], searches=[search_envelope([D03])])

    assert of_type(events, "citation") == [verified(D03)]


def test_ayni_cumlede_birden_cok_etiket_ayri_olay_olur(chat):
    events, _ = chat(
        [turn(1, SEARCH), answer("İki belge de aynı der. [D03#02][D04#01]")],
        searches=[search_envelope([D03, D04])],
    )

    assert of_type(events, "citation") == [verified(D03), verified(D04)]


def test_olay_sirasi_text_delta_sonra_citation_sonra_done(chat):
    events, _ = chat(
        [turn(1, SEARCH), answer("Kural budur. [D03#02]")],
        searches=[search_envelope([D03])],
    )

    assert kinds(events) == [
        "tool_call",
        "source_chip",
        "text_delta",
        "citation",
        "done",
    ]


def test_citationlar_son_text_delta_ile_done_arasindadir(chat):
    text = "İlk. [D03#02] İkinci. [D04#01] Üçüncü. [D99#01]"
    events, _ = chat(
        [turn(1, SEARCH), answer(text)], searches=[search_envelope([D03, D04])]
    )
    names = kinds(events)

    assert names.count("citation") == 3
    assert names.count("text_delta") >= 1
    first = names.index("citation")
    last = len(names) - 1 - names[::-1].index("citation")
    assert last - first == 2, "citation olayları bitişik olmalı"
    assert names[first - 1] == "text_delta"
    assert names[last + 1] == "done"
    assert names[-1] == "done"


# --- 4. Birden çok arama --------------------------------------------------------


def test_birden_cok_aramanin_parcalari_birlikte_eslesir(chat):
    text = "Prosedür budur. [D03#02] Buzlanma için ayrı kural var. [D04#01]"
    events, calls = chat(
        [turn(1, SEARCH), turn(2, SEARCH_OLD), answer(text)],
        searches=[search_envelope([D03]), search_envelope([D04])],
    )

    assert len(calls) == 2
    assert of_type(events, "citation") == [verified(D03), verified(D04)]


def test_ayni_kimlik_iki_aramada_gelirse_ilk_cagrinin_parcasi_kullanilir(chat):
    first = chunk("D03#02", title="İlk çağrıdaki başlık")
    second = chunk("D03#02", title="İkinci çağrıdaki başlık")
    events, _ = chat(
        [turn(1, SEARCH), turn(2, SEARCH_OLD), answer("Kural budur. [D03#02]")],
        searches=[search_envelope([first]), search_envelope([second])],
    )

    assert of_type(events, "citation") == [verified(first)]


def test_hatali_arama_zarfinin_parcalari_eslesmeye_katilmaz(chat):
    # Hata taşıyan zarfın value'su dolu olsa bile yalnızca error null olanlar sayılır.
    failed = search_envelope([D04]) | {
        "error": {"code": "SCHEMA_VALIDATION_FAILED", "message": "Hata."},
        "author": "layer",
    }
    events, _ = chat(
        [turn(1, SEARCH), turn(2, SEARCH_OLD), answer("Kural budur. [D04#01]")],
        searches=[failed, search_envelope([D03])],
    )

    assert of_type(events, "citation") == [unverified("D04#01")]


# --- 5. Etiket sayılmayanlar ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Madde [4] uygulanır.",
        "Bkz. [Madde 4] ve [EK-3].",
        "Kimlik biçimi yanlış [D3#2] ve [D03-02].",
        "Köşeli parantezsiz D03#02 yazıldı.",
        "Boş etiket [] ve [ D03#02 ].",
    ],
    ids=["sayi", "serbest-metin", "bozuk-kimlik", "parantezsiz", "bosluklu"],
)
def test_etiket_biciminde_olmayan_koseli_parantez_citation_uretmez(chat, text):
    events, _ = chat([turn(1, SEARCH), answer(text)], searches=[search_envelope([D03])])

    assert of_type(events, "text_delta"), "Cevap geldi; sınama anlamlı olsun."
    assert of_type(events, "citation") == []


# --- 6. Etiket yoksa olay yoktur ------------------------------------------------


def test_etiket_yoksa_citation_cikmaz_tool_cagrilmis_olsa_da(chat):
    # `atifsiz` bu olayla taşınmaz (docs/chat.md › Atıf olayı › Kapsam dışı).
    events, _ = chat(
        [turn(1, SEARCH), answer("Kural budur.")],
        searches=[search_envelope([D03])],
    )

    assert of_type(events, "text_delta"), "Cevap geldi; sınama anlamlı olsun."
    assert of_type(events, "citation") == []
    assert kinds(events) == ["tool_call", "source_chip", "text_delta", "done"]


def test_tool_cagrilmadi_etiket_yok_citation_yok(chat):
    events, _ = chat([answer("Bugün için ek bilgi yok.")])

    assert kinds(events) == ["text_delta", "done"]


# --- 7. Yalnızca tamam'da -------------------------------------------------------


def truncated_case():
    return [
        turn(1, SEARCH),
        model_message(
            "max_tokens", [TextBlock(type="text", text="Kural [D03#02] budu")]
        ),
    ]


def refusal_case():
    return [
        model_message("refusal", [TextBlock(type="text", text="Yapamam. [D03#02]")])
    ]


def repeat_case():
    return [turn(i, SEARCH) for i in (1, 2, 3)]


@pytest.mark.parametrize(
    ("build", "searches", "status"),
    [
        pytest.param(truncated_case, 1, "max_tokens", id="max_tokens"),
        pytest.param(refusal_case, 0, "durduruldu", id="durduruldu"),
        pytest.param(repeat_case, 2, "tekrar_siniri", id="tekrar_siniri"),
    ],
)
def test_tamam_disi_durumlarda_citation_cikmaz(chat, build, searches, status):
    events, _ = chat(
        build(), searches=[search_envelope([D03]) for _ in range(searches)]
    )

    assert of_type(events, "done")[0]["status"] == status
    assert len(of_type(events, "error")) == 1
    assert of_type(events, "text_delta") == []
    assert of_type(events, "citation") == []


# --- 8. Cevap metni değişmez ----------------------------------------------------


def test_text_delta_birlesimi_etiketli_cevaptir(chat):
    text = "Düşük görüşte yeni prosedür uygulanır. [D03#02] Eski kural kalktı. [D02#01]"
    events, _ = chat(
        [turn(1, SEARCH_OLD), answer(text)],
        searches=[search_envelope([D03, D02_OLD])],
    )

    assert len(of_type(events, "citation")) == 2
    assert "".join(d["text"] for d in of_type(events, "text_delta")) == text


def test_zarf_modele_citationdan_etkilenmeden_gider(chat):
    # Arama zarfı modele değiştirilmeden gider; citation yalnızca akışa eklenir.
    envelope = search_envelope([D03])
    llm = importlib.import_module("backend.llm")

    events, _ = chat(
        [turn(1, SEARCH), answer("Kural budur. [D03#02]")], searches=[envelope]
    )

    assert of_type(events, "citation") == [verified(D03)]
    result = llm.client.requests[1]["messages"][-1]["content"][0]
    assert json.loads(result["content"]) == envelope
