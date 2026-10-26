"""GET /map/stands testleri (docs/canli_akis.md › Stand listesi).

Testler koddan önce yazıldı; endpoint yokken kırmızıdır. Veri COPILOT_DATA'dan okunur;
tüketiciden ve broker'dan bağımsızdır (lifespan çalıştırılmaz).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "data" / "referans" / "seed42-2026-10-20.json"

STANDS = [
    {
        "stand_code": "R201",
        "stand_type": "REMOTE",
        "max_code_letter": "C",
        "mars": False,
        "status": "UNAVAILABLE",
        "lat": 41.256,
        "lon": 28.742,
    },
    {
        "stand_code": "C101",
        "stand_type": "CONTACT",
        "max_code_letter": "E",
        "mars": True,
        "status": "AVAILABLE",
        "lat": 41.262,
        "lon": 28.742,
    },
]


def write_data(tmp_path: Path, data) -> Path:
    path = tmp_path / "gun.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def client():
    return TestClient(main.app)


def test_standlar_aynen_stand_code_sirali_doner(client, monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(write_data(tmp_path, {"stands": STANDS})))

    response = client.get("/map/stands")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"stands": [STANDS[1], STANDS[0]]}


def test_referans_veride_120_stand(client, monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", str(REFERENCE))
    source = json.loads(REFERENCE.read_text(encoding="utf-8"))["stands"]

    stands = client.get("/map/stands").json()["stands"]

    assert len(stands) == 120
    assert stands == sorted(source, key=lambda s: s["stand_code"])


def test_veri_her_istekte_yeniden_okunur(client, monkeypatch, tmp_path):
    path = write_data(tmp_path, {"stands": STANDS[:1]})
    monkeypatch.setenv("COPILOT_DATA", str(path))
    assert len(client.get("/map/stands").json()["stands"]) == 1

    path.write_text(json.dumps({"stands": STANDS}), encoding="utf-8")
    assert len(client.get("/map/stands").json()["stands"]) == 2


def assert_unavailable(response, *leaks: str) -> None:
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.json() == {"detail": main.STANDS_UNAVAILABLE_MESSAGE}
    for leak in ("COPILOT_DATA", *leaks):
        assert leak not in response.text, "Hata ayrıntısı istemciye gitmemeli"


def test_veri_degiskeni_yoksa_503(client, monkeypatch):
    monkeypatch.delenv("COPILOT_DATA", raising=False)

    assert_unavailable(client.get("/map/stands"))


def test_dosya_yoksa_503_ve_yol_sizmaz(client, monkeypatch, tmp_path):
    missing = tmp_path / "yok.json"
    monkeypatch.setenv("COPILOT_DATA", str(missing))

    assert_unavailable(client.get("/map/stands"), str(missing), "yok.json")


@pytest.mark.parametrize(
    "data",
    [
        {"flights": []},
        {"stands": {"C101": STANDS[1]}},
        {"stands": [STANDS[1], "C101"]},
    ],
    ids=["stands-yok", "stands-liste-degil", "stand-nesne-degil"],
)
def test_stands_gecersizse_503(client, monkeypatch, tmp_path, data):
    monkeypatch.setenv("COPILOT_DATA", str(write_data(tmp_path, data)))

    assert_unavailable(client.get("/map/stands"))
