"""search_documents sözleşmesi (docs/kaynakli.md › Tool).

Ağa çıkmaz, `.env` gerektirmez; Voyage sahte istemcidir, indeks tmp'de kurulur.
Testler koddan önce yazıldı: tool, kontrat ve `search()`'ün yeni alanları yokken
kırmızıdır. Yalnızca `run_tool`, `tool_definitions` ve `search` kullanılır.

Test için sabitlenen adlar (docs'ta açık değil):
- Tool `hybrid` arar, `priority` kapalı; `vector_score` `search()` sonuçlarındadır
  (`vector` ve `hybrid`; `bm25`'te yok), `search.rag_threshold()` eşiği okur,
  `search.load_chunks()` indeksteki parçaları verir.
- Eşiğe eşit en yüksek `vector_score` geçer ("altındaysa" NOT_FOUND).
- Katman hatasında (indeks, model, gömme, eşik ayarı) `filters` doğrulanmış
  argümanlardır (varsayılanlar dahil), `source` `null`.

Veri kümesi (sorgu "dusuk gorus", sorgu vektörü [1, 0, 0]): vektör sırası
D03, D02 (eski sürüm), D04, D09, D15, D99; bm25 yalnızca D03 ve D02'de eşleşir.
Yalnız aktif aramada RRF sırası D03, D04, D09, D15, D99; eski sürümlü aramada
D03 ile D02 tam eşit (vektör sırası önce).
"""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from backend.rag import embed, search
from backend.tools import run_tool, tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "backend" / "tools" / "contracts" / "search_documents.json"
NAME = "search_documents"
MODEL = "sahte-gomme-modeli"
SECRET = "gizli-anahtar-xyz"
NOW = "2026-10-20T16:22:00+03:00"
SOURCE = "data/korpus"
VERSION = "1.0.0"
QUERY = "dusuk gorus"

NOT_FOUND = {
    "code": "NOT_FOUND",
    "message": "Belgelerde bu konuda kaynak bulunamadı.",
}
ARGS_INVALID = {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Tool argümanları şemaya uymuyor.",
}
DATA_INVALID = {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Tool çıktısı şemaya uymuyor; yanıt üretilemedi.",
}
FORBIDDEN_KEYWORDS = {"minLength", "maxLength", "minimum", "maximum", "multipleOf"}
ITEM_FIELDS = {
    "chunk_id",
    "doc_id",
    "title",
    "section",
    "revision",
    "effective_from",
    "status",
    "authority",
    "priority_level",
    "language",
    "text",
}

# (chunk_id, status, type, revision, effective_from, supersedes, text, vektör)
ROWS = [
    ("D03#01", "active", "aerodrome_manual", "2", "2026-03-01", "D02", "dusuk gorus yeni", [1.0, 0.0, 0.0]),
    ("D02#01", "superseded", "aerodrome_manual", "1", "2024-11-01", None, "dusuk gorus eski", [0.8, 0.6, 0.0]),
    ("D04#01", "active", "sop", "1", "2025-01-01", None, "holdover", [0.6, 0.8, 0.0]),
    ("D09#01", "active", "training_material", "1", "2025-02-01", None, "egitim", [0.28, 0.96, 0.0]),
    ("D15#01", "active", "facility_rules", "1", "2025-02-01", None, "otopark", [0.0, 1.0, 0.0]),
    ("D99#01", "active", "yeni_tur", "1", "2025-02-01", None, "bilinmeyen", [-1.0, 0.0, 0.0]),
]  # fmt: skip
ACTIVE_ORDER = ["D03#01", "D04#01", "D09#01", "D15#01", "D99#01"]
ALL_ORDER = ["D03#01", "D02#01", "D04#01", "D09#01", "D15#01", "D99#01"]
LEVELS = {
    "D03#01": 3,
    "D02#01": 3,
    "D04#01": 4,
    "D09#01": 5,
    "D15#01": 5,
    "D99#01": 1,
}


def make_chunk(row) -> dict:
    chunk_id, status, type_, revision, effective_from, supersedes, text, _ = row
    doc_id = chunk_id.split("#")[0]
    chunk = {
        "doc_id": doc_id,
        "title": f"Belge {doc_id}",
        "type": type_,
        "authority": "Kurgusal Makam",
        "airport": "XXXX",
        "language": "tr",
        "revision": revision,
        "effective_from": effective_from,
        "status": status,
        "chunk_id": chunk_id,
        "section": f"Bölüm {chunk_id}",
        "text": text,
        "context": f"[{doc_id}]",
    }
    if supersedes:
        chunk["supersedes"] = supersedes
    return chunk


def write_index(directory: Path, rows, model: str = MODEL) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [make_chunk(row) for row in rows]
    vectors = np.asarray([row[7] for row in rows], dtype=np.float32)
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


class FakeVoyage:
    """Her sorguyu `vector` alanına çevirir; çağrıları kaydeder, istenirse düşer."""

    def __init__(self):
        self.vector = [1.0, 0.0, 0.0]
        self.fail: Exception | None = None
        self.calls: list[dict] = []

    def embed(self, texts, model, input_type):
        self.calls.append(
            {"texts": list(texts), "model": model, "input_type": input_type}
        )
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(
            embeddings=[list(self.vector) for _ in texts], total_tokens=len(texts)
        )


@pytest.fixture
def voyage(monkeypatch, tmp_path):
    fake = FakeVoyage()
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.setattr(embed, "sleep", lambda seconds: None)
    monkeypatch.setattr(embed, "_make_client", lambda key: fake)
    monkeypatch.setenv("VOYAGE_API_KEY", SECRET)
    monkeypatch.setenv("COPILOT_EMBED_MODEL", MODEL)
    monkeypatch.setenv("COPILOT_RAG_ESIK", "0.5")
    monkeypatch.setenv("COPILOT_NOW", NOW)
    return fake


@pytest.fixture
def index_dir(tmp_path, monkeypatch, voyage):
    directory = tmp_path / "indeks"
    write_index(directory, list(reversed(ROWS)))
    monkeypatch.setattr(search, "INDEX_DIR", directory)
    return directory


def call(args) -> dict:
    envelope = run_tool(NAME, args)
    assert json.loads(json.dumps(envelope, ensure_ascii=False)) == envelope
    assert set(envelope) == {
        "value",
        "source",
        "as_of",
        "filters",
        "stale",
        "tool_version",
        "error",
        "author",
    }
    return envelope


def ids(envelope) -> list[str]:
    return [item["chunk_id"] for item in envelope["value"]]


def load_contract() -> dict:
    assert CONTRACT.exists(), "search_documents kontratı yok"
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def keywords(node) -> set[str]:
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            found |= keywords(value)
    elif isinstance(node, list):
        for value in node:
            found |= keywords(value)
    return found


# ───────── Kontrat ─────────


def test_kontrat_adi_surumu_ve_semalari_gecerli():
    contract = load_contract()

    assert contract["name"] == NAME
    assert contract["version"] == VERSION
    Draft202012Validator.check_schema(contract["input_schema"])
    Draft202012Validator.check_schema(contract["value_schema"])


def test_kontrat_girdisi_query_ve_include_superseded():
    schema = load_contract()["input_schema"]

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["query"]
    assert set(schema["properties"]) == {"query", "include_superseded"}
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["properties"]["include_superseded"]["type"] == "boolean"
    assert schema["properties"]["include_superseded"]["default"] is False


def test_kontrat_yasak_anahtar_kelimeleri_kullanmaz():
    contract = load_contract()

    assert not keywords(contract["input_schema"]) & FORBIDDEN_KEYWORDS
    assert not keywords(contract["value_schema"]) & FORBIDDEN_KEYWORDS


def test_kontrat_her_object_additional_properties_false():
    def objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                yield node
            for value in node.values():
                yield from objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from objects(value)

    contract = load_contract()
    found = [*objects(contract["input_schema"]), *objects(contract["value_schema"])]

    assert found
    assert all(node.get("additionalProperties") is False for node in found)


def test_kontrat_aciklamasi_uc_soruyu_cevaplar():
    description = load_contract()["description"]

    assert "Ne zaman kullanılır" in description
    assert "Ne zaman KULLANILMAZ" in description
    assert "include_superseded" in description
    assert "NOT_FOUND" in description


def test_tool_definitions_listesinin_sonunda_ve_kontratla_ayni():
    contract = load_contract()
    definitions = tool_definitions()

    assert definitions[-1] == {
        key: contract[key] for key in ("name", "description", "input_schema")
    }
    assert [d["name"] for d in definitions].count(NAME) == 1


# ───────── search(): vector_score ─────────


def run_search(index_dir, voyage, **kwargs):
    kwargs.setdefault("k", 6)
    return search.search(
        QUERY, index_dir=index_dir, client=voyage, model=MODEL, **kwargs
    )


@pytest.mark.parametrize("method", ["vector", "hybrid"])
def test_search_vector_ve_hybrid_ham_vektor_skorunu_verir(index_dir, voyage, method):
    results = run_search(index_dir, voyage, method=method)

    by_id = {r["chunk_id"]: r["vector_score"] for r in results}
    assert by_id == pytest.approx(
        {
            "D03#01": 1.0,
            "D02#01": 0.8,
            "D04#01": 0.6,
            "D09#01": 0.28,
            "D15#01": 0.0,
            "D99#01": -1.0,
        },
        abs=1e-6,
    )
    assert all(type(r["vector_score"]) is float for r in results)


def test_search_hibritte_score_rrf_vector_score_ayri(index_dir, voyage):
    top = run_search(index_dir, voyage, method="hybrid")[0]

    assert top["chunk_id"] == "D03#01"
    # Vektörde 1., bm25'te 2. (D02 ile eşit skor, chunk_id küçük olan önce).
    assert top["score"] == pytest.approx(1 / 61 + 1 / 62, abs=1e-12)
    assert top["vector_score"] == pytest.approx(1.0, abs=1e-6)


def test_search_vector_yonteminde_score_ve_vector_score_esit(index_dir, voyage):
    for result in run_search(index_dir, voyage, method="vector"):
        assert result["vector_score"] == result["score"]


def test_search_bm25_vector_score_icermez(index_dir, voyage):
    results = run_search(index_dir, voyage, method="bm25")

    assert results
    assert all("vector_score" not in r for r in results)


def test_search_vector_score_filtreden_sonraki_kumeyle_degismez(index_dir, voyage):
    results = run_search(index_dir, voyage, method="hybrid", status="active")

    assert {r["chunk_id"]: r["vector_score"] for r in results}[
        "D04#01"
    ] == pytest.approx(0.6, abs=1e-6)


def test_load_chunks_indeksteki_parcalari_verir(index_dir):
    chunks = search.load_chunks(index_dir)

    assert sorted(c["chunk_id"] for c in chunks) == sorted(r[0] for r in ROWS)
    assert next(c for c in chunks if c["chunk_id"] == "D03#01")["supersedes"] == "D02"


def test_load_chunks_indeks_yoksa_index_not_ready(tmp_path):
    with pytest.raises(search.IndexNotReadyError):
        search.load_chunks(tmp_path / "yok")


@pytest.mark.parametrize(("raw", "expected"), [("0.5", 0.5), (" 0.25 ", 0.25), ("1", 1.0)])
def test_rag_threshold_ortamdan_okunur(voyage, monkeypatch, raw, expected):
    monkeypatch.setenv("COPILOT_RAG_ESIK", raw)

    assert search.rag_threshold() == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "abc", "nan", "inf"])
def test_rag_threshold_eksik_ya_da_gecersizse_config_error(voyage, monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("COPILOT_RAG_ESIK")
    else:
        monkeypatch.setenv("COPILOT_RAG_ESIK", raw)

    with pytest.raises(embed.EmbedConfigError):
        search.rag_threshold()


# ───────── Tool: başarılı yanıt ─────────


def test_varsayilan_yalniz_aktif_parcalar_zarfi_tam(index_dir):
    envelope = call({"query": QUERY})

    assert envelope["error"] is None
    assert envelope["author"] == "tool"
    assert envelope["source"] == SOURCE
    assert envelope["as_of"] == NOW
    assert envelope["stale"] is False
    assert envelope["tool_version"] == VERSION
    assert envelope["filters"] == {"query": QUERY, "include_superseded": False}
    assert ids(envelope) == ACTIVE_ORDER


def test_include_superseded_eski_surumleri_de_getirir(index_dir):
    envelope = call({"query": QUERY, "include_superseded": True})

    assert envelope["filters"] == {"query": QUERY, "include_superseded": True}
    assert ids(envelope) == ALL_ORDER


def test_value_kontrat_semasina_uyar(index_dir):
    schema = load_contract()["value_schema"]

    for args in ({"query": QUERY}, {"query": QUERY, "include_superseded": True}):
        Draft202012Validator(schema).validate(call(args)["value"])


def test_parca_alanlari_belge_ve_surum_bilgisini_tasir(index_dir):
    item = call({"query": QUERY})["value"][0]

    assert item == {
        "chunk_id": "D03#01",
        "doc_id": "D03",
        "title": "Belge D03",
        "section": "Bölüm D03#01",
        "revision": "2",
        "effective_from": "2026-03-01",
        "status": "active",
        "supersedes": "D02",
        "authority": "Kurgusal Makam",
        "priority_level": 3,
        "language": "tr",
        "text": "dusuk gorus yeni",
    }


def test_skor_modele_gitmez(index_dir):
    for args in ({"query": QUERY}, {"query": QUERY, "include_superseded": True}):
        for item in call(args)["value"]:
            assert "score" not in item
            assert "vector_score" not in item
            assert "context" not in item
            assert "type" not in item


def test_supersedes_ve_superseded_by_kodca_hesaplanir(index_dir):
    items = {i["chunk_id"]: i for i in call({"query": QUERY, "include_superseded": True})["value"]}

    assert items["D03#01"]["supersedes"] == "D02"
    assert "superseded_by" not in items["D03#01"]
    assert items["D02#01"]["superseded_by"] == "D03"
    assert "supersedes" not in items["D02#01"]
    assert items["D02#01"]["status"] == "superseded"
    for chunk_id in ("D04#01", "D09#01", "D15#01", "D99#01"):
        assert "supersedes" not in items[chunk_id]
        assert "superseded_by" not in items[chunk_id]


def test_priority_level_type_den_gelir(index_dir):
    items = call({"query": QUERY, "include_superseded": True})["value"]

    assert {i["chunk_id"]: i["priority_level"] for i in items} == LEVELS


def test_value_de_null_alan_yok(index_dir):
    for item in call({"query": QUERY, "include_superseded": True})["value"]:
        assert None not in item.values()
        assert ITEM_FIELDS <= set(item)


@pytest.fixture
def many_index(tmp_path, monkeypatch, voyage):
    """10 parça, vektör ve bm25 sırası aynı (D01..D10); ilk 7'si aktif."""
    import math

    rows = []
    for number in range(1, 11):
        angle = number * 0.05
        rows.append(
            (
                f"D{number:02d}#01",
                "active" if number <= 7 else "superseded",
                "sop",
                "1",
                "2025-01-01",
                None,
                "pist",
                [math.cos(angle), math.sin(angle), 0.0],
            )
        )
    directory = tmp_path / "cok"
    write_index(directory, rows)
    monkeypatch.setattr(search, "INDEX_DIR", directory)
    return directory


def test_en_fazla_bes_parca_eski_surumlu_sekiz(many_index):
    default = call({"query": "pist"})
    superseded = call({"query": "pist", "include_superseded": True})

    assert ids(default) == [f"D{n:02d}#01" for n in range(1, 6)]
    assert ids(superseded) == [f"D{n:02d}#01" for n in range(1, 9)]


def test_tool_hibrit_arar_soruyu_bir_kez_gomer(index_dir, voyage):
    call({"query": QUERY})

    assert len(voyage.calls) == 1
    assert voyage.calls[0]["input_type"] == "query"
    assert voyage.calls[0]["model"] == MODEL
    assert voyage.calls[0]["texts"] == [QUERY]


def test_tool_copilot_data_okumaz(index_dir, monkeypatch):
    monkeypatch.delenv("COPILOT_DATA", raising=False)

    assert call({"query": QUERY})["error"] is None


def test_tool_indeksi_degistirmez(index_dir):
    before = {p.name: p.read_bytes() for p in index_dir.iterdir()}

    call({"query": QUERY, "include_superseded": True})

    assert {p.name: p.read_bytes() for p in index_dir.iterdir()} == before


# ───────── Tool: eşik ve NOT_FOUND ─────────


def not_found(filters=None) -> dict:
    return {
        "value": None,
        "source": SOURCE,
        "as_of": NOW,
        "filters": filters or {"query": QUERY, "include_superseded": False},
        "stale": False,
        "tool_version": VERSION,
        "error": NOT_FOUND,
        "author": "tool",
    }


def test_en_yuksek_vektor_puani_esigin_altindaysa_not_found(index_dir, monkeypatch):
    monkeypatch.setenv("COPILOT_RAG_ESIK", "1.5")  # en yüksek puan 1.0

    assert call({"query": QUERY}) == not_found()


def test_esige_esit_puan_gecer(index_dir, monkeypatch):
    monkeypatch.setenv("COPILOT_RAG_ESIK", "1.0")

    envelope = call({"query": QUERY})

    assert envelope["error"] is None
    assert ids(envelope) == ACTIVE_ORDER


def test_esik_vektor_puanina_uygulanir_rrf_skoruna_degil(
    index_dir, voyage, monkeypatch
):
    # RRF skorları ~0.03; eşik 0.5 olsa bile vektör puanı 1.0 olduğu için geçer.
    monkeypatch.setenv("COPILOT_RAG_ESIK", "0.5")

    assert call({"query": QUERY})["error"] is None


def test_sorgu_vektoru_ilgisizse_not_found_ve_value_null(index_dir, voyage, monkeypatch):
    voyage.vector = [0.0, 0.0, 1.0]  # hiçbir parçayla örtüşmez: tüm puanlar 0
    monkeypatch.setenv("COPILOT_RAG_ESIK", "0.1")

    assert call({"query": QUERY}) == not_found()


def test_esik_her_cagrida_ortamdan_okunur(index_dir, monkeypatch):
    assert call({"query": QUERY})["error"] is None
    monkeypatch.setenv("COPILOT_RAG_ESIK", "1.5")
    assert call({"query": QUERY})["error"] == NOT_FOUND
    monkeypatch.setenv("COPILOT_RAG_ESIK", "0.5")
    assert call({"query": QUERY})["error"] is None


def test_esik_yalniz_dondurulen_parcalara_bakar(index_dir, voyage, monkeypatch):
    # Sorgu D04 yönünde: yalnız aktif aramada en yüksek puan 0.6 → eşik 0.7'de NOT_FOUND;
    # eski sürümlü aramada D02 (0.8) da gelir ve eşiği geçer.
    voyage.vector = [0.6, 0.8, 0.0]
    monkeypatch.setenv("COPILOT_RAG_ESIK", "1.01")
    assert call({"query": QUERY})["error"] == NOT_FOUND

    monkeypatch.setenv("COPILOT_RAG_ESIK", "0.99")
    assert call({"query": QUERY})["error"] is None


def test_filtre_hicbir_parca_birakmazsa_not_found(tmp_path, monkeypatch, voyage):
    rows = [row for row in ROWS if row[1] == "superseded"]  # yalnız eski sürüm
    directory = tmp_path / "eski"
    write_index(directory, rows)
    monkeypatch.setattr(search, "INDEX_DIR", directory)

    assert call({"query": QUERY}) == not_found()
    assert voyage.calls == []  # aday yoksa gömme çağrısı yapılmaz


# ───────── Tool: argüman hataları ─────────


def invalid(args=None) -> dict:
    return {
        "value": None,
        "source": None,
        "as_of": None,
        "filters": {},
        "stale": False,
        "tool_version": VERSION,
        "error": ARGS_INVALID,
        "author": "layer",
    }


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": 5},
        {"query": None},
        {"query": QUERY, "include_superseded": "evet"},
        {"query": QUERY, "include_superseded": 1},
        {"query": QUERY, "extra": 1},
        None,
        [],
        "soru",
    ],
)
def test_gecersiz_arguman_sema_hatasi_gomme_yok(index_dir, voyage, args):
    assert call(args) == invalid()
    assert voyage.calls == []


# ───────── Tool: veri hatası (katman) ─────────


def layer_failure(filters=None) -> dict:
    return {
        "value": None,
        "source": None,
        "as_of": None,
        "filters": filters or {"query": QUERY, "include_superseded": False},
        "stale": False,
        "tool_version": VERSION,
        "error": DATA_INVALID,
        "author": "layer",
    }


def test_indeks_yoksa_katman_hatasi(tmp_path, monkeypatch, voyage):
    monkeypatch.setattr(search, "INDEX_DIR", tmp_path / "yok")

    assert call({"query": QUERY}) == layer_failure()
    assert voyage.calls == []


def test_indeks_modeli_farkliysa_katman_hatasi_gomme_yok(
    index_dir, voyage, monkeypatch
):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    assert call({"query": QUERY}) == layer_failure()
    assert voyage.calls == []


def test_gomme_hatasinda_katman_hatasi_sir_sizmaz(index_dir, voyage):
    voyage.fail = RuntimeError(f"sır: {SECRET}")

    envelope = call({"query": QUERY})

    assert envelope == layer_failure()
    assert SECRET not in json.dumps(envelope, ensure_ascii=False)


@pytest.mark.parametrize("raw", [None, "", "abc"])
def test_esik_ayari_eksik_ya_da_gecersizse_katman_hatasi(
    index_dir, voyage, monkeypatch, raw
):
    if raw is None:
        monkeypatch.delenv("COPILOT_RAG_ESIK")
    else:
        monkeypatch.setenv("COPILOT_RAG_ESIK", raw)

    assert call({"query": QUERY}) == layer_failure()
    assert voyage.calls == []


def test_katman_hatasi_include_superseded_filtresini_tasir(index_dir, monkeypatch):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    assert call({"query": QUERY, "include_superseded": True}) == layer_failure(
        {"query": QUERY, "include_superseded": True}
    )
