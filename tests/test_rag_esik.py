"""`scripts/rag_esik.py` sözleşmesi (docs/kaynakli.md › Eşik).

Ağa çıkmaz, `.env` gerektirmez; Voyage sahte istemcidir. Testler koddan önce
yazıldı: betik yokken kırmızıdır.

Test için sabitlenen adlar (docs'ta açık değil):
- Betik: `--sorular`, `--indeks`, `--out` (varsayılan `DEFAULT_OUT`); var olan
  `--out` dosyasının üzerine yazılmaz. Sorgu vektörleri `embed.embed_queries`
  önbelleğinden gelir (`rag_karsilastir.py` ile ortak anahtar: model + sorgu metni).
- Soru başına puan: `vector` yöntemiyle en yüksek iç çarpım; `include_superseded`
  false ise yalnızca `status: active` parçalar aranır.

Veri kümesi (8 parça, 4 boyut) ve sorular (puan, en yüksek parça):
  S1 "holdover tablo"      cevaplanabilir  [1,0,0,0]         → 1.0000 D04#01
  S2 "koprunun yerine ..." cevaplanabilir  [0,0.6,0.8,0]     → 0.8000 D01#01
  S3 "eski prosedur"       cevaplanabilir, include_superseded → 1.0000 D02#01
  S4 "eski prosedur"       cevaplanabilir, yalnız active      → 0.8000 D05#01
  U1 "tayfun uyarisi"      cevaplanamaz    [0,0,0,-1]        → 0.0000 D01#01
  U2 "yemekhane menusu"    cevaplanamaz    [0.28,0,0,-0.96]  → 0.2800 D04#01
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.rag import embed

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "rag_esik.py"
MODEL = "sahte-gomme-modeli"
SECRET = "gizli-anahtar-xyz"


class FakeVoyage:
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
            embeddings=[list(self.vectors[text]) for text in texts],
            total_tokens=len(texts),
        )


@pytest.fixture
def voyage(monkeypatch, tmp_path):
    fake = FakeVoyage()
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.setattr(embed, "sleep", lambda seconds: None)
    monkeypatch.setattr(embed, "_make_client", lambda key: fake)
    monkeypatch.setattr(
        embed, "QUERY_CACHE", tmp_path / "veri" / "sorgu_onbellegi.json"
    )
    monkeypatch.setenv("VOYAGE_API_KEY", SECRET)
    monkeypatch.setenv("COPILOT_EMBED_MODEL", MODEL)
    return fake


# (chunk_id, doc_id, status, type, text, vektör)
ROWS = [
    ("D01#01", "D01", "active", "aerodrome_manual", "stand kod", [0.0, 0.0, 1.0, 0.0]),
    ("D02#01", "D02", "superseded", "aerodrome_manual", "eski", [0.6, 0.8, 0.0, 0.0]),
    ("D04#01", "D04", "active", "sop", "holdover tablo", [1.0, 0.0, 0.0, 0.0]),
    ("D05#01", "D05", "active", "sop", "pbb ariza", [0.0, 1.0, 0.0, 0.0]),
    ("D07#01", "D07", "active", "aerodrome_restrictions", "kod", [0.0, 0.0, 0.6, 0.8]),
    ("D10#01", "D10", "active", "temporary_note", "zzzz", [0.0, 0.0, 0.0, 1.0]),
    ("D11#01", "D11", "active", "sla_annex", "zzzz", [0.0, 0.0, 0.0, 1.0]),
    ("D12#01", "D12", "active", "agreement_summary", "zzzz", [0.0, 0.0, 0.0, 1.0]),
]  # fmt: skip

QUESTIONS = [
    {
        "id": "S1",
        "soru": "holdover tablo",
        "cevaplanabilir": True,
        "beklenen_belgeler": ["D04"],
        "include_superseded": False,
    },
    {
        "id": "S2",
        "soru": "koprunun yerine ne yapilir",
        "cevaplanabilir": True,
        "beklenen_belgeler": ["D01"],
        "include_superseded": False,
    },
    {
        "id": "S3",
        "soru": "eski prosedur",
        "cevaplanabilir": True,
        "beklenen_belgeler": ["D02"],
        "include_superseded": True,
    },
    {
        "id": "S4",
        "soru": "eski prosedur",
        "cevaplanabilir": True,
        "beklenen_belgeler": ["D05"],
        "include_superseded": False,
    },
    {
        "id": "U1",
        "soru": "tayfun uyarisi",
        "cevaplanabilir": False,
        "beklenen_belgeler": [],
        "include_superseded": False,
    },
    {
        "id": "U2",
        "soru": "yemekhane menusu",
        "cevaplanabilir": False,
        "beklenen_belgeler": [],
        "include_superseded": False,
    },
]
QUERY_VECTORS = {
    "holdover tablo": [1.0, 0.0, 0.0, 0.0],
    "koprunun yerine ne yapilir": [0.0, 0.6, 0.8, 0.0],
    "eski prosedur": [0.6, 0.8, 0.0, 0.0],
    "tayfun uyarisi": [0.0, 0.0, 0.0, -1.0],
    "yemekhane menusu": [0.28, 0.0, 0.0, -0.96],
}
QUESTION_HEADER = "| Soru | Kategori | En yüksek vektör puanı | Parça | Beklenen belgede |"
QUESTION_ROWS = [
    "| S1 | cevaplanabilir | 1.0000 | D04#01 | evet |",
    "| S2 | cevaplanabilir | 0.8000 | D01#01 | evet |",
    "| S3 | cevaplanabilir | 1.0000 | D02#01 | evet |",
    "| S4 | cevaplanabilir | 0.8000 | D05#01 | evet |",
    "| U1 | cevaplanamaz | 0.0000 | D01#01 | - |",
    "| U2 | cevaplanamaz | 0.2800 | D04#01 | - |",
]
SUMMARY_HEADER = "| Kategori | Soru sayısı | En düşük | En yüksek |"
SUMMARY_ROWS = [
    "| cevaplanabilir | 4 | 0.8000 | 1.0000 |",
    "| cevaplanamaz | 2 | 0.0000 | 0.2800 |",
]
GAP_LINE = (
    "Ayrım: cevaplanamaz en yüksek 0.2800 < cevaplanabilir en düşük 0.8000; "
    "eşik (0.2800, 0.8000] aralığında seçilebilir."
)


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
            "status": status,
            "chunk_id": chunk_id,
            "section": f"Bölüm {chunk_id}",
            "text": text,
            "context": f"[{doc_id}]",
        }
        for chunk_id, doc_id, status, type_, text, _ in ROWS
    ]
    vectors = np.asarray([row[5] for row in ROWS], dtype=np.float32)
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
    voyage.vectors = dict(QUERY_VECTORS)
    index_dir = tmp_path / "indeks"
    write_index(index_dir)
    return SimpleNamespace(
        index=index_dir,
        questions=write_questions(tmp_path / "sorular.json"),
        out=tmp_path / "cikti" / "esik.json",
        voyage=voyage,
    )


def load_script():
    assert SCRIPT.exists(), "scripts/rag_esik.py yok"
    spec = importlib.util.spec_from_file_location("rag_esik", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(env, out=None):
    return load_script().main(
        [
            "--sorular",
            str(env.questions),
            "--indeks",
            str(env.index),
            "--out",
            str(out or env.out),
        ]
    )


def test_soru_tablosu_puan_ve_en_yuksek_parca(env, capsys):
    code = run(env)

    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert QUESTION_HEADER in lines
    start = lines.index(QUESTION_HEADER)
    assert lines[start + 1] == "|---|---|---|---|---|"
    assert lines[start + 2 : start + 2 + len(QUESTION_ROWS)] == QUESTION_ROWS


def test_kategori_ozeti_en_dusuk_ve_en_yuksek(env, capsys):
    assert run(env) == 0

    lines = capsys.readouterr().out.splitlines()
    start = lines.index(SUMMARY_HEADER)
    assert lines[start + 1] == "|---|---|---|---|"
    assert lines[start + 2 : start + 4] == SUMMARY_ROWS


def test_ayrim_satiri_esik_araligini_soyler(env, capsys):
    assert run(env) == 0

    assert GAP_LINE in capsys.readouterr().out.splitlines()


def test_cakisma_varsa_tek_esik_ayirmaz_denir(env, capsys):
    env.voyage.vectors["yemekhane menusu"] = [1.0, 0.0, 0.0, 0.0]  # puan 1.0000

    assert run(env) == 0

    out = capsys.readouterr().out
    assert (
        "Çakışma: cevaplanamaz en yüksek 1.0000 >= cevaplanabilir en düşük 0.8000; "
        "tek bir vektör eşiği ikisini ayıramaz."
    ) in out.splitlines()
    assert "Ayrım:" not in out


def test_include_superseded_aramayi_belirler(env, capsys):
    run(env)

    out = capsys.readouterr().out
    # S3 eski sürümü de arar (D02#01 en yüksek), S4 aynı sorguyla yalnız active arar.
    assert "| S3 | cevaplanabilir | 1.0000 | D02#01 | evet |" in out
    assert "| S4 | cevaplanabilir | 0.8000 | D05#01 | evet |" in out


def test_sorgular_tek_istekte_gomulur_tekrar_eden_bir_kez(env):
    assert run(env) == 0

    assert len(env.voyage.calls) == 1
    assert env.voyage.calls[0]["input_type"] == "query"
    assert env.voyage.calls[0]["texts"] == [
        "holdover tablo",
        "koprunun yerine ne yapilir",
        "eski prosedur",
        "tayfun uyarisi",
        "yemekhane menusu",
    ]


def test_ikinci_kosu_onbellekten_istek_yapmaz(env, tmp_path, capsys):
    run(env)
    first = capsys.readouterr()

    assert run(env, out=tmp_path / "ikinci.json") == 0

    second = capsys.readouterr()
    assert len(env.voyage.calls) == 1
    assert "Gömme: 5 sorgu, 1 istek (önbellekten 0)." in first.err
    assert "Gömme: 5 sorgu, 0 istek (önbellekten 5)." in second.err
    assert second.out == first.out


def test_karsilastir_ile_ortak_onbellek_anahtari(env, capsys):
    # rag_karsilastir.py aynı embed.embed_queries önbelleğini kullanır.
    embed.embed_queries(["holdover tablo"], model=MODEL)
    assert len(env.voyage.calls) == 1

    assert run(env) == 0

    assert env.voyage.calls[1]["texts"] == [
        "koprunun yerine ne yapilir",
        "eski prosedur",
        "tayfun uyarisi",
        "yemekhane menusu",
    ]
    assert "Gömme: 5 sorgu, 1 istek (önbellekten 1)." in capsys.readouterr().err


def test_sonuc_dosyasi_yazilir(env):
    assert run(env) == 0

    saved = json.loads(env.out.read_text(encoding="utf-8"))
    assert saved["model"] == MODEL
    by_id = {row["id"]: row for row in saved["sorular"]}
    assert [row["id"] for row in saved["sorular"]] == [q["id"] for q in QUESTIONS]
    assert by_id["S1"]["kategori"] == "cevaplanabilir"
    assert by_id["S1"]["puan"] == pytest.approx(1.0, abs=1e-6)
    assert by_id["S1"]["chunk_id"] == "D04#01"
    assert by_id["U2"]["kategori"] == "cevaplanamaz"
    assert by_id["U2"]["puan"] == pytest.approx(0.28, abs=1e-6)
    assert saved["kategoriler"]["cevaplanabilir"]["en_dusuk"] == pytest.approx(
        0.8, abs=1e-6
    )
    assert saved["kategoriler"]["cevaplanamaz"]["en_yuksek"] == pytest.approx(
        0.28, abs=1e-6
    )


def test_sonuc_dosyasi_klasoru_yoksa_olusturulur(env):
    assert not env.out.parent.exists()

    assert run(env) == 0

    assert env.out.is_file()


def test_var_olan_sonuc_dosyasinin_uzerine_yazilmaz(env, capsys):
    env.out.parent.mkdir(parents=True)
    env.out.write_text("eski sonuç", encoding="utf-8")

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.out.read_text(encoding="utf-8") == "eski sonuç"
    assert env.voyage.calls == []


def test_varsayilan_cikti_yolu(env, tmp_path, monkeypatch):
    module = load_script()
    default = tmp_path / "varsayilan" / "esik.json"
    monkeypatch.setattr(module, "DEFAULT_OUT", default)

    code = module.main(["--sorular", str(env.questions), "--indeks", str(env.index)])

    assert code == 0
    assert default.is_file()


def test_indeks_yoksa_hata_ve_istek_yok(env, tmp_path, capsys):
    env.index = tmp_path / "yok"

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.voyage.calls == []
    assert not env.out.exists()


def test_model_farkliysa_hata_ve_istek_yok(env, monkeypatch, capsys):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.voyage.calls == []


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


def bad(**changes):
    question = dict(QUESTIONS[0])
    question.update(changes)
    return [question]


@pytest.mark.parametrize(
    "questions",
    [
        [],
        {"id": "S1"},
        bad(soru="   "),
        bad(cevaplanabilir="evet"),
        bad(include_superseded="hayır"),
        bad(beklenen_belgeler=[]),  # cevaplanabilir ama beklenen belge yok
        [QUESTIONS[4] | {"beklenen_belgeler": ["D01"]}],  # cevaplanamaz ama belge var
        [QUESTIONS[0], QUESTIONS[0]],  # yinelenen id
    ],
)
def test_gecersiz_soru_dosyasi_hata_ve_istek_yok(env, capsys, questions):
    write_questions(env.questions, questions)

    code = run(env)

    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert env.voyage.calls == []
    assert not env.out.exists()


def test_soru_dosyasi_yoksa_ya_da_json_degilse_hata(env, tmp_path, capsys):
    env.questions = tmp_path / "yok.json"
    assert run(env) == 1

    env.questions.write_text("{bozuk", encoding="utf-8")
    assert run(env) == 1

    assert capsys.readouterr().err.count("Hata:") == 2
    assert env.voyage.calls == []


def test_gercek_soru_dosyasi_gecerli():
    questions = load_script().load_questions(REPO_ROOT / "eval" / "kaynakli_sorulari.json")

    assert len(questions) == 10
    assert {q["cevaplanabilir"] for q in questions} == {True, False}
