"""scripts/rag_ara.py sözleşmesi. Ağa çıkmaz; Voyage istemcisi sahtedir."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.rag import embed

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rag_ara.py"
MODEL = "sahte-model"


def chunk(chunk_id, doc_id, status, language, type_, text):
    return {
        "doc_id": doc_id,
        "title": f"Belge {doc_id}",
        "type": type_,
        "authority": "Kurgusal Makam",
        "airport": "XXXX",
        "language": language,
        "revision": "2",
        "effective_from": "2025-03-01",
        "status": status,
        "chunk_id": chunk_id,
        "section": "Bölüm",
        "text": text,
        "context": f"[{doc_id}]",
    }


CHUNKS = [
    chunk("D01#01", "D01", "active", "tr", "manual", "Birinci metin."),
    chunk("D02#01", "D02", "superseded", "tr", "procedure", "İkinci metin."),
    chunk("D03#01", "D03", "active", "en", "manual", "Third text."),
]
VECTORS = [[1.0, 0.0], [0.6, 0.8], [0.0, 1.0]]


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail

    def embed(self, texts, model, input_type):
        if self.fail:
            raise RuntimeError("sır: anahtar-123")
        return SimpleNamespace(embeddings=[[1.0, 0.0]] * len(texts), total_tokens=1)


def load_script():
    assert SCRIPT.exists(), "scripts/rag_ara.py yok"
    spec = importlib.util.spec_from_file_location("rag_ara", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def index_dir(tmp_path, monkeypatch):
    directory = tmp_path / "indeks"
    directory.mkdir()
    (directory / "chunks.json").write_text(
        json.dumps(CHUNKS, ensure_ascii=False), encoding="utf-8"
    )
    np.save(directory / "vektorler.npy", np.asarray(VECTORS, dtype=np.float32))
    (directory / "meta.json").write_text(
        json.dumps({"model": MODEL, "dimension": 2, "chunk_count": 3}),
        encoding="utf-8",
    )
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.setenv("VOYAGE_API_KEY", "anahtar-123")
    monkeypatch.setenv("COPILOT_EMBED_MODEL", MODEL)
    monkeypatch.setattr(embed, "_make_client", lambda key: FakeClient())
    return directory


def run(module, index_dir, *args):
    return module.main(["soru", "--indeks", str(index_dir), *args])


def test_sonuclar_skor_sirasiyla_basilir(index_dir, capsys):
    code = run(load_script(), index_dir)

    out = capsys.readouterr().out
    assert code == 0
    assert out.index("D01#01") < out.index("D02#01") < out.index("D03#01")
    assert "1.0000" in out
    assert "Birinci metin." in out


def test_k_sonuc_sayisini_sinirlar(index_dir, capsys):
    run(load_script(), index_dir, "-k", "1")

    out = capsys.readouterr().out
    assert "D01#01" in out
    assert "D02#01" not in out


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (["--status", "superseded"], "D02#01"),
        (["--language", "en"], "D03#01"),
        (["--type", "procedure"], "D02#01"),
        (["--doc-id", "D03"], "D03#01"),
    ],
)
def test_filtre_bayraklari(index_dir, capsys, flags, expected):
    code = run(load_script(), index_dir, *flags)

    out = capsys.readouterr().out
    assert code == 0
    assert expected in out
    assert "D01#01" not in out


def test_sonuc_yoksa_mesaj_ve_0(index_dir, capsys):
    code = run(load_script(), index_dir, "--doc-id", "D99")

    assert code == 0
    assert "Sonuç yok." in capsys.readouterr().out


def test_indeks_yoksa_hata_ve_1(tmp_path, index_dir, capsys):
    code = run(load_script(), tmp_path / "yok")

    assert code == 1
    assert capsys.readouterr().err.startswith("Hata:")


def test_model_uyusmazligi_hata_ve_1(index_dir, monkeypatch, capsys):
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "baska-model")

    code = run(load_script(), index_dir)

    assert code == 1
    assert "baska-model" in capsys.readouterr().err


def test_eksik_anahtar_hata_ve_1(index_dir, monkeypatch, capsys):
    monkeypatch.delenv("VOYAGE_API_KEY")

    code = run(load_script(), index_dir)

    assert code == 1
    assert "VOYAGE_API_KEY" in capsys.readouterr().err


def test_gomme_hatasi_ayrinti_sizdirmaz(index_dir, monkeypatch, capsys):
    monkeypatch.setattr(embed, "_make_client", lambda key: FakeClient(fail=True))

    code = run(load_script(), index_dir)

    err = capsys.readouterr().err
    assert code == 1
    assert err.startswith("Hata:")
    assert "anahtar-123" not in err


def test_gecersiz_k_hata_ve_1(index_dir, capsys):
    code = run(load_script(), index_dir, "-k", "0")

    assert code == 1
    assert capsys.readouterr().err.startswith("Hata:")


def test_arguman_yoksa_systemexit_2():
    with pytest.raises(SystemExit) as info:
        load_script().main([])

    assert info.value.code == 2
