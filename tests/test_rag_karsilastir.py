"""Sorgu önbelleği ve `scripts/rag_karsilastir.py` sözleşmesi (docs/hibrit.md › Ölçüt,
Önbellek ve istek sayısı).

Ağa çıkmaz, `.env` gerektirmez; Voyage sahte istemcidir. Testler koddan önce
yazıldı: `embed.embed_queries` ve betik yokken kırmızıdır.

Test için sabitlenen adlar (docs'ta açık değil):
- `embed.QUERY_CACHE` (yol, çağrı anında okunur) ve
  `embed.embed_queries(texts, client=None, model=None, cache_path=None)`;
  dönüş: `.vectors` (girdiyle aynı sırada birim vektörler), `.model`, `.fetched`
  (API'ye giden benzersiz sorgu sayısı).
- Önbellek dosyası: `{model: {sorgu: [vektör]}}`.
- Betik: `--sorular`, `--indeks`, `--out` (varsayılan `DEFAULT_OUT`); var olan
  `--out` dosyasının üzerine yazılmaz.

Betik veri kümesi (8 parça, 4 boyut) ve sorular:
  K1 "holdover tablo"   kelime      → D04    vektör [1,0,0,0]
  K2 "pbb ariza"        kelime      → D05    vektör [0,0,0,1] (vektör D05'i bulamaz)
  A1 anlam, C1 capraz_dil → D05      vektör [0,1,0,0] (bm25 hiç eşleşme bulamaz)
  O1 "stand kod"        oncelik     → D01, D07, ilk D07; vektör [0,0,1,0]
O1'de hybrid D01'i, hybrid + priority D07'yi öne alır (2/61·0.94 < 2/62·0.97).
"""

import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.rag import embed

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rag_karsilastir.py"
MODEL = "sahte-gomme-modeli"
SECRET = "gizli-anahtar-xyz"


# ───────── ortak sahte Voyage ─────────


class FakeVoyage:
    """`vectors` sözlüğündeki vektörü döndürür; yoksa [len, 1, 0]. Çağrıları kaydeder."""

    def __init__(self, vectors: dict[str, list[float]] | None = None):
        self.vectors = vectors or {}
        self.fail: Exception | None = None
        self.calls: list[dict] = []

    def embed(self, texts, model, input_type):
        self.calls.append(
            {"texts": list(texts), "model": model, "input_type": input_type}
        )
        if self.fail is not None:
            raise self.fail
        return SimpleNamespace(
            embeddings=[
                list(self.vectors.get(text, [float(len(text)), 1.0, 0.0]))
                for text in texts
            ],
            total_tokens=len(texts),
        )


def unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


@pytest.fixture
def cache_path(tmp_path, monkeypatch):
    path = tmp_path / "veri" / "sorgu_onbellegi.json"
    monkeypatch.setattr(embed, "QUERY_CACHE", path, raising=False)
    return path


@pytest.fixture
def voyage(monkeypatch, tmp_path, cache_path):
    fake = FakeVoyage()
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.setattr(embed, "sleep", lambda seconds: None)
    monkeypatch.setattr(embed, "_make_client", lambda key: fake)
    monkeypatch.setenv("VOYAGE_API_KEY", SECRET)
    monkeypatch.setenv("COPILOT_EMBED_MODEL", MODEL)
    return fake


def has_embed_queries() -> None:
    assert hasattr(embed, "embed_queries"), "embed.embed_queries yok"


# ───────── embed.embed_queries: önbellek ─────────


def test_hepsi_tek_istekte_query_olarak_gomulur(voyage):
    has_embed_queries()

    result = embed.embed_queries(["bir", "iki üç", "dört"], client=voyage, model=MODEL)

    assert len(voyage.calls) == 1
    assert voyage.calls[0]["texts"] == ["bir", "iki üç", "dört"]
    assert voyage.calls[0]["input_type"] == "query"
    assert voyage.calls[0]["model"] == MODEL
    assert result.model == MODEL
    assert result.fetched == 3
    assert result.vectors == [
        pytest.approx(unit([float(len(t)), 1.0, 0.0]), abs=1e-12)
        for t in ("bir", "iki üç", "dört")
    ]


def test_tekrar_eden_sorgu_bir_kez_gonderilir_sira_korunur(voyage):
    has_embed_queries()

    result = embed.embed_queries(["a", "bb", "a"], client=voyage, model=MODEL)

    assert voyage.calls[0]["texts"] == ["a", "bb"]
    assert result.fetched == 2
    assert len(result.vectors) == 3
    assert result.vectors[0] == result.vectors[2]
    assert result.vectors[0] != result.vectors[1]


def test_ikinci_cagri_onbellekten_gelir_istek_yok(voyage, cache_path, monkeypatch):
    has_embed_queries()
    first = embed.embed_queries(["bir", "iki"], client=voyage, model=MODEL)

    def no_client(key):
        raise AssertionError("önbellekteki sorgu için istemci kurulmamalı")

    monkeypatch.setattr(embed, "_make_client", no_client)
    second = embed.embed_queries(["iki", "bir"], model=MODEL)

    assert len(voyage.calls) == 1
    assert second.fetched == 0
    assert second.vectors == [first.vectors[1], first.vectors[0]]


def test_kismi_onbellek_yalniz_eksikler_tek_istekle_gider(voyage):
    has_embed_queries()
    embed.embed_queries(["bir", "iki"], client=voyage, model=MODEL)

    result = embed.embed_queries(["bir", "üç", "dört"], client=voyage, model=MODEL)

    assert len(voyage.calls) == 2
    assert voyage.calls[1]["texts"] == ["üç", "dört"]
    assert result.fetched == 2


def test_model_anahtarin_parcasi_baska_model_onbellegi_kullanmaz(voyage, cache_path):
    has_embed_queries()
    embed.embed_queries(["bir"], client=voyage, model="model-a")

    result = embed.embed_queries(["bir"], client=voyage, model="model-b")

    assert len(voyage.calls) == 2
    assert result.fetched == 1
    stored = json.loads(cache_path.read_text(encoding="utf-8"))
    assert sorted(stored) == ["model-a", "model-b"]
    assert list(stored["model-a"]) == ["bir"]


def test_onbellek_dosya_bicimi_model_sorgu_vektor(voyage, cache_path):
    has_embed_queries()
    result = embed.embed_queries(["bir"], client=voyage, model=MODEL)

    stored = json.loads(cache_path.read_text(encoding="utf-8"))

    assert stored == {MODEL: {"bir": pytest.approx(result.vectors[0], abs=1e-15)}}


def test_onbellek_klasoru_yoksa_olusturulur_gecici_dosya_kalmaz(voyage, cache_path):
    has_embed_queries()
    assert not cache_path.parent.exists()

    embed.embed_queries(["bir"], client=voyage, model=MODEL)

    assert [p.name for p in cache_path.parent.iterdir()] == [cache_path.name]


def test_cache_path_argumani_varsayilani_ezer(voyage, tmp_path, cache_path):
    has_embed_queries()
    other = tmp_path / "baska.json"

    embed.embed_queries(["bir"], client=voyage, model=MODEL, cache_path=other)

    assert other.is_file()
    assert not cache_path.exists()


def test_bozuk_onbellek_yok_sayilir_ve_yeniden_yazilir(voyage, cache_path):
    has_embed_queries()
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("{bozuk json", encoding="utf-8")

    result = embed.embed_queries(["bir"], client=voyage, model=MODEL)

    assert result.fetched == 1
    assert list(json.loads(cache_path.read_text(encoding="utf-8"))[MODEL]) == ["bir"]


@pytest.mark.parametrize(
    "content",
    [[], {MODEL: []}, {MODEL: {"bir": "vektör değil"}}, {MODEL: {"bir": [1, "x"]}}],
)
def test_beklenmedik_bicimli_onbellek_yok_sayilir(voyage, cache_path, content):
    has_embed_queries()
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(json.dumps(content), encoding="utf-8")

    result = embed.embed_queries(["bir"], client=voyage, model=MODEL)

    assert result.fetched == 1


def test_yazilamayan_onbellek_aramayi_bozmaz(voyage, cache_path):
    has_embed_queries()
    cache_path.mkdir(parents=True)  # dosya yerine klasör: okunamaz, yazılamaz

    result = embed.embed_queries(["bir"], client=voyage, model=MODEL)

    assert result.fetched == 1
    assert len(result.vectors) == 1


def test_degistirme_permission_error_verirse_yeniden_denenir(
    voyage, cache_path, monkeypatch
):
    has_embed_queries()
    real_replace = embed.os.replace
    attempts = []

    def flaky(src, dst):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("kilit")
        real_replace(src, dst)

    monkeypatch.setattr(embed.os, "replace", flaky)

    embed.embed_queries(["bir"], client=voyage, model=MODEL)

    assert len(attempts) == 3
    assert cache_path.is_file()


def test_gomme_hatasinda_onbellege_yazilmaz(voyage, cache_path):
    has_embed_queries()
    voyage.fail = RuntimeError(f"sır: {SECRET}")

    with pytest.raises(embed.EmbedError) as info:
        embed.embed_queries(["bir"], client=voyage, model=MODEL)

    assert SECRET not in str(info.value)
    assert not cache_path.exists()


def test_gomme_hatasi_eski_onbellegi_bozmaz(voyage, cache_path):
    has_embed_queries()
    embed.embed_queries(["bir"], client=voyage, model=MODEL)
    before = cache_path.read_bytes()
    voyage.fail = RuntimeError("patladı")

    with pytest.raises(embed.EmbedError):
        embed.embed_queries(["bir", "iki"], client=voyage, model=MODEL)

    assert cache_path.read_bytes() == before


def test_128den_fazla_eksik_sorgu_gruplanir(voyage):
    has_embed_queries()
    texts = [f"soru {n}" for n in range(130)]

    result = embed.embed_queries(texts, client=voyage, model=MODEL)

    assert [len(c["texts"]) for c in voyage.calls] == [128, 2]
    assert result.fetched == 130


def test_bos_sorgu_metni_value_error_ve_istek_yok(voyage):
    has_embed_queries()

    with pytest.raises(ValueError):
        embed.embed_queries(["bir", "   "], client=voyage, model=MODEL)

    assert voyage.calls == []


def test_bos_liste_istek_yapmaz(voyage):
    has_embed_queries()

    result = embed.embed_queries([], client=voyage, model=MODEL)

    assert result.vectors == []
    assert result.fetched == 0
    assert voyage.calls == []


def test_embed_query_onbellegi_kullanmaz_ve_yazmaz(voyage, cache_path):
    embed.embed_query("bir", client=voyage, model=MODEL)

    assert not cache_path.exists()


# ───────── scripts/rag_karsilastir.py ─────────

# (chunk_id, doc_id, type, text, vektör)
ROWS = [
    ("D01#01", "D01", "aerodrome_manual", "stand kod stand kod", [0.0, 0.0, 1.0, 0.0]),
    ("D04#01", "D04", "sop", "holdover tablo", [1.0, 0.0, 0.0, 0.0]),
    ("D05#01", "D05", "sop", "pbb ariza", [0.0, 1.0, 0.0, 0.0]),
    ("D07#01", "D07", "aerodrome_restrictions", "stand kod", [0.0, 0.0, 0.6, 0.8]),
    ("D10#01", "D10", "temporary_note", "zzzz", [0.0, 0.0, 0.0, 1.0]),
    ("D11#01", "D11", "sla_annex", "zzzz", [0.0, 0.0, 0.0, 1.0]),
    ("D12#01", "D12", "agreement_summary", "zzzz", [0.0, 0.0, 0.0, 1.0]),
]  # fmt: skip

QUESTIONS = [
    {"id": "K1", "soru": "holdover tablo", "tip": "kelime", "beklenen_belge": ["D04"]},
    {"id": "K2", "soru": "pbb ariza", "tip": "kelime", "beklenen_belge": ["D05"]},
    {
        "id": "A1",
        "soru": "koprunun yerine ne yapilir",
        "tip": "anlam",
        "beklenen_belge": ["D05"],
    },
    {
        "id": "C1",
        "soru": "boarding bridge",
        "tip": "capraz_dil",
        "beklenen_belge": ["D05"],
    },
    {
        "id": "O1",
        "soru": "stand kod",
        "tip": "oncelik",
        "beklenen_belge": ["D01", "D07"],
        "ilk_beklenen": "D07",
    },
]
QUERY_VECTORS = {
    "holdover tablo": [1.0, 0.0, 0.0, 0.0],
    "pbb ariza": [0.0, 0.0, 0.0, 1.0],
    "koprunun yerine ne yapilir": [0.0, 1.0, 0.0, 0.0],
    "boarding bridge": [0.0, 1.0, 0.0, 0.0],
    "stand kod": [0.0, 0.0, 1.0, 0.0],
}
HEADER = "| Yöntem | Kelime | Anlam | Çapraz dil | Öncelik | Tümü | İlk sıra doğru |"
SEPARATOR = "|---|---|---|---|---|---|---|"
TABLE_ROWS = [
    "| `bm25` | 1.00 | 0.00 | 0.00 | 1.00 | 0.60 | 0/1 |",
    "| `vector` | 0.50 | 1.00 | 1.00 | 1.00 | 0.80 | 0/1 |",
    "| `hybrid` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0/1 |",
    "| `hybrid + priority` | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1/1 |",
]


def write_index(directory: Path, model: str = MODEL) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [
        {
            "doc_id": doc_id,
            "title": f"Belge {doc_id}",
            "type": type_,
            "authority": "Kurgusal Makam",
            "airport": "XXXX",
            "language": "tr",
            "revision": "1",
            "effective_from": "2025-03-01",
            "status": "active",
            "chunk_id": chunk_id,
            "section": f"Bölüm {chunk_id}",
            "text": text,
            "context": f"[{doc_id}]",
        }
        for chunk_id, doc_id, type_, text, _ in ROWS
    ]
    vectors = np.asarray([row[4] for row in ROWS], dtype=np.float32)
    (directory / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    np.save(directory / "vektorler.npy", vectors, allow_pickle=False)
    meta = {
        "model": model,
        "dimension": 4,
        "chunk_count": len(chunks),
        "corpus_sha256": "0" * 64,
    }
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def write_questions(path: Path, questions=None) -> Path:
    path.write_text(
        json.dumps(QUESTIONS if questions is None else questions, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def env(tmp_path, voyage):
    voyage.vectors = QUERY_VECTORS
    index_dir = tmp_path / "indeks"
    write_index(index_dir)
    return SimpleNamespace(
        index=index_dir,
        questions=write_questions(tmp_path / "sorular.json"),
        out=tmp_path / "cikti" / "sonuc.json",
        voyage=voyage,
    )


def load_script():
    assert SCRIPT.exists(), "scripts/rag_karsilastir.py yok"
    spec = importlib.util.spec_from_file_location("rag_karsilastir", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(env, *extra, out=None):
    module = load_script()
    return module.main(
        [
            "--sorular",
            str(env.questions),
            "--indeks",
            str(env.index),
            "--out",
            str(out or env.out),
            *extra,
        ]
    )


def test_tablo_hucreleri_ve_satirlar(env, capsys):
    code = run(env)

    out = capsys.readouterr().out
    assert code == 0
    lines = out.splitlines()
    assert HEADER in lines
    assert lines[lines.index(HEADER) + 1] == SEPARATOR
    start = lines.index(HEADER) + 2
    assert lines[start : start + 4] == TABLE_ROWS


def test_tum_sorgular_tek_istekte_gomulur(env):
    assert run(env) == 0

    assert len(env.voyage.calls) == 1
    assert env.voyage.calls[0]["input_type"] == "query"
    assert env.voyage.calls[0]["texts"] == [q["soru"] for q in QUESTIONS]


def test_ikinci_kosu_onbellekten_istek_yapmaz_ayni_tabloyu_verir(
    env, tmp_path, capsys
):
    assert run(env) == 0
    first = capsys.readouterr().out

    assert run(env, out=tmp_path / "ikinci.json") == 0

    second = capsys.readouterr().out
    assert len(env.voyage.calls) == 1
    for row in TABLE_ROWS:
        assert row in first
        assert row in second


def test_istek_sayisi_stderr_de_bildirilir(env, tmp_path, capsys):
    run(env)
    first = capsys.readouterr().err
    run(env, out=tmp_path / "ikinci.json")
    second = capsys.readouterr().err

    assert "Gömme: 5 sorgu, 1 istek (önbellekten 0)." in first
    assert "Gömme: 5 sorgu, 0 istek (önbellekten 5)." in second


def test_sonuc_dosyasi_yazilir(env):
    assert run(env) == 0

    saved = json.loads(env.out.read_text(encoding="utf-8"))
    assert saved["model"] == MODEL
    assert saved["k"] == 5
    assert [row["yontem"] for row in saved["satirlar"]] == [
        "bm25",
        "vector",
        "hybrid",
        "hybrid + priority",
    ]
    assert saved["sonuclar"]["hybrid + priority"]["O1"][0] == "D07#01"
    assert saved["sonuclar"]["hybrid"]["O1"][0] == "D01#01"
    assert saved["sonuclar"]["bm25"]["A1"] == []


def test_sonuc_dosyasi_klasoru_yoksa_olusturulur(env):
    assert not env.out.parent.exists()

    assert run(env) == 0

    assert env.out.is_file()


def test_var_olan_sonuc_dosyasinin_uzerine_yazilmaz(env, capsys):
    env.out.parent.mkdir(parents=True)
    env.out.write_text("eski sonuç", encoding="utf-8")

    code = run(env)

    captured = capsys.readouterr()
    assert code == 1
    assert "Hata:" in captured.err
    assert env.out.read_text(encoding="utf-8") == "eski sonuç"
    assert env.voyage.calls == []


def test_varsayilan_cikti_yolu(env, tmp_path, monkeypatch):
    module = load_script()
    default = tmp_path / "varsayilan" / "arama.json"
    monkeypatch.setattr(module, "DEFAULT_OUT", default)

    code = module.main(
        ["--sorular", str(env.questions), "--indeks", str(env.index)]
    )

    assert code == 0
    assert default.is_file()


def test_indeks_yoksa_hata_ve_istek_yok(env, tmp_path, capsys):
    env.index = tmp_path / "yok"

    code = run(env)

    captured = capsys.readouterr()
    assert code == 1
    assert "Hata:" in captured.err
    assert env.voyage.calls == []
    assert not env.out.exists()


def test_model_farkliysa_hata_ve_istek_yok(env, monkeypatch, capsys):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.voyage.calls == []
    assert not env.out.exists()


def test_gomme_hatasinda_hata_1_sir_yazmaz_cikti_yok(env, capsys):
    env.voyage.fail = RuntimeError(f"sır: {SECRET}")

    code = run(env)

    captured = capsys.readouterr()
    assert code == 1
    assert "Hata:" in captured.err
    assert SECRET not in captured.out + captured.err
    assert not env.out.exists()


def test_indeksi_degistirmez(env):
    before = {p.name: p.read_bytes() for p in env.index.iterdir()}

    run(env)

    assert {p.name: p.read_bytes() for p in env.index.iterdir()} == before


def bad_question(**changes):
    question = dict(QUESTIONS[0])
    question.update(changes)
    return [question]


@pytest.mark.parametrize(
    "questions",
    [
        [],
        {"id": "K1"},
        bad_question(tip="bilinmeyen"),
        bad_question(beklenen_belge=[]),
        bad_question(soru="   "),
        [QUESTIONS[-1] | {"ilk_beklenen": None}],
    ],
)
def test_gecersiz_soru_dosyasi_hata_ve_istek_yok(env, capsys, questions):
    write_questions(env.questions, questions)

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.voyage.calls == []
    assert not env.out.exists()


def test_soru_dosyasi_yoksa_hata(env, tmp_path, capsys):
    env.questions = tmp_path / "yok.json"

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.voyage.calls == []


def test_soru_dosyasi_json_degilse_hata(env, capsys):
    env.questions.write_text("{bozuk", encoding="utf-8")

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.voyage.calls == []


def test_gercek_soru_dosyasi_gecerli(env):
    real = REPO_ROOT / "eval" / "arama_sorulari.json"
    module = load_script()

    questions = module.load_questions(real)

    assert len(questions) == 12
    assert {q["tip"] for q in questions} == {
        "kelime",
        "anlam",
        "capraz_dil",
        "oncelik",
    }
