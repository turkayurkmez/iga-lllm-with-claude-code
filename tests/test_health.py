"""API anahtarı olmadan /health ve /chat davranışı."""

import sys

import pytest
from fastapi.testclient import TestClient

from backend.main import CONFIG_ERROR_MESSAGE, app

REQUIRED_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")


@pytest.fixture
def no_llm_config(monkeypatch):
    # Boş değer eksik sayılır; ortamda tanımlı olduğu için load_dotenv .env'deki değeri yazmaz.
    for name in REQUIRED_VARS:
        monkeypatch.setenv(name, "")
    # Daha önce başarıyla yüklenmiş backend.llm varsa yeniden import edilsin.
    monkeypatch.delitem(sys.modules, "backend.llm", raising=False)


def test_health_api_anahtari_olmadan_ok_doner(no_llm_config):
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_ayar_eksikken_503_ve_genel_mesaj_doner(no_llm_config):
    response = TestClient(app).post("/chat", json={"message": "merhaba"})

    assert response.status_code == 503
    assert response.json() == {"detail": CONFIG_ERROR_MESSAGE}
    for name in REQUIRED_VARS:
        assert name not in response.text
