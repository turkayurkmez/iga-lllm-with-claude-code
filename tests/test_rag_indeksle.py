"""scripts/rag_indeksle.py sözleşmesi. Ağa çıkmaz; Voyage istemcisi sahtedir."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.rag import embed

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rag_indeksle.py"
STAMP = "**KURGUSAL — EĞİTİM AMAÇLI**"
DOC = f"""---
doc_id: D01
title: Deneme
type: manual
authority: Kurgusal Makam
airport: XXXX
language: tr
revision: 1
effective_from: 2025-03-01
status: active
---
{STAMP}

# Deneme

## Giriş

Gövde metni.

{STAMP}
"""


class ServerError(Exception):
    http_status = 500


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail

    def embed(self, texts, model, input_type):
        if self.fail:
            raise ServerError("sır: anahtar-123")
        return SimpleNamespace(
            embeddings=[[1.0, 2.0] for _ in texts], total_tokens=7 * len(texts)
        )


def load_script():
    assert SCRIPT.exists(), "scripts/rag_indeksle.py yok"
    spec = importlib.util.spec_from_file_location("rag_indeksle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def paths(tmp_path, monkeypatch):
    corpus = tmp_path / "korpus"
    corpus.mkdir()
    (corpus / "D01.md").write_bytes(DOC.encode("utf-8"))
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.setenv("VOYAGE_API_KEY", "anahtar-123")
    monkeypatch.setenv("COPILOT_EMBED_MODEL", "sahte-model")
    monkeypatch.setattr(embed, "_make_client", lambda key: FakeClient())
    return SimpleNamespace(corpus=corpus, index=tmp_path / "data" / "indeks")


def run(module, paths):
    return module.main(["--korpus", str(paths.corpus), "--indeks", str(paths.index)])


def test_basarili_kurulum_ozet_basar(paths, capsys):
    module = load_script()

    code = run(module, paths)

    out = capsys.readouterr().out
    assert code == 0
    assert "sahte-model" in out
    assert "1 parça" in out
    assert "boyut 2" in out
    assert sorted(p.name for p in paths.index.iterdir()) == [
        "chunks.json",
        "meta.json",
        "vektorler.npy",
    ]


def test_gomme_hatasi_hata_satiri_ve_1_doner(paths, monkeypatch, capsys):
    module = load_script()
    monkeypatch.setattr(embed, "_make_client", lambda key: FakeClient(fail=True))

    code = run(module, paths)

    err = capsys.readouterr().err
    assert code == 1
    assert err.startswith("Hata:")
    assert "anahtar-123" not in err
    assert not paths.index.exists()


def test_eksik_ayar_hata_satiri_ve_1_doner(paths, monkeypatch, capsys):
    module = load_script()
    monkeypatch.delenv("VOYAGE_API_KEY")

    code = run(module, paths)

    err = capsys.readouterr().err
    assert code == 1
    assert "Hata:" in err
    assert "VOYAGE_API_KEY" in err
    assert not paths.index.exists()


def test_bozuk_korpus_hata_satiri_ve_1_doner(paths, capsys):
    module = load_script()
    (paths.corpus / "D02.md").write_text("front matter yok\n", encoding="utf-8")

    code = run(module, paths)

    assert code == 1
    assert capsys.readouterr().err.startswith("Hata:")
    assert not paths.index.exists()


def test_hatada_eski_indeks_bozulmaz(paths, monkeypatch):
    module = load_script()
    assert run(module, paths) == 0
    before = {p.name: p.read_bytes() for p in paths.index.iterdir()}
    monkeypatch.setattr(embed, "_make_client", lambda key: FakeClient(fail=True))

    assert run(module, paths) == 1

    assert {p.name: p.read_bytes() for p in paths.index.iterdir()} == before


def test_gecersiz_arguman_systemexit_2(paths):
    module = load_script()

    with pytest.raises(SystemExit) as info:
        module.main(["--bilinmeyen"])

    assert info.value.code == 2
