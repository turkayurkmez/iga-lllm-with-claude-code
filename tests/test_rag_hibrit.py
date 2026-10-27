"""`method` seçimi ve hibrit arama sözleşmesi (docs/hibrit.md › Yöntemler, Hibrit).

Ağa çıkmaz, `.env` gerektirmez; Voyage sahte istemcidir. Testler koddan önce
yazıldı: `search(method="hybrid")` yokken kırmızıdır. BM25'in kendi sözleşmesi
`tests/test_rag_bm25.py`'de, kaynak önceliği (`priority`) burada yok.

Sözleşmenin test için sabitlenen adları (docs'ta açık değil):
- `search.METHODS == ("vector", "bm25", "hybrid")`; geçersiz `method` `ValueError`.
- `search(..., rrf_candidates=20, rrf_k=60)`: aday sayısı ve RRF sabiti.
- `scripts/rag_ara.py --method {vector,bm25,hybrid}` (varsayılan `vector`).
- `GET /rag/search?method=`: geçersiz değer 422; hibrit yanıtında `method` alanı.

Veri kümesi (sorgu "pist", sorgu vektörü [1, 0, 0]; 6 parça):
  vektör sırası: D01#01, D01#02, D02#01, D03#01, D02#02, D03#02
  bm25 sırası:   D03#01 (tf 3), D02#01 (tf 2), D01#02 (tf 1); diğerlerinde "pist" yok
RRF (60): D03#01 = 1/64 + 1/61, D01#02 = 1/62 + 1/63, D02#01 = 1/63 + 1/62,
D01#01 = 1/61, D02#02 = 1/65, D03#02 = 1/66 → D01#02 ile D02#01 tam eşit.
"""

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.rag import embed, search

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rag_ara.py"
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

# (chunk_id, doc_id, status, language, type, text, vektör)
ROWS = [
    ("D01#01", "D01", "active", "tr", "manual", "kapat kapat stand", [1.0, 0.0, 0.0]),
    ("D01#02", "D01", "active", "tr", "manual", "pist kapat stand", [0.8, 0.6, 0.0]),
    ("D02#01", "D02", "superseded", "tr", "procedure", "pist pist kapat", [0.6, 0.8, 0.0]),
    ("D03#01", "D03", "active", "en", "manual", "pist pist pist", [0.28, 0.96, 0.0]),
    ("D02#02", "D02", "superseded", "tr", "procedure", "stand stand kapat", [0.0, 1.0, 0.0]),
    ("D03#02", "D03", "active", "en", "manual", "kapat stand stand", [-1.0, 0.0, 0.0]),
]  # fmt: skip
VECTOR_ORDER = ["D01#01", "D01#02", "D02#01", "D03#01", "D02#02", "D03#02"]
BM25_ORDER = ["D03#01", "D02#01", "D01#02"]
HYBRID_ORDER = ["D03#01", "D01#02", "D02#01", "D01#01", "D02#02", "D03#02"]


def rrf(*ranks: int, c: int = 60) -> float:
    return sum(1 / (c + rank) for rank in ranks)


HYBRID_SCORES = {
    "D03#01": rrf(4, 1),
    "D01#02": rrf(2, 3),
    "D02#01": rrf(3, 2),
    "D01#01": rrf(1),
    "D02#02": rrf(5),
    "D03#02": rrf(6),
}


def make_chunk(chunk_id, doc_id, status, language, type_, text) -> dict:
    return {
        "doc_id": doc_id,
        "title": f"Belge {doc_id}",
        "type": type_,
        "authority": "Kurgusal Makam",
        "airport": "XXXX",
        "language": language,
        "revision": "1",
        "effective_from": "2025-03-01",
        "status": status,
        "chunk_id": chunk_id,
        "section": f"Bölüm {chunk_id}",
        "text": text,
        "context": f"[{doc_id} · Belge {doc_id} · Bölüm {chunk_id}]",
    }


def write_index(directory: Path, rows, model: str = MODEL) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [make_chunk(*row[:6]) for row in rows]
    vectors = np.asarray([row[6] for row in rows], dtype=np.float32)
    (directory / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    np.save(directory / "vektorler.npy", vectors, allow_pickle=False)
    meta = {
        "model": model,
        "dimension": int(vectors.shape[1]),
        "chunk_count": len(chunks),
        "corpus_sha256": "0" * 64,
    }
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


class FakeClient:
    """Her sorguyu [1, 0, 0] vektörüne çevirir; çağrıları kaydeder, istenirse düşer."""

    def __init__(self, dimension: int = 3, fail: Exception | None = None):
        self.dimension = dimension
        self.fail = fail
        self.calls = []

    def embed(self, texts, model, input_type):
        self.calls.append(
            {"texts": list(texts), "model": model, "input_type": input_type}
        )
        if self.fail is not None:
            raise self.fail
        vector = [1.0] + [0.0] * (self.dimension - 1)
        return SimpleNamespace(
            embeddings=[list(vector) for _ in texts], total_tokens=len(texts)
        )


@pytest.fixture
def index_dir(tmp_path):
    directory = tmp_path / "data" / "indeks"
    write_index(directory, list(reversed(ROWS)))
    return directory


@pytest.fixture
def client():
    return FakeClient()


def run(index_dir, client, query="pist", **kwargs):
    kwargs.setdefault("model", MODEL)
    return search.search(query, index_dir=index_dir, client=client, **kwargs)


def ids(results) -> list[str]:
    return [r["chunk_id"] for r in results]


# ───────── method seçimi ─────────


def test_gecerli_yontemler():
    assert search.METHODS == ("vector", "bm25", "hybrid")


def test_varsayilan_yontem_vector(index_dir, client):
    default = run(index_dir, client, k=6)
    explicit = run(index_dir, client, k=6, method="vector")

    assert ids(default) == VECTOR_ORDER
    assert default == explicit


def test_her_yontem_kendi_siralamasini_verir(index_dir, client):
    vector = ids(run(index_dir, client, k=6, method="vector"))
    bm25 = ids(run(index_dir, client, k=6, method="bm25"))
    hybrid = ids(run(index_dir, client, k=6, method="hybrid"))

    assert vector == VECTOR_ORDER
    assert bm25 == BM25_ORDER
    assert hybrid == HYBRID_ORDER
    assert len({tuple(vector), tuple(bm25), tuple(hybrid)}) == 3


@pytest.mark.parametrize("method", ["vector", "bm25", "hybrid"])
def test_sonuc_alanlari_uc_yontemde_ayni(index_dir, client, method):
    results = run(index_dir, client, k=6, method=method)

    assert results
    for result in results:
        for field in RESULT_FIELDS:
            assert field in result, field
        assert type(result["score"]) is float
        assert result["text"] == next(
            row[5] for row in ROWS if row[0] == result["chunk_id"]
        )


@pytest.mark.parametrize(
    "method", ["bilinmeyen", "", "BM25", "Hybrid", "hibrit", "vektor", "keyword"]
)
def test_gecersiz_yontem_value_error(index_dir, client, method):
    with pytest.raises(ValueError) as info:
        run(index_dir, client, method=method)

    assert client.calls == []
    message = str(info.value)
    for valid in ("vector", "bm25", "hybrid"):
        assert valid in message


@pytest.mark.parametrize("method", ["vector", "bm25", "hybrid"])
def test_bos_soru_her_yontemde_reddedilir_ve_gomulmez(index_dir, client, method):
    with pytest.raises(ValueError):
        run(index_dir, client, query="   ", method=method)

    assert client.calls == []


@pytest.mark.parametrize("method", ["vector", "bm25", "hybrid"])
def test_k_sifir_her_yontemde_reddedilir(index_dir, client, method):
    with pytest.raises(ValueError):
        run(index_dir, client, k=0, method=method)


@pytest.mark.parametrize("method", ["vector", "bm25", "hybrid"])
@pytest.mark.parametrize(
    ("filters", "allowed"),
    [
        ({"status": "superseded"}, {"D02#01", "D02#02"}),
        ({"language": "en"}, {"D03#01", "D03#02"}),
        ({"type": "procedure"}, {"D02#01", "D02#02"}),
        ({"doc_id": "D03"}, {"D03#01", "D03#02"}),
    ],
)
def test_dort_filtre_uc_yontemde_ayni_calisir(
    index_dir, client, method, filters, allowed
):
    results = run(index_dir, client, k=6, method=method, **filters)

    assert results
    assert set(ids(results)) <= allowed


@pytest.mark.parametrize("method", ["vector", "bm25", "hybrid"])
def test_filtre_hicbir_parca_birakmazsa_bos_liste(index_dir, client, method):
    assert run(index_dir, client, method=method, doc_id="D99") == []


@pytest.mark.parametrize("method", ["vector", "bm25", "hybrid"])
def test_yontem_indeksi_degistirmez(index_dir, client, method):
    before = {p.name: p.read_bytes() for p in index_dir.iterdir()}

    run(index_dir, client, k=6, method=method)

    assert {p.name: p.read_bytes() for p in index_dir.iterdir()} == before


def test_vector_yontemi_m51_sozlesmesini_korur(index_dir, client):
    results = run(index_dir, client, k=6, method="vector")

    assert ids(results) == VECTOR_ORDER
    assert [r["score"] for r in results] == pytest.approx(
        [1.0, 0.8, 0.6, 0.28, 0.0, -1.0], abs=1e-6
    )


# ───────── Hibrit: RRF ─────────


def test_hibrit_birlesik_skor_rrf_toplamidir(index_dir, client):
    results = run(index_dir, client, k=6, method="hybrid")

    assert ids(results) == HYBRID_ORDER
    assert {r["chunk_id"]: r["score"] for r in results} == pytest.approx(
        HYBRID_SCORES, abs=1e-12
    )


def test_hibrit_skoru_rrf_formulu_1_bolu_60_arti_sira(index_dir, client):
    results = run(index_dir, client, k=6, method="hybrid")
    by_id = {r["chunk_id"]: r["score"] for r in results}

    # Yalnızca vektör listesinde olan parça: tek terim, sıra 1'den başlar.
    assert by_id["D01#01"] == pytest.approx(1 / 61, abs=1e-12)
    # Her iki listede olan parça: iki terim toplanır.
    assert by_id["D03#01"] == pytest.approx(1 / 64 + 1 / 61, abs=1e-12)


def test_parca_iki_listede_de_ise_tek_listedekinden_once_gelebilir(index_dir, client):
    # D03#01 vektörde 4., bm25'te 1.: vektörde 2. olan D01#02'yi geçer.
    order = ids(run(index_dir, client, k=6, method="hybrid"))

    assert order.index("D03#01") < order.index("D01#02")
    assert order.index("D03#01") < order.index("D01#01")


def test_bm25_listesinde_olmayan_parca_yalnizca_vektor_terimini_alir(
    index_dir, client
):
    results = run(index_dir, client, k=6, method="hybrid")
    by_id = {r["chunk_id"]: r["score"] for r in results}

    # "pist" geçmeyen üç parça bm25 listesinde yok: yalnızca 1/(60 + vektör sırası).
    assert by_id["D01#01"] == pytest.approx(1 / 61, abs=1e-12)
    assert by_id["D02#02"] == pytest.approx(1 / 65, abs=1e-12)
    assert by_id["D03#02"] == pytest.approx(1 / 66, abs=1e-12)


def test_skor_azalan_sirada(index_dir, client):
    scores = [r["score"] for r in run(index_dir, client, k=6, method="hybrid")]

    assert scores == sorted(scores, reverse=True)


def test_esit_skorda_vektor_sirasi_once_gelir(index_dir, client):
    # D01#02 (vektör 2.) ve D02#01 (vektör 3.) tam eşit: 1/62 + 1/63.
    results = run(index_dir, client, k=6, method="hybrid")
    by_id = {r["chunk_id"]: r["score"] for r in results}

    assert by_id["D01#02"] == by_id["D02#01"]
    assert ids(results).index("D01#02") < ids(results).index("D02#01")


def test_hibrit_vektor_listesinde_olmayan_parca_esitlikte_vektordekinden_sonra(
    index_dir, client
):
    # 2 aday: vektör [D01#01, D01#02], bm25 [D03#01, D02#01].
    # D01#01 ile D03#01 → 1/61 eşit; D01#02 ile D02#01 → 1/62 eşit.
    results = run(index_dir, client, k=6, method="hybrid", rrf_candidates=2)

    assert ids(results) == ["D01#01", "D03#01", "D01#02", "D02#01"]
    assert [r["score"] for r in results] == pytest.approx(
        [1 / 61, 1 / 61, 1 / 62, 1 / 62], abs=1e-12
    )


def test_hibrit_k_kadar_sonuc_doner(index_dir, client):
    assert ids(run(index_dir, client, k=1, method="hybrid")) == HYBRID_ORDER[:1]
    assert ids(run(index_dir, client, k=3, method="hybrid")) == HYBRID_ORDER[:3]


def test_hibrit_varsayilan_k_bes(index_dir, client):
    results = run(index_dir, client, method="hybrid")

    assert ids(results) == HYBRID_ORDER[:5]


def test_hibrit_k_parca_sayisindan_buyukse_hepsi_doner(index_dir, client):
    assert ids(run(index_dir, client, k=20, method="hybrid")) == HYBRID_ORDER


def test_ayni_soru_ayni_hibrit_sonuc(index_dir, client):
    assert run(index_dir, client, k=6, method="hybrid") == run(
        index_dir, client, k=6, method="hybrid"
    )


def test_hibrit_indeks_sirasindan_bagimsiz(tmp_path, client):
    forward = tmp_path / "ileri"
    backward = tmp_path / "geri"
    write_index(forward, ROWS)
    write_index(backward, list(reversed(ROWS)))

    assert run(forward, client, k=6, method="hybrid") == run(
        backward, client, k=6, method="hybrid"
    )


# ───────── Hibrit: adaylar ve sabit ayarlanabilir ─────────


def test_rrf_sabiti_ayarlanabilir(index_dir, client):
    results = run(index_dir, client, k=6, method="hybrid", rrf_k=0)

    # Sabit 0: skor = Σ 1 / sıra.
    assert ids(results) == [
        "D03#01",
        "D01#01",
        "D01#02",
        "D02#01",
        "D02#02",
        "D03#02",
    ]
    assert {r["chunk_id"]: r["score"] for r in results} == pytest.approx(
        {
            "D03#01": 1 / 4 + 1 / 1,
            "D01#01": 1 / 1,
            "D01#02": 1 / 2 + 1 / 3,
            "D02#01": 1 / 3 + 1 / 2,
            "D02#02": 1 / 5,
            "D03#02": 1 / 6,
        },
        abs=1e-12,
    )


def test_varsayilan_aday_sayisi_20_sabit_60(index_dir, client):
    default = run(index_dir, client, k=6, method="hybrid")
    explicit = run(
        index_dir, client, k=6, method="hybrid", rrf_candidates=20, rrf_k=60
    )

    assert default == explicit


def test_aday_sayisi_ayarlanabilir(index_dir, client):
    results = run(index_dir, client, k=6, method="hybrid", rrf_candidates=1)

    # Her listeden yalnızca birincisi: vektör D01#01, bm25 D03#01.
    assert ids(results) == ["D01#01", "D03#01"]


@pytest.fixture
def wide_index(tmp_path):
    """25 parça; vektör sırası chunk_id sırası. Yalnızca sonuncuda "pist" var."""
    rows = []
    for number in range(1, 26):
        angle = number * 0.05
        text = "pist" if number == 25 else "kapat"
        rows.append(
            (
                f"D01#{number:02d}",
                "D01",
                "active",
                "tr",
                "manual",
                text,
                [math.cos(angle), math.sin(angle)],
            )
        )
    directory = tmp_path / "genis"
    write_index(directory, rows)
    return directory


def test_her_listeden_ilk_20_aday_alinir(wide_index):
    client = FakeClient(dimension=2)

    results = run(wide_index, client, k=25, method="hybrid")

    # Vektör listesinde yalnızca ilk 20 var. D01#25 vektör 25.: yalnızca bm25 terimi
    # (1/61), bu yüzden D01#01 ile eşit; eşitlikte vektördeki D01#01 önce gelir.
    # 21-24. parçaların hiçbir listede terimi yok: sonuçta değiller.
    expected = ["D01#01", "D01#25"] + [f"D01#{n:02d}" for n in range(2, 21)]
    assert ids(results) == expected
    assert results[1]["score"] == pytest.approx(1 / 61, abs=1e-12)
    assert results[0]["score"] == results[1]["score"]


def test_aday_sinirsiz_olsaydi_d01_25_vektor_terimini_de_alirdi(wide_index):
    client = FakeClient(dimension=2)

    results = run(
        wide_index, client, k=25, method="hybrid", rrf_candidates=25
    )

    assert results[0]["chunk_id"] == "D01#25"
    assert results[0]["score"] == pytest.approx(1 / 61 + 1 / 85, abs=1e-12)
    assert len(results) == 25


def test_k_aday_sayisindan_bagimsiz(wide_index):
    client = FakeClient(dimension=2)

    assert ids(run(wide_index, client, k=3, method="hybrid")) == [
        "D01#01",
        "D01#25",
        "D01#02",
    ]


# ───────── Hibrit: bm25 eşleşmesi yok / filtre ─────────


def test_bm25_eslesmesi_yoksa_hibrit_vektor_sirasini_izler(index_dir, client):
    results = run(index_dir, client, query="yagmur", k=6, method="hybrid")

    assert ids(results) == VECTOR_ORDER
    assert [r["score"] for r in results] == pytest.approx(
        [1 / (60 + rank) for rank in range(1, 7)], abs=1e-12
    )


def test_vektor_listesinde_negatif_skorlu_parca_da_aday(index_dir, client):
    # Skor eşiği yok (M5.1): D03#02 (iç çarpım -1) hibritte son sırada yer alır.
    results = run(index_dir, client, k=6, method="hybrid")

    assert results[-1]["chunk_id"] == "D03#02"
    assert results[-1]["score"] == pytest.approx(1 / 66, abs=1e-12)


def test_hibrit_filtre_adaylardan_once_uygulanir(index_dir, client):
    # Süzülmüş küme: D02#01, D02#02. Vektör: D02#01 (1.), D02#02 (2.); bm25:
    # D02#01 (1.). Süzülmemiş sıralar (3. ve 5.) kullanılsaydı skorlar farklı olurdu.
    results = run(index_dir, client, k=6, method="hybrid", status="superseded")

    assert ids(results) == ["D02#01", "D02#02"]
    assert [r["score"] for r in results] == pytest.approx(
        [1 / 61 + 1 / 61, 1 / 62], abs=1e-12
    )


def test_hibrit_dil_filtresi_siralari_sifirdan_kurar(index_dir, client):
    results = run(index_dir, client, k=6, method="hybrid", language="en")

    assert ids(results) == ["D03#01", "D03#02"]
    assert [r["score"] for r in results] == pytest.approx(
        [1 / 61 + 1 / 61, 1 / 62], abs=1e-12
    )


# ───────── Hibrit: gömme ve model ─────────


def test_hibrit_soruyu_bir_kez_query_olarak_gomer(index_dir, client):
    run(index_dir, client, method="hybrid")

    assert len(client.calls) == 1
    assert client.calls[0]["input_type"] == "query"
    assert client.calls[0]["model"] == MODEL
    assert client.calls[0]["texts"] == ["pist"]


def test_vector_soruyu_bir_kez_gomer(index_dir, client):
    run(index_dir, client, method="vector")

    assert len(client.calls) == 1


def test_bm25_soruyu_gommez(index_dir, client):
    run(index_dir, client, method="bm25")

    assert client.calls == []


def test_hibrit_model_farkliysa_reddedilir_ve_gomme_cagrilmaz(index_dir, client):
    with pytest.raises(search.IndexModelMismatchError) as info:
        run(index_dir, client, model="baska-model", method="hybrid")

    assert info.value.code == "INDEX_MODEL_MISMATCH"
    assert client.calls == []


def test_hibrit_indeks_yoksa_index_not_ready(tmp_path, client):
    with pytest.raises(search.IndexNotReadyError):
        run(tmp_path / "yok", client, method="hybrid")

    assert client.calls == []


def test_hibrit_gomme_ayari_yoksa_embed_config_error(
    index_dir, monkeypatch, tmp_path
):
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_EMBED_MODEL", raising=False)

    with pytest.raises(embed.EmbedConfigError):
        search.search("pist", index_dir=index_dir, method="hybrid")


def test_hibrit_gomme_hatasi_yayilir(index_dir):
    client = FakeClient(fail=RuntimeError("gomme patladi"))

    with pytest.raises(embed.EmbedError):
        run(index_dir, client, method="hybrid")


# ───────── HTTP: GET /rag/search?method= ─────────


class FakeVoyage(FakeClient):
    pass


@pytest.fixture
def http_index(tmp_path, monkeypatch):
    directory = tmp_path / "data" / "indeks"
    write_index(directory, ROWS)
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
def http(http_index, voyage) -> TestClient:
    return TestClient(app)


def get(http, **params):
    return http.get("/rag/search", params=params)


def http_ids(response) -> list[str]:
    return [r["chunk_id"] for r in response.json()["results"]]


def test_http_varsayilan_vector(http):
    assert http_ids(get(http, q="pist", k=6)) == VECTOR_ORDER
    assert http_ids(get(http, q="pist", k=6, method="vector")) == VECTOR_ORDER


def test_http_bm25(http, voyage):
    response = get(http, q="pist", k=6, method="bm25")

    assert response.status_code == 200
    assert http_ids(response) == BM25_ORDER
    assert voyage.calls == []


def test_http_hybrid(http, voyage):
    response = get(http, q="pist", k=6, method="hybrid")

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "hybrid"
    assert [r["chunk_id"] for r in body["results"]] == HYBRID_ORDER
    assert [r["score"] for r in body["results"]] == pytest.approx(
        [HYBRID_SCORES[cid] for cid in HYBRID_ORDER], abs=1e-12
    )
    assert len(voyage.calls) == 1
    assert voyage.calls[0]["input_type"] == "query"


def test_http_hybrid_k_ve_filtre(http):
    response = get(http, q="pist", k=1, method="hybrid", language="en")

    assert response.status_code == 200
    assert http_ids(response) == ["D03#01"]
    assert response.json()["filters"] == {"language": "en"}


@pytest.mark.parametrize("method", ["bilinmeyen", "BM25", "hibrit", "vektor", ""])
def test_http_gecersiz_method_422(http, voyage, method):
    response = get(http, q="pist", method=method)

    assert response.status_code == 422
    assert voyage.calls == []


def test_http_hybrid_eslesme_yoksa_bos_degil_vektor_sonucu(http):
    response = get(http, q="yagmur", k=3, method="hybrid")

    assert response.status_code == 200
    assert http_ids(response) == VECTOR_ORDER[:3]


def test_http_hybrid_filtre_hicbir_parca_birakmazsa_bos_liste(http):
    response = get(http, q="pist", method="hybrid", doc_id="D99")

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_http_hybrid_model_farkliysa_503(http, voyage, monkeypatch):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    response = get(http, q="pist", method="hybrid")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INDEX_MODEL_MISMATCH"
    assert voyage.calls == []


def test_http_bm25_model_farkli_olsa_da_200(http, monkeypatch):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    assert get(http, q="pist", method="bm25").status_code == 200


def test_http_hybrid_indeks_yoksa_503(http, tmp_path, monkeypatch):
    monkeypatch.setattr(search, "INDEX_DIR", tmp_path / "yok")

    response = get(http, q="pist", method="hybrid")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INDEX_NOT_READY"


def test_http_hybrid_gomme_hatasinda_503_ve_sir_sizmaz(http, voyage):
    voyage.fail = RuntimeError(f"sır: {SECRET}")

    response = get(http, q="pist", method="hybrid")

    assert response.status_code == 503
    assert SECRET not in response.text


def test_http_bm25_gomme_hatasindan_etkilenmez(http, voyage):
    voyage.fail = RuntimeError(f"sır: {SECRET}")

    response = get(http, q="pist", method="bm25")

    assert response.status_code == 200
    assert http_ids(response) == BM25_ORDER


# ───────── scripts/rag_ara.py --method ─────────


def load_script():
    assert SCRIPT.exists(), "scripts/rag_ara.py yok"
    spec = importlib.util.spec_from_file_location("rag_ara_hibrit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cli(module, directory, *args):
    return module.main(["pist", "--indeks", str(directory), "-k", "6", *args])


def printed_order(out: str) -> list[str]:
    found = [(out.index(cid), cid) for cid in VECTOR_ORDER if cid in out]
    return [cid for _, cid in sorted(found)]


@pytest.fixture
def cli_env(http_index, voyage):
    return http_index


def test_cli_varsayilan_vector(cli_env, capsys):
    code = cli(load_script(), cli_env)

    assert code == 0
    assert printed_order(capsys.readouterr().out) == VECTOR_ORDER


def test_cli_method_vector(cli_env, capsys):
    code = cli(load_script(), cli_env, "--method", "vector")

    assert code == 0
    assert printed_order(capsys.readouterr().out) == VECTOR_ORDER


def test_cli_method_bm25_gomme_istemez(cli_env, voyage, capsys):
    code = cli(load_script(), cli_env, "--method", "bm25")

    out = capsys.readouterr().out
    assert code == 0
    assert printed_order(out) == BM25_ORDER
    assert voyage.calls == []


def test_cli_bm25_yapilandirma_olmadan_calisir(http_index, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_EMBED_MODEL", raising=False)

    def no_client(key):
        raise AssertionError("bm25 Voyage istemcisi kurmamalı")

    monkeypatch.setattr(embed, "_make_client", no_client)

    code = cli(load_script(), http_index, "--method", "bm25")

    assert code == 0
    assert printed_order(capsys.readouterr().out) == BM25_ORDER


def test_http_bm25_yapilandirma_olmadan_200(http_index, monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_EMBED_MODEL", raising=False)

    response = get(TestClient(app), q="pist", k=6, method="bm25")

    assert response.status_code == 200
    assert http_ids(response) == BM25_ORDER


def test_cli_method_hybrid(cli_env, voyage, capsys):
    code = cli(load_script(), cli_env, "--method", "hybrid")

    out = capsys.readouterr().out
    assert code == 0
    assert printed_order(out) == HYBRID_ORDER
    assert f"{HYBRID_SCORES['D03#01']:.4f}" in out
    assert len(voyage.calls) == 1


def test_cli_gecersiz_method_kullanim_hatasi(cli_env, capsys):
    with pytest.raises(SystemExit) as info:
        cli(load_script(), cli_env, "--method", "bilinmeyen")

    assert info.value.code == 2
    # Bayrak tanınmıyorsa da kod 2 olur; "invalid choice" bayrağın var olduğunu kanıtlar.
    assert "invalid choice" in capsys.readouterr().err


def test_cli_hybrid_gomme_hatasinda_hata_ve_1_sir_yazmaz(
    cli_env, voyage, capsys
):
    voyage.fail = RuntimeError(f"sır: {SECRET}")

    code = cli(load_script(), cli_env, "--method", "hybrid")

    captured = capsys.readouterr()
    assert code == 1
    assert "Hata:" in captured.err
    assert SECRET not in captured.out + captured.err
