"""Kaynak önceliği sözleşmesi (docs/hibrit.md › Kaynak önceliği).

Ağa çıkmaz, `.env` gerektirmez; Voyage sahte istemcidir. Testler koddan önce
yazıldı: `priority` argümanı yokken kırmızıdır.

Test için sabitlenen adlar (docs'ta açık değil):
- `search(..., priority=False)`; yalnızca `method="hybrid"` ile `True` olabilir.
- `GET /rag/search?priority=true`; `hybrid` gövdesinde `priority` alanı bulunur.
- `scripts/rag_ara.py --priority` (yalnızca `--method hybrid` ile).
- `type` → düzey eşlemesinde olmayan tür çarpan almaz (1.00).

Veri kümesi (sorgu "pist", sorgu vektörü [1, 0, 0]; 3 parça): vektör ve bm25
sırası aynı: D09#01, D01#01, D07#01. Birleşik skorlar 2/61 > 2/62 > 2/63;
çarpanlarla (0.88, 0.94, 0.97) sıra tamamen tersine döner.
"""

import importlib.util
import json
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

# docs/hibrit.md tablosu: düzey → belgeler; korpusun metadata'sındaki `type` ile.
LEVEL_BY_TYPE = {
    "aerodrome_restrictions": 2,  # D07
    "aerodrome_manual": 3,  # D01, D02, D03
    "sop": 4,  # D04, D05, D06
    "local_instruction": 4,  # D08
    "temporary_note": 4,  # D10
    "sla_annex": 4,  # D11
    "agreement_summary": 4,  # D12
    "training_material": 5,  # D09
    "operational_memory": 5,  # D13, D14
    "facility_rules": 5,  # D15
}


def multiplier(level: int) -> float:
    return 1.00 - 0.03 * (level - 1)


# (chunk_id, doc_id, status, language, type, text, vektör)
ROWS = [
    ("D09#01", "D09", "active", "tr", "training_material", "pist pist pist", [1.0, 0.0, 0.0]),
    ("D01#01", "D01", "active", "tr", "aerodrome_manual", "pist pist", [0.8, 0.6, 0.0]),
    ("D07#01", "D07", "active", "tr", "aerodrome_restrictions", "pist", [0.6, 0.8, 0.0]),
]  # fmt: skip
PLAIN_ORDER = ["D09#01", "D01#01", "D07#01"]
PRIORITY_ORDER = ["D07#01", "D01#01", "D09#01"]
BASE_SCORES = {"D09#01": 2 / 61, "D01#01": 2 / 62, "D07#01": 2 / 63}
PRIORITY_SCORES = {
    "D09#01": 2 / 61 * 0.88,
    "D01#01": 2 / 62 * 0.94,
    "D07#01": 2 / 63 * 0.97,
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


def write_index(directory: Path, rows) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [make_chunk(*row[:6]) for row in rows]
    vectors = np.asarray([row[6] for row in rows], dtype=np.float32)
    (directory / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    np.save(directory / "vektorler.npy", vectors, allow_pickle=False)
    meta = {
        "model": MODEL,
        "dimension": int(vectors.shape[1]),
        "chunk_count": len(chunks),
        "corpus_sha256": "0" * 64,
    }
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


class FakeClient:
    """Her sorguyu [1, 0, 0] vektörüne çevirir; çağrıları kaydeder, istenirse düşer."""

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
def index_dir(tmp_path):
    directory = tmp_path / "data" / "indeks"
    write_index(directory, list(reversed(ROWS)))
    return directory


@pytest.fixture
def client():
    return FakeClient()


def run(index_dir, client, query="pist", **kwargs):
    kwargs.setdefault("model", MODEL)
    kwargs.setdefault("k", 3)
    return search.search(query, index_dir=index_dir, client=client, **kwargs)


def ids(results) -> list[str]:
    return [r["chunk_id"] for r in results]


def scores(results) -> dict[str, float]:
    return {r["chunk_id"]: r["score"] for r in results}


# ───────── Kapalıyken hiçbir şey değişmez ─────────


def test_priority_varsayilan_kapali(index_dir, client):
    default = run(index_dir, client, method="hybrid")
    explicit = run(index_dir, client, method="hybrid", priority=False)

    assert ids(default) == PLAIN_ORDER
    assert default == explicit
    assert scores(default) == pytest.approx(BASE_SCORES, abs=1e-12)


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_priority_false_diger_yontemleri_degistirmez(index_dir, client, method):
    default = run(index_dir, client, method=method)
    explicit = run(index_dir, client, method=method, priority=False)

    assert default == explicit


# ───────── Açıkken: skor × çarpan, yeniden sıralama ─────────


def test_priority_skoru_carpanla_carpar_ve_yeniden_siralar(index_dir, client):
    results = run(index_dir, client, method="hybrid", priority=True)

    assert ids(results) == PRIORITY_ORDER
    assert scores(results) == pytest.approx(PRIORITY_SCORES, abs=1e-12)


def test_priority_sonuc_skor_azalan_sirada(index_dir, client):
    values = [r["score"] for r in run(index_dir, client, method="hybrid", priority=True)]

    assert len(values) == 3
    assert values == sorted(values, reverse=True)


def test_priority_sonuc_alanlari_ayni(index_dir, client):
    plain = run(index_dir, client, method="hybrid")
    boosted = run(index_dir, client, method="hybrid", priority=True)

    assert plain and boosted
    assert {frozenset(r) for r in plain} == {frozenset(r) for r in boosted}
    for result in boosted:
        assert type(result["score"]) is float
        assert result["text"] == next(
            row[5] for row in ROWS if row[0] == result["chunk_id"]
        )


def test_priority_k_yeniden_siralamadan_sonra_uygulanir(index_dir, client):
    plain = run(index_dir, client, method="hybrid", k=1)
    boosted = run(index_dir, client, method="hybrid", k=1, priority=True)

    assert ids(plain) == ["D09#01"]
    assert ids(boosted) == ["D07#01"]


def test_priority_cokcalistirmada_ayni_sonuc(index_dir, client):
    first = run(index_dir, client, method="hybrid", priority=True)
    second = run(index_dir, client, method="hybrid", priority=True)

    assert first == second


def test_priority_aday_ve_rrf_ayarlariyla_birlikte_calisir(index_dir, client):
    # 1 aday: vektör ve bm25 listesinde yalnızca D09#01 → 2/61, sonra çarpan.
    results = run(index_dir, client, method="hybrid", priority=True, rrf_candidates=1)

    assert ids(results) == ["D09#01"]
    assert results[0]["score"] == pytest.approx(2 / 61 * 0.88, abs=1e-12)

    # rrf_k=0: skor Σ 1/sıra; çarpan bunun üstüne biner.
    results = run(index_dir, client, method="hybrid", priority=True, rrf_k=0)
    assert scores(results) == pytest.approx(
        {"D09#01": 2 * 0.88, "D01#01": 1 * 0.94, "D07#01": 2 / 3 * 0.97}, abs=1e-12
    )
    assert ids(results) == ["D09#01", "D01#01", "D07#01"]


def test_priority_bm25_eslesmesi_yoksa_vektor_skoru_carpilir(index_dir, client):
    results = run(index_dir, client, query="yagmur", method="hybrid", priority=True)

    # Yalnızca vektör terimi: 1/61, 1/62, 1/63; çarpanlarla sıra yine tersine döner.
    assert scores(results) == pytest.approx(
        {"D09#01": 0.88 / 61, "D01#01": 0.94 / 62, "D07#01": 0.97 / 63}, abs=1e-12
    )
    assert ids(results) == ["D07#01", "D01#01", "D09#01"]


def test_priority_esit_skorda_vektor_sirasi_once_gelir(tmp_path):
    # Aynı tür (aynı çarpan), 1 aday: P yalnızca vektörde, Q yalnızca bm25'te → 1/61
    # eşit. Çarpandan sonra da eşit: vektör sırasındaki P, chunk_id'si küçük Q'dan önce.
    rows = [
        ("D05#02", "D05", "active", "tr", "sop", "kapat", [1.0, 0.0, 0.0]),
        ("D05#01", "D05", "active", "tr", "sop", "pist", [0.0, 1.0, 0.0]),
    ]
    write_index(tmp_path / "ind", rows)

    results = run(
        tmp_path / "ind",
        FakeClient(),
        method="hybrid",
        priority=True,
        rrf_candidates=1,
    )

    assert ids(results) == ["D05#02", "D05#01"]
    assert [r["score"] for r in results] == pytest.approx([0.91 / 61] * 2, abs=1e-12)
    assert results[0]["score"] == results[1]["score"]


# ───────── type → düzey eşlemesi ─────────


def single_chunk_index(tmp_path, type_: str) -> Path:
    directory = tmp_path / f"tek-{type_}"
    write_index(
        directory,
        [("D99#01", "D99", "active", "tr", type_, "pist", [1.0, 0.0, 0.0])],
    )
    return directory


@pytest.mark.parametrize(("type_", "level"), sorted(LEVEL_BY_TYPE.items()))
def test_type_duzey_ve_carpan_eslemesi(tmp_path, client, type_, level):
    directory = single_chunk_index(tmp_path, type_)

    results = run(directory, client, method="hybrid", priority=True)

    assert ids(results) == ["D99#01"]
    assert results[0]["score"] == pytest.approx(2 / 61 * multiplier(level), abs=1e-12)


def test_duzey_listesinde_olmayan_type_carpan_almaz(tmp_path, client):
    directory = single_chunk_index(tmp_path, "baska_bir_tur")

    results = run(directory, client, method="hybrid", priority=True)

    assert results[0]["score"] == pytest.approx(2 / 61, abs=1e-12)


def test_ayni_turdeki_belgeler_ayni_carpani_alir(tmp_path, client):
    rows = [
        ("D04#01", "D04", "active", "tr", "sop", "pist", [1.0, 0.0, 0.0]),
        ("D05#01", "D05", "active", "tr", "sop", "pist", [1.0, 0.0, 0.0]),
        ("D06#01", "D06", "active", "tr", "sop", "pist", [1.0, 0.0, 0.0]),
    ]
    write_index(tmp_path / "ind", rows)

    results = run(tmp_path / "ind", client, method="hybrid", priority=True)

    # Üç parça da aynı vektör ve metne sahip: sıra chunk_id'ye göre 1, 2, 3.
    assert ids(results) == ["D04#01", "D05#01", "D06#01"]
    assert [r["score"] for r in results] == pytest.approx(
        [2 / 61 * 0.91, 2 / 62 * 0.91, 2 / 63 * 0.91], abs=1e-12
    )


# ───────── Çarpan filtre değildir ─────────


def test_dusuk_oncelikli_belge_yine_gorunur(index_dir, client):
    results = run(index_dir, client, method="hybrid", priority=True)

    assert "D09#01" in ids(results)


def test_yalniz_dusuk_oncelikli_belge_cevap_veriyorsa_o_doner(index_dir, client):
    # "pist"i yalnızca D09 içeriyor sayılsın diye doc_id süzülür.
    results = run(index_dir, client, method="hybrid", priority=True, doc_id="D09")

    assert ids(results) == ["D09#01"]
    assert results[0]["score"] == pytest.approx(2 / 61 * 0.88, abs=1e-12)


@pytest.mark.parametrize(
    ("filters", "allowed"),
    [
        ({"status": "active"}, {"D09#01", "D01#01", "D07#01"}),
        ({"language": "en"}, set()),
        ({"type": "aerodrome_manual"}, {"D01#01"}),
        ({"doc_id": "D07"}, {"D07#01"}),
    ],
)
def test_dort_filtre_oncelikle_birlikte_calisir(index_dir, client, filters, allowed):
    results = run(index_dir, client, method="hybrid", priority=True, **filters)

    assert set(ids(results)) == allowed


# ───────── Yalnızca hybrid ─────────


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_priority_true_vector_ve_bm25te_value_error(index_dir, client, method):
    with pytest.raises(ValueError) as info:
        run(index_dir, client, method=method, priority=True)

    assert "hybrid" in str(info.value)
    assert "priority" in str(info.value)
    assert client.calls == []


def test_priority_true_varsayilan_yontemde_de_value_error(index_dir, client):
    with pytest.raises(ValueError):
        run(index_dir, client, priority=True)

    assert client.calls == []


def test_priority_hibritte_soruyu_bir_kez_gomer(index_dir, client):
    run(index_dir, client, method="hybrid", priority=True)

    assert len(client.calls) == 1
    assert client.calls[0]["input_type"] == "query"


def test_priority_indeksi_degistirmez(index_dir, client):
    before = {p.name: p.read_bytes() for p in index_dir.iterdir()}

    run(index_dir, client, method="hybrid", priority=True)

    assert {p.name: p.read_bytes() for p in index_dir.iterdir()} == before


def test_priority_hibritin_model_kontrolunu_korur(index_dir, client):
    with pytest.raises(search.IndexModelMismatchError):
        run(index_dir, client, model="baska-model", method="hybrid", priority=True)

    assert client.calls == []


# ───────── HTTP: GET /rag/search?priority= ─────────


@pytest.fixture
def http_index(tmp_path, monkeypatch):
    directory = tmp_path / "data" / "indeks"
    write_index(directory, ROWS)
    monkeypatch.setattr(search, "INDEX_DIR", directory)
    return directory


@pytest.fixture
def voyage(monkeypatch, tmp_path):
    fake = FakeClient()
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


def test_http_hybrid_priority_true(http):
    response = get(http, q="pist", k=3, method="hybrid", priority="true")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["query", "k", "method", "priority", "filters", "results"]
    assert body["method"] == "hybrid"
    assert body["priority"] is True
    assert http_ids(response) == PRIORITY_ORDER
    assert [r["score"] for r in body["results"]] == pytest.approx(
        [PRIORITY_SCORES[cid] for cid in PRIORITY_ORDER], abs=1e-12
    )


@pytest.mark.parametrize("params", [{}, {"priority": "false"}])
def test_http_hybrid_priority_kapali_siralama_degismez(http, params):
    response = get(http, q="pist", k=3, method="hybrid", **params)

    assert response.status_code == 200
    body = response.json()
    assert body["priority"] is False
    assert http_ids(response) == PLAIN_ORDER
    assert [r["score"] for r in body["results"]] == pytest.approx(
        [BASE_SCORES[cid] for cid in PLAIN_ORDER], abs=1e-12
    )


def test_http_hybrid_priority_filtre_ve_k(http):
    response = get(
        http, q="pist", k=1, method="hybrid", priority="true", status="active"
    )

    assert response.status_code == 200
    assert http_ids(response) == ["D07#01"]
    assert response.json()["filters"] == {"status": "active"}


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_http_priority_true_hybrid_disinda_422(http, voyage, method):
    response = get(http, q="pist", method=method, priority="true")

    assert response.status_code == 422
    assert voyage.calls == []


def test_http_priority_true_varsayilan_yontemde_422(http, voyage):
    response = get(http, q="pist", priority="true")

    assert response.status_code == 422
    assert voyage.calls == []


@pytest.mark.parametrize("method", ["vector", "bm25"])
def test_http_priority_false_hybrid_disinda_kabul_edilir(http, method):
    response = get(http, q="pist", method=method, priority="false")

    assert response.status_code == 200
    assert "priority" not in response.json()


def test_http_gecersiz_priority_degeri_422(http, voyage):
    response = get(http, q="pist", method="hybrid", priority="belki")

    assert response.status_code == 422
    assert voyage.calls == []


def test_http_vector_ve_bm25_govdesi_priority_icermez(http):
    assert "priority" not in get(http, q="pist").json()
    assert "priority" not in get(http, q="pist", method="bm25").json()


def test_http_hybrid_priority_model_farkliysa_503(http, voyage, monkeypatch):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    response = get(http, q="pist", method="hybrid", priority="true")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INDEX_MODEL_MISMATCH"
    assert voyage.calls == []


# ───────── scripts/rag_ara.py --priority ─────────


def load_script():
    assert SCRIPT.exists(), "scripts/rag_ara.py yok"
    spec = importlib.util.spec_from_file_location("rag_ara_oncelik", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cli(module, directory, *args):
    return module.main(["pist", "--indeks", str(directory), "-k", "3", *args])


def printed_order(out: str) -> list[str]:
    found = [(out.index(cid), cid) for cid in PLAIN_ORDER if cid in out]
    return [cid for _, cid in sorted(found)]


def test_cli_hybrid_priority(http_index, voyage, capsys):
    code = cli(load_script(), http_index, "--method", "hybrid", "--priority")

    out = capsys.readouterr().out
    assert code == 0
    assert printed_order(out) == PRIORITY_ORDER
    assert f"{PRIORITY_SCORES['D07#01']:.4f}" in out
    assert len(voyage.calls) == 1


def test_cli_hybrid_priority_olmadan_siralama_degismez(http_index, voyage, capsys):
    code = cli(load_script(), http_index, "--method", "hybrid")

    assert code == 0
    assert printed_order(capsys.readouterr().out) == PLAIN_ORDER


@pytest.mark.parametrize("method_args", [[], ["--method", "vector"], ["--method", "bm25"]])
def test_cli_priority_hybrid_disinda_hata_ve_1(http_index, voyage, capsys, method_args):
    code = cli(load_script(), http_index, *method_args, "--priority")

    captured = capsys.readouterr()
    assert code == 1
    assert "Hata:" in captured.err
    assert "hybrid" in captured.err
    assert captured.out == ""
    assert voyage.calls == []
