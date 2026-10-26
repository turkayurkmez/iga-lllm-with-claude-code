"""Tool HTTP sarmalayıcısı sözleşme testleri (docs/http.md).

Testler koddan önce yazıldı; /tools uç noktaları yokken kırmızıdır. HTTP yalnızca
taşıyıcıdır: yanıt gövdesi, aynı ortamda backend.tools.run_tool'un döndürdüğü zarfla
birebir karşılaştırılır. Beklenen zarflar docs/http.md › Örnekler'den alınmıştır;
örnek değişirse test de değişmeli.
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.tools import run_tool, tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")

INVALID_JSON_DETAIL = {"detail": "İstek gövdesi geçerli JSON değil."}
UNEXPECTED_DETAIL = {"detail": "Beklenmeyen bir hata oluştu."}

# docs/http.md › Örnekler
SUMMARY_ALL = {
    "value": {
        "date": "2026-10-20",
        "direction": "all",
        "total": 600,
        "cancelled": 4,
        "delayed": 115,
    },
    "source": REFERENCE,
    "as_of": NOW,
    "filters": {"direction": "all"},
    "stale": False,
    "tool_version": "1.0.0",
    "error": None,
    "author": "tool",
}
NOT_FOUND = {
    "value": None,
    "source": REFERENCE,
    "as_of": NOW,
    "filters": {"query": "ZZ9999"},
    "stale": False,
    "tool_version": "1.0.0",
    "error": {"code": "NOT_FOUND", "message": "Bu kimlikle uçuş bulunamadı."},
    "author": "tool",
}
NOT_IN_SCOPE = {
    "value": None,
    "source": None,
    "as_of": None,
    "filters": {},
    "stale": False,
    "tool_version": None,
    "error": {
        "code": "CAPABILITY_NOT_IN_SCOPE",
        "message": "Bu istek copilot'un kapsamı dışında.",
    },
    "author": "layer",
}
ARGS_INVALID = {
    "value": None,
    "source": None,
    "as_of": None,
    "filters": {},
    "stale": False,
    "tool_version": "1.0.0",
    "error": {
        "code": "SCHEMA_VALIDATION_FAILED",
        "message": "Tool argümanları şemaya uymuyor.",
    },
    "author": "layer",
}


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    # source, COPILOT_DATA'nın değeri olduğu gibi döner; göreli yol için kök sabitlenir.
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def post_json(client: TestClient, name: str, body: object):
    return client.post(f"/tools/{name}", json=body)


def assert_json_headers(response) -> None:
    content_type = response.headers["content-type"].replace(" ", "").lower()
    assert content_type == "application/json;charset=utf-8"
    assert response.headers.get("cache-control") == "no-store"


def assert_carried(response, name: str, args: object, status: int) -> dict:
    """Yanıt, aynı ortamdaki run_tool zarfını birebir taşır ve durum kodu eşleşir."""
    assert response.status_code == status
    assert_json_headers(response)
    body = response.json()
    assert body == run_tool(name, args)
    assert list(body) == list(run_tool(name, args))
    return body


# ───────── GET /tools ─────────


def test_tools_listesi_tool_definitions_ile_birebir_ayni(client):
    response = client.get("/tools")

    assert response.status_code == 200
    assert_json_headers(response)
    assert response.json() == tool_definitions()


def test_tools_listesi_sozlesmedeki_sirayla_bes_tool(client):
    names = [tool["name"] for tool in client.get("/tools").json()]

    assert names == [
        "get_flight_summary",
        "resolve_flight_identity",
        "get_flight_details",
        "focus_map_object",
        "highlight_map_set",
    ]


def test_tools_listesinde_yalnizca_anthropic_tanim_alanlari_var(client):
    for tool in client.get("/tools").json():
        assert set(tool) == {"name", "description", "input_schema"}


def test_tools_listesi_zarf_degildir(client):
    body = client.get("/tools").json()

    assert isinstance(body, list)


# ───────── POST /tools/{ad}: durum kodu eşlemesi ─────────


def test_basarili_cagri_200_ve_ornek_zarf(client):
    response = post_json(client, "get_flight_summary", {"direction": "all"})

    body = assert_carried(response, "get_flight_summary", {"direction": "all"}, 200)
    assert body == SUMMARY_ALL


@pytest.mark.parametrize("direction", ["arrival", "departure"])
def test_diger_yonler_de_200_ve_birebir_tasinir(client, direction):
    args = {"direction": direction}

    assert_carried(
        post_json(client, "get_flight_summary", args), "get_flight_summary", args, 200
    )


def test_not_found_404_ve_ornek_zarf(client):
    args = {"query": "ZZ9999"}

    body = assert_carried(
        post_json(client, "resolve_flight_identity", args),
        "resolve_flight_identity",
        args,
        404,
    )
    assert body == NOT_FOUND


def test_details_not_found_404(client):
    args = {"flight_id": "FL-20261020-9999"}

    body = assert_carried(
        post_json(client, "get_flight_details", args), "get_flight_details", args, 404
    )
    assert body["error"]["code"] == "NOT_FOUND"


def test_ambiguous_entity_409_ve_adaylar_birebir(client):
    args = {"query": "TC-LSD"}

    body = assert_carried(
        post_json(client, "resolve_flight_identity", args),
        "resolve_flight_identity",
        args,
        409,
    )
    assert body["error"]["code"] == "AMBIGUOUS_ENTITY"
    assert [c["flight_id"] for c in body["value"]] == [
        "FL-20261020-0269",
        "FL-20261020-0270",
    ]


def test_tek_eslesme_200(client):
    args = {"query": "THY2345"}

    body = assert_carried(
        post_json(client, "resolve_flight_identity", args),
        "resolve_flight_identity",
        args,
        200,
    )
    assert body["value"]["flight_id"] == "FL-20261020-0270"


def test_details_basarili_200(client):
    args = {"flight_id": "FL-20261020-0270"}

    assert_carried(
        post_json(client, "get_flight_details", args), "get_flight_details", args, 200
    )


def test_bilinmeyen_tool_404_ve_ornek_zarf(client):
    body = assert_carried(post_json(client, "get_weather", {}), "get_weather", {}, 404)

    assert body == NOT_IN_SCOPE


def test_tool_adi_harf_donusumune_ugramaz(client):
    response = post_json(client, "GET_FLIGHT_SUMMARY", {"direction": "all"})

    body = assert_carried(response, "GET_FLIGHT_SUMMARY", {"direction": "all"}, 404)
    assert body["error"]["code"] == "CAPABILITY_NOT_IN_SCOPE"


def test_sema_ihlali_422_ve_ornek_zarf(client):
    args = {"direction": "ALL"}

    body = assert_carried(
        post_json(client, "get_flight_summary", args), "get_flight_summary", args, 422
    )
    assert body == ARGS_INVALID


@pytest.mark.parametrize(
    "args",
    [{}, {"direction": "all", "airline": "TK"}, {"direction": 1}],
    ids=["eksik", "ek_alan", "yanlis_tip"],
)
def test_arguman_hatalari_422(client, args):
    assert_carried(
        post_json(client, "get_flight_summary", args), "get_flight_summary", args, 422
    )


def test_veri_hatasi_da_422_ve_filters_dolu(client, monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))
    args = {"direction": "all"}

    body = assert_carried(
        post_json(client, "get_flight_summary", args), "get_flight_summary", args, 422
    )
    assert body["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert body["author"] == "layer"
    assert body["filters"] == {"direction": "all"}
    assert "yok.json" not in json.dumps(body, ensure_ascii=False)


# ───────── POST /tools/{ad}: gövde ─────────


def test_args_sarmali_desteklenmez_ek_arguman_sayilir(client):
    body = {"args": {"direction": "all"}}

    envelope = assert_carried(
        post_json(client, "get_flight_summary", body), "get_flight_summary", body, 422
    )
    assert envelope["error"]["code"] == "SCHEMA_VALIDATION_FAILED"


@pytest.mark.parametrize(
    "body", [[1], "x", None, 5], ids=["dizi", "metin", "null", "sayi"]
)
def test_nesne_olmayan_json_run_toola_gider_422(client, body):
    response = client.post(
        "/tools/get_flight_summary",
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )

    envelope = assert_carried(response, "get_flight_summary", body, 422)
    assert envelope["error"]["code"] == "SCHEMA_VALIDATION_FAILED"


def test_sorgu_dizesi_okunmaz(client):
    response = client.post(
        "/tools/get_flight_summary",
        params={"direction": "arrival"},
        json={"direction": "all"},
    )

    body = assert_carried(response, "get_flight_summary", {"direction": "all"}, 200)
    assert body["filters"] == {"direction": "all"}


def test_arguman_yalnizca_sorgu_dizesinde_ise_422(client):
    response = client.post(
        "/tools/get_flight_summary", params={"direction": "all"}, json={}
    )

    assert_carried(response, "get_flight_summary", {}, 422)


# ───────── Taşıma hataları ─────────


@pytest.mark.parametrize(
    "raw",
    [b"", b"{direction: all}", b'{"direction": "all"', b'{"direction": "\xff"}'],
    ids=["bos", "gecersiz_json", "yarim_json", "gecersiz_utf8"],
)
def test_cozulemeyen_govde_400_ve_zarf_kurulmaz(client, raw):
    response = client.post(
        "/tools/get_flight_summary",
        content=raw,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json() == INVALID_JSON_DETAIL


def test_400_govdesinde_cozumleme_ayrintisi_yok(client):
    response = client.post(
        "/tools/get_flight_summary",
        content=b"{direction: all}",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    text = response.text
    for leak in ("line", "column", "char", "Expecting", "JSONDecodeError"):
        assert leak not in text


def test_sarmalayici_hatasi_500_genel_mesaj(monkeypatch):
    def boom(name, args):
        raise RuntimeError("gizli ayrinti C:\\veri\\dosya.json")

    # Sarmalayıcı run_tool'u backend.main'e import eder (from backend.tools import ...).
    monkeypatch.setattr("backend.main.run_tool", boom)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/tools/get_flight_summary", json={"direction": "all"})

    assert response.status_code == 500
    assert response.json() == UNEXPECTED_DETAIL
    assert "gizli" not in response.text
    assert "RuntimeError" not in response.text


def test_tool_yolunda_get_405(client):
    response = client.get("/tools/get_flight_summary")

    assert response.status_code == 405


# ───────── Kurallar ─────────


def test_turkce_karakterler_kacissiz_utf8(client):
    response = post_json(client, "resolve_flight_identity", {"query": "ZZ9999"})

    assert response.status_code == 404
    assert "bulunamadı".encode() in response.content
    assert b"\\u0131" not in response.content


def test_ayni_istek_ayni_veri_ve_saatle_byte_byte_ayni(client):
    first = post_json(client, "get_flight_details", {"flight_id": "FL-20261020-0270"})
    second = post_json(client, "get_flight_details", {"flight_id": "FL-20261020-0270"})

    assert first.status_code == 200
    assert first.content == second.content


def test_veri_her_istekte_yeniden_okunur(client, monkeypatch, tmp_path):
    assert (
        post_json(client, "get_flight_summary", {"direction": "all"}).status_code == 200
    )

    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))
    response = post_json(client, "get_flight_summary", {"direction": "all"})

    assert response.status_code == 422


def test_saat_zarftan_gelir(client, monkeypatch):
    monkeypatch.setenv("COPILOT_NOW", "2026-10-20T18:00:00+03:00")

    body = post_json(client, "get_flight_summary", {"direction": "all"}).json()

    assert body["as_of"] == "2026-10-20T18:00:00+03:00"


@pytest.fixture
def no_llm_config(monkeypatch):
    # Boş değer eksik sayılır; ortamda tanımlı olduğu için load_dotenv .env'deki değeri yazmaz.
    for name in LLM_VARS:
        monkeypatch.setenv(name, "")
    monkeypatch.delitem(sys.modules, "backend.llm", raising=False)


def test_tools_api_anahtari_olmadan_calisir(no_llm_config, client):
    listing = client.get("/tools")
    call = post_json(client, "get_flight_summary", {"direction": "all"})

    assert listing.status_code == 200
    assert call.status_code == 200
    assert "backend.llm" not in sys.modules
