"""GET /rag/search sözleşmesi (docs/rag.md §7). Ağa çıkmaz, sunucu başlatılmaz.

Testler koddan önce yazıldı: uç yokken kırmızıdır. Uygulama `TestClient` ile
sürülür; indeks tmp klasöründe elle kurulmuş vektörlerle, gömme sahte Voyage
istemcisiyle çalışır.

Testin dayandığı tasarım kararları (docs'ta açık değil):
- İndeks klasörü `backend.rag.search.INDEX_DIR` modül değişkeninden ÇAĞRI ANINDA
  okunur (testler onu monkeypatch'ler); yani `search()` varsayılanı `None` olup
  çağrıda `INDEX_DIR`'e düşmelidir.
- Yanıttaki `filters` yalnızca verilen filtreleri içerir (hiç yoksa `{}`).
- Gömme hatası (Voyage çökmesi, eksik ayar) §7 tablosunda yok: 5xx ve genel
  Türkçe mesaj beklenir, ayrıntı (anahtar, istisna metni) istemciye gitmez.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.rag import embed, search

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL = "sahte-gomme-modeli"
SECRET = "gizli-anahtar-xyz"
RESULT_FIELDS = (
    "score",
    "chunk_id",
    "doc_id",
    "revision",
    "status",
    "language",
    "section",
    "text",
)

# (chunk_id, doc_id, revision, status, language, type, text, vektör).
# Sorgu "pist" → [1, 0, 0]; skor = ilk bileşen.
ROWS = [
    ("D01#01", "D01", "2", "active", "tr", "manual", "Pist kapanış kuralı: çalışma.", [1.0, 0.0, 0.0]),
    ("D01#02", "D01", "2", "active", "tr", "manual", "İkinci kural.", [0.8, 0.6, 0.0]),
    ("D02#01", "D02", "1", "superseded", "tr", "procedure", "Eski prosedür.", [0.6, 0.8, 0.0]),
    ("D03#01", "D03", "3", "active", "en", "manual", "Runway rule.", [0.0, 1.0, 0.0]),
]  # fmt: skip


def write_index(directory: Path, model: str = MODEL) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [
        {
            "doc_id": doc_id,
            "title": f"Belge {doc_id}",
            "type": type_,
            "authority": "Kurgusal Makam",
            "airport": "XXXX",
            "language": language,
            "revision": revision,
            "effective_from": "2025-03-01",
            "status": status,
            "chunk_id": chunk_id,
            "section": f"Bölüm {chunk_id}",
            "text": text,
            "context": f"[{doc_id} · Belge {doc_id} · Bölüm {chunk_id}]",
        }
        for chunk_id, doc_id, revision, status, language, type_, text, _ in ROWS
    ]
    vectors = np.asarray([row[7] for row in ROWS], dtype=np.float32)
    (directory / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    np.save(directory / "vektorler.npy", vectors, allow_pickle=False)
    meta = {
        "model": model,
        "dimension": 3,
        "chunk_count": len(chunks),
        "corpus_sha256": "0" * 64,
    }
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


class FakeVoyage:
    """Sorgu vektörünü döndürür; çağrıları kaydeder, istenirse düşer."""

    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.calls = []

    def embed(self, texts, model, input_type):
        self.calls.append(
            {"texts": list(texts), "model": model, "input_type": input_type}
        )
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(
            embeddings=[[1.0, 0.0, 0.0] for _ in texts], total_tokens=len(texts)
        )


@pytest.fixture
def index_dir(tmp_path, monkeypatch):
    directory = tmp_path / "data" / "indeks"
    write_index(directory)
    monkeypatch.setattr(search, "INDEX_DIR", directory)
    return directory


@pytest.fixture
def voyage(monkeypatch, tmp_path):
    fake = FakeVoyage()
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.setattr(embed, "sleep", lambda seconds: None)
    monkeypatch.setattr(embed, "_make_client", lambda key: fake)
    monkeypatch.setenv("VOYAGE_API_KEY", SECRET)
    monkeypatch.setenv("COPILOT_EMBED_MODEL", MODEL)
    return fake


@pytest.fixture
def client(index_dir, voyage) -> TestClient:
    return TestClient(app)


def get(client, **params):
    return client.get("/rag/search", params=params)


def ids(response) -> list[str]:
    return [r["chunk_id"] for r in response.json()["results"]]


def assert_json_utf8(response) -> None:
    content_type = response.headers["content-type"].replace(" ", "").lower()
    assert content_type == "application/json;charset=utf-8"


# ───────── 200: gövde ─────────


def test_uc_var_ve_200_doner(client):
    response = get(client, q="pist")

    assert response.status_code == 200
    assert_json_utf8(response)


def test_govde_alanlari_ve_sirasi(client):
    body = get(client, q="pist").json()

    assert list(body) == ["query", "k", "filters", "results"]


def test_query_soruyu_aynen_yansitir(client):
    assert get(client, q="pist").json()["query"] == "pist"


def test_k_verilmezse_varsayilan_bes_yansir(client):
    body = get(client, q="pist").json()

    assert body["k"] == 5
    assert len(body["results"]) == 4  # indekste yalnızca 4 parça var


def test_k_verilirse_yansir_ve_sonuc_sayisini_sinirlar(client):
    body = get(client, q="pist", k=2).json()

    assert body["k"] == 2
    assert [r["chunk_id"] for r in body["results"]] == ["D01#01", "D01#02"]


def test_filters_hic_yoksa_bos_nesne(client):
    assert get(client, q="pist").json()["filters"] == {}


def test_filters_yalnizca_verilenleri_icerir(client):
    body = get(client, q="pist", status="active", language="tr").json()

    assert body["filters"] == {"status": "active", "language": "tr"}


def test_dort_filtre_de_yansir(client):
    body = get(
        client, q="pist", status="active", language="tr", type="manual", doc_id="D01"
    ).json()

    assert body["filters"] == {
        "status": "active",
        "language": "tr",
        "type": "manual",
        "doc_id": "D01",
    }
    assert [r["chunk_id"] for r in body["results"]] == ["D01#01", "D01#02"]


def test_sonuc_alanlari_ve_degerleri(client):
    top = get(client, q="pist", k=1).json()["results"][0]

    assert set(top) >= set(RESULT_FIELDS)
    assert top["score"] == pytest.approx(1.0, abs=1e-6)
    assert top["chunk_id"] == "D01#01"
    assert top["doc_id"] == "D01"
    assert top["revision"] == "2"
    assert top["status"] == "active"
    assert top["language"] == "tr"
    assert top["section"] == "Bölüm D01#01"
    assert top["text"] == "Pist kapanış kuralı: çalışma."


def test_sonuclar_search_fonksiyonunun_dondurdugunu_birebir_tasir(client, voyage):
    expected = search.search("pist", k=3, status="active", client=voyage, model=MODEL)

    body = get(client, q="pist", k=3, status="active").json()

    assert body["results"] == expected


def test_filtreler_calisir(client):
    assert ids(get(client, q="pist", status="superseded")) == ["D02#01"]
    assert ids(get(client, q="pist", language="en")) == ["D03#01"]
    assert ids(get(client, q="pist", type="procedure")) == ["D02#01"]
    assert ids(get(client, q="pist", doc_id="D03")) == ["D03#01"]


def test_filtre_hicbir_parca_birakmazsa_200_ve_bos_liste(client):
    response = get(client, q="pist", doc_id="D99")

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["filters"] == {"doc_id": "D99"}


def test_turkce_karakterler_kacissiz_utf8(client):
    raw = get(client, q="pist", k=1).content

    assert "Pist kapanış kuralı: çalışma.".encode() in raw
    assert b"\\u" not in raw


def test_turkce_soru_yansir(client, voyage):
    body = get(client, q="pist kapanışı nedir?").json()

    assert body["query"] == "pist kapanışı nedir?"
    assert voyage.calls[0]["texts"] == ["pist kapanışı nedir?"]


def test_yanit_zarf_degildir(client):
    response = get(client, q="pist")
    assert response.status_code == 200
    body = response.json()

    for key in ("as_of", "stale", "tool_version", "author", "error", "source"):
        assert key not in body


def test_soru_query_input_type_ile_ve_indeks_modeliyle_gomulur(client, voyage):
    get(client, q="pist")

    assert len(voyage.calls) == 1
    assert voyage.calls[0]["input_type"] == "query"
    assert voyage.calls[0]["model"] == MODEL


def test_arama_indeks_dosyalarini_degistirmez(client, index_dir):
    before = {p.name: p.read_bytes() for p in index_dir.iterdir()}

    assert get(client, q="pist", k=3).status_code == 200

    assert {p.name: p.read_bytes() for p in index_dir.iterdir()} == before


def test_gercek_data_klasorune_dokunulmaz(client):
    repo_index = REPO_ROOT / "data" / "indeks"
    existed = repo_index.exists()

    assert get(client, q="pist").status_code == 200

    assert repo_index.exists() == existed


# ───────── 422: doğrulama ─────────


@pytest.mark.parametrize("q", ["", "   "])
def test_bos_q_422_ve_gomme_cagrilmaz(client, voyage, q):
    response = get(client, q=q)

    assert response.status_code == 422
    assert "detail" in response.json()
    assert voyage.calls == []


def test_q_yoksa_422(client, voyage):
    response = client.get("/rag/search")

    assert response.status_code == 422
    assert voyage.calls == []


@pytest.mark.parametrize("k", ["0", "-1", "21", "100", "abc", "1.5", ""])
def test_k_1_20_disinda_ya_da_sayi_degilse_422(client, voyage, k):
    response = get(client, q="pist", k=k)

    assert response.status_code == 422
    assert voyage.calls == []


@pytest.mark.parametrize("k", [1, 20])
def test_k_siniri_dahil_200(client, k):
    response = get(client, q="pist", k=k)

    assert response.status_code == 200
    assert response.json()["k"] == k


# ───────── 503: indeks yok / model farklı ─────────


def test_indeks_yoksa_503_index_not_ready(client, index_dir):
    for path in index_dir.iterdir():
        path.unlink()
    index_dir.rmdir()

    response = get(client, q="pist")

    assert response.status_code == 503
    assert_json_utf8(response)
    body = response.json()
    assert list(body) == ["error"]
    assert list(body["error"]) == ["code", "message"]
    assert body["error"]["code"] == "INDEX_NOT_READY"
    assert body["error"]["message"]


def test_indeks_dosyalarindan_biri_eksikse_503(client, index_dir, voyage):
    (index_dir / "vektorler.npy").unlink()

    response = get(client, q="pist")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INDEX_NOT_READY"
    assert voyage.calls == []


def test_model_farkliysa_503_index_model_mismatch(client, voyage, monkeypatch):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    response = get(client, q="pist")

    assert response.status_code == 503
    assert_json_utf8(response)
    body = response.json()
    assert list(body) == ["error"]
    assert list(body["error"]) == ["code", "message"]
    assert body["error"]["code"] == "INDEX_MODEL_MISMATCH"
    assert body["error"]["message"]
    assert voyage.calls == []


def test_hata_mesajlari_turkce_ve_anahtar_icermez(client, monkeypatch):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    response = get(client, q="pist")
    text = response.text

    assert response.status_code == 503
    assert SECRET not in text
    assert "Traceback" not in text


def test_indeks_hatasi_dogrulama_hatasindan_sonra_gelir(client, index_dir):
    # Geçersiz k, indeks olmasa da 422'dir (istek önce doğrulanır).
    for path in index_dir.iterdir():
        path.unlink()
    index_dir.rmdir()

    assert get(client, q="pist", k=0).status_code == 422


# ───────── Gömme hataları: istemciye ayrıntı gitmez ─────────


def test_voyage_hatasi_5xx_ve_ayrinti_sizmaz(client, voyage):
    voyage.fail = RuntimeError(f"sır: {SECRET}")

    response = get(client, q="pist")

    assert response.status_code >= 500
    assert SECRET not in response.text
    assert "sır" not in response.text
    assert "Traceback" not in response.text
    assert response.json()["detail"] or response.json()["error"]["message"]


def test_eksik_voyage_anahtari_5xx_ve_anahtar_adi_disinda_ayrinti_yok(
    client, monkeypatch
):
    monkeypatch.delenv("VOYAGE_API_KEY")
    monkeypatch.setattr(embed, "_make_client", lambda key: FakeVoyage())

    response = get(client, q="pist")

    assert response.status_code >= 500
    assert "Traceback" not in response.text


# ───────── Yöntem ve çevre ─────────


def test_post_405(client):
    assert client.post("/rag/search", json={"q": "pist"}).status_code == 405


def test_rag_istegi_anthropic_ayari_gerektirmez(client, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL"):
        monkeypatch.setenv(name, "")

    assert get(client, q="pist").status_code == 200


def test_health_etkilenmez(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_vite_proxy_rag_yolunu_icerir():
    # CLAUDE.md: yeni endpoint eklenince frontend/vite.config.ts proxy listesine de girer.
    config = (REPO_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")

    assert "'/rag': backend" in config
