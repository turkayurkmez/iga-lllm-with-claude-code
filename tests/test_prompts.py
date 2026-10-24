"""System talimatı sözleşme testleri (docs/system-talimat.md › Testler).

Testler koddan önce yazıldı; talimat sözleşmeye uydurulana kadar sürüm, değişiklik
günlüğü, tool adı, hata kodu ve "canlı veri yok" testleri kırmızıdır. Gerçek API
çağrısı yapılmaz: /chat testi sahte bir istemciyle çalışır. Ücretli ölçüm
testleri pytest'e girmez.
"""

import copy
import importlib
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import Message, TextBlock, Usage
from fastapi.testclient import TestClient

from backend import main, prompts
from backend.envelope import ErrorCode
from backend.tools import tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "docs" / "system-talimat.md"
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")

# İlke 5'te adıyla geçen dört kod; STALE_DATA İlke 6'da davranışla anlatılır.
PRINCIPLE_CODES = {
    "NOT_FOUND",
    "AMBIGUOUS_ENTITY",
    "SCHEMA_VALIDATION_FAILED",
    "CAPABILITY_NOT_IN_SCOPE",
}
# Alt çizgili büyük harf kelime; "AOCC", "İGA" gibi kısaltmalar kod sayılmaz.
CODE_PATTERN = re.compile(r"\b[A-Z]+(?:_[A-Z]+)+\b")
SNAKE_CASE_PATTERN = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
# Somut operasyon verisi: rakam, sefer no, tescil, stand ve dosya yolu.
OPERATIONAL_PATTERNS = {
    "rakam": re.compile(r"\d"),
    "sefer no": re.compile(r"\b(?:TK|THY)\d+"),
    "tescil": re.compile(r"\bTC-[A-Z]{3}\b"),
    "dosya uzantısı": re.compile(r"[\w-]+\.(?:json|py|md|csv)\b"),
    "dosya yolu": re.compile(r"\b(?:data|synth|backend|docs)[/\\]"),
}


def changelog_last_version() -> str:
    """Belgenin Değişiklik günlüğü tablosundaki son satırın sürüm hücresi."""
    text = CONTRACT.read_text(encoding="utf-8")
    _, _, section = text.partition("## Değişiklik günlüğü")
    assert section, "docs/system-talimat.md içinde Değişiklik günlüğü bölümü yok."
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("|") and not line.startswith("|---")
    ]
    # İlk satır başlıktır.
    assert len(rows) >= 2, "Değişiklik günlüğünde satır yok."
    return rows[-1].split("|")[1].strip().strip("`")


class FakeMessages:
    """/chat'in agent döngüsünün messages.create çağrılarını kaydeder."""

    def __init__(self):
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return Message(
            id="msg_test",
            type="message",
            role="assistant",
            model="test-model",
            content=[TextBlock(type="text", text="Merhaba.")],
            stop_reason="end_turn",
            stop_sequence=None,
            usage=Usage(input_tokens=1, output_tokens=1),
        )


@pytest.fixture
def fake_llm(monkeypatch):
    # Döngü backend.llm'i kendisi de import eder; .env gerekmesin diye ortam verilir.
    for name in LLM_VARS:
        monkeypatch.setenv(name, f"test-{name.lower()}")
    messages = FakeMessages()
    llm = importlib.import_module("backend.llm")
    monkeypatch.setattr(llm, "client", SimpleNamespace(messages=messages))
    monkeypatch.setattr(main, "load_llm", lambda: llm)
    return messages


def test_chat_ayni_talimati_gonderir(fake_llm):
    response = TestClient(main.app).post("/chat", json={"message": "merhaba"})

    assert response.status_code == 200
    assert "event: done" in response.text
    assert len(fake_llm.requests) == 1
    assert fake_llm.requests[0]["system"] == prompts.SYSTEM_INSTRUCTIONS


def test_chat_bilinmeyen_talimat_surumunde_503_ve_model_cagrilmaz(
    fake_llm, monkeypatch
):
    monkeypatch.setenv("COPILOT_INSTRUCTION", "v999")

    response = TestClient(main.app).post("/chat", json={"message": "merhaba"})

    assert response.status_code == 503
    assert response.json() == {"detail": main.CONFIG_ERROR_MESSAGE}
    assert "v999" not in response.text
    assert fake_llm.requests == []


def test_surum_bicimi_gecerli():
    version = getattr(prompts, "SYSTEM_INSTRUCTIONS_VERSION", None)

    assert isinstance(version, str), "SYSTEM_INSTRUCTIONS_VERSION tanımlı değil."
    assert VERSION_PATTERN.match(version), version


def test_surum_degisiklik_gunlugunde_var():
    version = getattr(prompts, "SYSTEM_INSTRUCTIONS_VERSION", None)

    assert isinstance(version, str), "SYSTEM_INSTRUCTIONS_VERSION tanımlı değil."
    assert changelog_last_version() == version


def test_talimat_turkce_ve_tek_parca():
    text = prompts.SYSTEM_INSTRUCTIONS

    assert isinstance(text, str)
    assert text.strip()
    assert "{" not in text
    assert "}" not in text


@pytest.mark.parametrize("kind", OPERATIONAL_PATTERNS)
def test_talimatta_operasyon_verisi_yok(kind):
    found = OPERATIONAL_PATTERNS[kind].findall(prompts.SYSTEM_INSTRUCTIONS)

    assert found == [], f"Talimatta {kind} var: {found}"


def test_talimatta_model_adi_yok():
    from backend.llm import MODEL, TEMP_MODEL

    for name in (MODEL, TEMP_MODEL):
        assert name not in prompts.SYSTEM_INSTRUCTIONS


def test_talimat_kayitli_tool_adlarini_kullanir():
    registered = {definition["name"] for definition in tool_definitions()}
    mentioned = set(SNAKE_CASE_PATTERN.findall(prompts.SYSTEM_INSTRUCTIONS))

    assert mentioned <= registered, (
        f"Kayıtlı olmayan tool adı: {mentioned - registered}"
    )
    # İlke 4 üç tool'un sırasını adlarıyla verir.
    assert registered <= mentioned, f"Talimatta geçmeyen tool: {registered - mentioned}"


def test_talimat_hata_kodlarini_dogru_yazar():
    known = {code.value for code in ErrorCode}
    mentioned = set(CODE_PATTERN.findall(prompts.SYSTEM_INSTRUCTIONS))

    assert mentioned <= known, f"Zarfta olmayan hata kodu: {mentioned - known}"
    assert PRINCIPLE_CODES <= mentioned, (
        f"İlke 5'te geçmesi gereken kod eksik: {PRINCIPLE_CODES - mentioned}"
    )


def test_canli_veri_yok_ifadesi_kalmadi():
    assert "erişimin yok" not in prompts.SYSTEM_INSTRUCTIONS.casefold()
