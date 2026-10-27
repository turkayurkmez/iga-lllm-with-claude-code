"""Arama sözleşmesi (docs/rag.md §6). Ağa çıkmaz, `.env` gerektirmez.

Gömme sahte Voyage istemcisiyle, indeks tmp klasöründe elle kurulmuş vektörlerle
çalışır; böylece skorlar önceden hesaplanabilir. Testler koddan önce yazıldı:
`backend/rag/search.py` yokken kırmızıdır.

Sözleşmenin test için sabitlenen adları (docs'ta açık değil):
- `search(query, k=5, status=None, language=None, type=None, doc_id=None,
  index_dir=INDEX_DIR, client=None, model=None) -> list[dict]`
- `IndexNotReadyError` (`code == "INDEX_NOT_READY"`) ve
  `IndexModelMismatchError` (`code == "INDEX_MODEL_MISMATCH"`), §7'deki kodlarla aynı.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.rag import embed
from backend.rag.index import build_index

MODEL = "sahte-gomme-modeli"
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
STAMP = "**KURGUSAL — EĞİTİM AMAÇLI**"


def unit(*components: float) -> list[float]:
    return [float(c) for c in components]


# (chunk_id, doc_id, revision, status, language, type, vektör).
# Sorgu [1, 0, 0]: skor = ilk bileşen. İndekse bilerek ters sırada yazılır.
CHUNKS = [
    ("D01#01", "D01", "2", "active", "tr", "manual", unit(1.0, 0.0, 0.0)),
    ("D01#02", "D01", "2", "active", "tr", "manual", unit(0.8, 0.6, 0.0)),
    ("D02#01", "D02", "1", "superseded", "tr", "procedure", unit(0.6, 0.8, 0.0)),
    ("D02#02", "D02", "1", "superseded", "tr", "procedure", unit(0.0, 1.0, 0.0)),
    ("D03#01", "D03", "3", "active", "en", "manual", unit(0.28, 0.96, 0.0)),
    ("D03#02", "D03", "3", "active", "en", "manual", unit(-1.0, 0.0, 0.0)),
]
EXPECTED_ORDER = ["D01#01", "D01#02", "D02#01", "D03#01", "D02#02", "D03#02"]
EXPECTED_SCORES = {
    "D01#01": 1.0,
    "D01#02": 0.8,
    "D02#01": 0.6,
    "D02#02": 0.0,
    "D03#01": 0.28,
    "D03#02": -1.0,
}


def make_chunk(chunk_id, doc_id, revision, status, language, type_) -> dict:
    return {
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
        "text": f"{chunk_id} gövde metni.",
        "context": f"[{doc_id} · Belge {doc_id} · Bölüm {chunk_id}]",
    }


def write_index(directory: Path, rows, model: str = MODEL) -> None:
    """§5 dosyalarını doğrudan yazar (indeks kurucuya bağımlı olmadan)."""
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [make_chunk(*row[:6]) for row in rows]
    vectors = np.asarray([row[6] for row in rows], dtype=np.float32)
    (directory / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    np.save(directory / "vektorler.npy", vectors, allow_pickle=False)
    meta = {
        "model": model,
        "dimension": int(vectors.shape[1]),
        "chunk_count": len(chunks),
        "corpus_sha256": "0" * 64,
    }
    (directory / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


class FakeClient:
    """Sorgu metnini önceden verilen vektöre çevirir ve çağrıları kaydeder."""

    def __init__(self, vectors: dict[str, list[float]] | None = None):
        self.vectors = vectors if vectors is not None else {}
        self.calls = []

    def embed(self, texts, model, input_type):
        self.calls.append(
            {"texts": list(texts), "model": model, "input_type": input_type}
        )
        return SimpleNamespace(
            embeddings=[self.vectors[t] for t in texts], total_tokens=len(texts)
        )


def load_search():
    assert importlib.util.find_spec("backend.rag.search") is not None, (
        "backend/rag/search.py yok"
    )
    from backend.rag import search

    return search


@pytest.fixture
def index_dir(tmp_path):
    directory = tmp_path / "data" / "indeks"
    write_index(directory, list(reversed(CHUNKS)))
    return directory


@pytest.fixture
def client():
    return FakeClient({"pist": unit(1.0, 0.0, 0.0)})


@pytest.fixture
def no_env_file(monkeypatch, tmp_path):
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_EMBED_MODEL", raising=False)


def run(index_dir, client, query="pist", **kwargs):
    search = load_search()
    kwargs.setdefault("model", MODEL)
    return search.search(query, index_dir=index_dir, client=client, **kwargs)


def ids(results) -> list[str]:
    return [r["chunk_id"] for r in results]


# ───────── Sonuç biçimi ─────────


def test_modul_var():
    assert importlib.util.find_spec("backend.rag.search") is not None


def test_sonuc_alanlari(index_dir, client):
    results = run(index_dir, client, k=6)

    assert len(results) == 6
    for result in results:
        for field in RESULT_FIELDS:
            assert field in result, field


def test_sonuc_alan_degerleri_parcadan_gelir(index_dir, client):
    top = run(index_dir, client, k=1)[0]

    assert top["chunk_id"] == "D01#01"
    assert top["doc_id"] == "D01"
    assert top["revision"] == "2"
    assert top["status"] == "active"
    assert top["language"] == "tr"
    assert top["section"] == "Bölüm D01#01"
    assert top["text"] == "D01#01 gövde metni."


def test_text_context_icermez(index_dir, client):
    # §3 madde 8: arama sonucunda `text` ve `context` ayrı gösterilir.
    for result in run(index_dir, client, k=6):
        assert result["text"] == f"{result['chunk_id']} gövde metni."
        assert "[" not in result["text"]


def test_skor_duz_python_float(index_dir, client):
    for result in run(index_dir, client, k=6):
        assert type(result["score"]) is float


# ───────── Sıralama ve skor ─────────


def test_skor_ic_carpimdir(index_dir, client):
    results = run(index_dir, client, k=6)

    for result in results:
        assert result["score"] == pytest.approx(
            EXPECTED_SCORES[result["chunk_id"]], abs=1e-6
        )


def test_skora_gore_azalan_sira_indeks_sirasindan_bagimsiz(index_dir, client):
    assert ids(run(index_dir, client, k=6)) == EXPECTED_ORDER


def test_birim_olmayan_sorgu_vektoru_normallestirilir(index_dir):
    client = FakeClient({"pist": unit(3.0, 0.0, 0.0)})

    results = run(index_dir, client, k=2)

    assert [r["score"] for r in results] == pytest.approx([1.0, 0.8], abs=1e-6)


def test_esit_skorda_chunk_id_artan(tmp_path):
    directory = tmp_path / "indeks"
    same = unit(0.6, 0.8, 0.0)
    rows = [
        ("D05#01", "D05", "1", "active", "tr", "manual", same),
        ("D01#02", "D01", "1", "active", "tr", "manual", same),
        ("D03#01", "D03", "1", "active", "tr", "manual", same),
        ("D01#01", "D01", "1", "active", "tr", "manual", same),
        ("D02#01", "D02", "1", "active", "tr", "manual", unit(1.0, 0.0, 0.0)),
    ]
    write_index(directory, rows)
    client = FakeClient({"pist": unit(1.0, 0.0, 0.0)})

    results = run(directory, client, k=5)

    # D02#01 daha yüksek skorlu; kalan dördü eşit ve chunk_id artan sırada.
    assert ids(results) == ["D02#01", "D01#01", "D01#02", "D03#01", "D05#01"]


def test_esit_skorda_k_siniri_chunk_id_a_gore_keser(tmp_path):
    directory = tmp_path / "indeks"
    same = unit(1.0, 0.0, 0.0)
    rows = [
        ("D03#01", "D03", "1", "active", "tr", "manual", same),
        ("D01#01", "D01", "1", "active", "tr", "manual", same),
        ("D02#01", "D02", "1", "active", "tr", "manual", same),
    ]
    write_index(directory, rows)

    results = run(directory, FakeClient({"pist": same}), k=2)

    assert ids(results) == ["D01#01", "D02#01"]


def test_skor_esigi_yok_negatif_skor_da_doner(index_dir, client):
    results = run(index_dir, client, k=6)

    assert results[-1]["chunk_id"] == "D03#02"
    assert results[-1]["score"] < 0


def test_ayni_soru_ayni_sonuc(index_dir, client):
    assert run(index_dir, client, k=6) == run(index_dir, client, k=6)


# ───────── k ─────────


def test_varsayilan_k_bes(index_dir, client):
    search = load_search()

    results = search.search("pist", index_dir=index_dir, client=client, model=MODEL)

    assert len(results) == 5
    assert ids(results) == EXPECTED_ORDER[:5]


@pytest.mark.parametrize("k", [1, 2, 3])
def test_k_kadar_sonuc(index_dir, client, k):
    assert ids(run(index_dir, client, k=k)) == EXPECTED_ORDER[:k]


def test_k_parca_sayisindan_buyukse_hepsi_doner(index_dir, client):
    assert len(run(index_dir, client, k=20)) == 6


# ───────── Filtreler ─────────


def test_filtre_yoksa_hepsi_aday(index_dir, client):
    assert ids(run(index_dir, client, k=6)) == EXPECTED_ORDER


def test_status_filtresi(index_dir, client):
    results = run(index_dir, client, k=6, status="superseded")

    assert ids(results) == ["D02#01", "D02#02"]
    assert {r["status"] for r in results} == {"superseded"}


def test_language_filtresi(index_dir, client):
    results = run(index_dir, client, k=6, language="en")

    assert ids(results) == ["D03#01", "D03#02"]


def test_type_filtresi(index_dir, client):
    results = run(index_dir, client, k=6, type="procedure")

    assert ids(results) == ["D02#01", "D02#02"]


def test_doc_id_filtresi(index_dir, client):
    results = run(index_dir, client, k=6, doc_id="D01")

    assert ids(results) == ["D01#01", "D01#02"]


def test_filtreler_birlikte_ve_ile_birlesir(index_dir, client):
    results = run(index_dir, client, k=6, status="active", language="tr")

    assert ids(results) == ["D01#01", "D01#02"]


def test_celisen_filtreler_bos_liste(index_dir, client):
    assert run(index_dir, client, k=6, doc_id="D02", status="active") == []


def test_filtre_benzerlikten_once_uygulanir(index_dir, client):
    # `en` parçaları genel sıralamada 4. ve 6.; son-süzme yapılsaydı k=2'de
    # ilk ikiye (D01) bakılır ve sonuç boş kalırdı.
    results = run(index_dir, client, k=2, language="en")

    assert ids(results) == ["D03#01", "D03#02"]


def test_filtre_sonrasi_k_siniri(index_dir, client):
    results = run(index_dir, client, k=1, status="superseded")

    assert ids(results) == ["D02#01"]


@pytest.mark.parametrize(
    "filters",
    [
        {"status": "yok-boyle-durum"},
        {"language": "de"},
        {"type": "yok-boyle-tur"},
        {"doc_id": "D99"},
    ],
)
def test_filtre_hicbir_parca_birakmazsa_bos_liste_hata_degil(
    index_dir, client, filters
):
    assert run(index_dir, client, k=5, **filters) == []


def test_bos_sonucta_da_soru_gomulur_ya_da_en_azindan_hata_yok(index_dir, client):
    # Boş liste hata değildir; istisna fırlatmaz (gömme çağrısının yapılıp
    # yapılmadığı sözleşmede yok, bu yüzden yalnızca dönüş denetlenir).
    assert run(index_dir, client, doc_id="D99") == []


# ───────── Soru gömme ─────────


def test_soru_query_input_type_ile_ve_indeks_modeliyle_gomulur(index_dir, client):
    run(index_dir, client)

    assert len(client.calls) == 1
    assert client.calls[0]["input_type"] == "query"
    assert client.calls[0]["model"] == MODEL
    assert client.calls[0]["texts"] == ["pist"]


def test_bos_soru_reddedilir_ve_gomulmez(index_dir, client):
    with pytest.raises(ValueError):
        run(index_dir, client, query="   ")

    assert client.calls == []


# ───────── İndeks yok / model uyuşmazlığı ─────────


def test_indeks_klasoru_yoksa_index_not_ready(tmp_path, client):
    search = load_search()

    with pytest.raises(search.IndexNotReadyError) as info:
        run(tmp_path / "yok", client)

    assert info.value.code == "INDEX_NOT_READY"
    assert client.calls == []


@pytest.mark.parametrize("missing", ["chunks.json", "vektorler.npy", "meta.json"])
def test_indeks_dosyalarindan_biri_eksikse_index_not_ready(index_dir, client, missing):
    search = load_search()
    (index_dir / missing).unlink()

    with pytest.raises(search.IndexNotReadyError):
        run(index_dir, client)

    assert client.calls == []


def test_bos_indeks_klasoru_index_not_ready(tmp_path, client):
    search = load_search()
    directory = tmp_path / "indeks"
    directory.mkdir()

    with pytest.raises(search.IndexNotReadyError):
        run(directory, client)


def test_model_farkliysa_reddedilir_ve_gomme_cagrilmaz(index_dir, client):
    search = load_search()

    with pytest.raises(search.IndexModelMismatchError) as info:
        run(index_dir, client, model="baska-model")

    assert info.value.code == "INDEX_MODEL_MISMATCH"
    assert client.calls == []


def test_model_env_den_okunur_ve_uyusursa_arama_calisir(
    index_dir, client, monkeypatch, no_env_file
):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", MODEL)
    search = load_search()

    results = search.search("pist", k=1, index_dir=index_dir, client=client)

    assert ids(results) == ["D01#01"]
    assert client.calls[0]["model"] == MODEL


def test_env_modeli_indeksinkinden_farkliysa_reddedilir(
    index_dir, client, monkeypatch, no_env_file
):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")
    search = load_search()

    with pytest.raises(search.IndexModelMismatchError):
        search.search("pist", index_dir=index_dir, client=client)

    assert client.calls == []


def test_hata_mesajlari_turkce_ve_modelleri_icerir(index_dir, client):
    search = load_search()

    with pytest.raises(search.IndexModelMismatchError) as info:
        run(index_dir, client, model="baska-model")

    message = str(info.value)
    assert MODEL in message
    assert "baska-model" in message


# ───────── Yan etkisizlik ─────────


def test_arama_indeks_dosyalarini_degistirmez(index_dir, client):
    before = {p.name: p.read_bytes() for p in index_dir.iterdir()}

    run(index_dir, client, k=6)
    run(index_dir, client, k=2, status="active")

    assert {p.name: p.read_bytes() for p in index_dir.iterdir()} == before
    assert sorted(p.name for p in index_dir.iterdir()) == sorted(before)


def test_arama_gercek_data_klasorune_dokunmaz(index_dir, client):
    repo_index = Path(__file__).resolve().parent.parent / "data" / "indeks"
    existed = repo_index.exists()

    run(index_dir, client)

    assert repo_index.exists() == existed


# ───────── İndeks kurucu çıktısıyla uçtan uca ─────────

DOC = """---
doc_id: {doc_id}
title: Belge {doc_id}
type: manual
authority: Kurgusal Makam
airport: XXXX
language: tr
revision: 1
effective_from: 2025-03-01
status: active
---
{stamp}

# Belge {doc_id}

## Giriş

{doc_id} giriş metni.

## Kurallar

{doc_id} için kurallar burada.

{stamp}
"""


class KeywordClient:
    """Metinde `kurallar` geçiyorsa [1, 0], geçmiyorsa [0, 1] üretir."""

    def embed(self, texts, model, input_type):
        vectors = [[1.0, 0.0] if "kurallar" in t.lower() else [0.0, 1.0] for t in texts]
        return SimpleNamespace(embeddings=vectors, total_tokens=len(texts))


def test_build_index_ciktisini_arar(tmp_path):
    corpus = tmp_path / "korpus"
    corpus.mkdir()
    for doc_id in ("D01", "D02"):
        text = DOC.format(doc_id=doc_id, stamp=STAMP)
        (corpus / f"{doc_id}.md").write_bytes(text.encode("utf-8"))
    directory = tmp_path / "data" / "indeks"
    build_index(corpus, directory, client=KeywordClient(), model=MODEL)
    search = load_search()

    results = search.search(
        "kurallar", k=2, index_dir=directory, client=KeywordClient(), model=MODEL
    )

    assert [r["doc_id"] for r in results] == ["D01", "D02"]
    assert [r["section"] for r in results] == ["Kurallar", "Kurallar"]
    assert [r["score"] for r in results] == pytest.approx([1.0, 1.0], abs=1e-6)
    assert all("kurallar" in r["text"] for r in results)
