"""scripts/rag_kotu_parcala.py: sabit 800 karakterlik kötü chunking demosu."""

import importlib.util
from pathlib import Path

from backend.rag.loader import load_corpus

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "rag_kotu_parcala.py"


def load_script():
    assert SCRIPT.exists()
    spec = importlib.util.spec_from_file_location("rag_kotu_parcala", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parcalar_sabit_800_karakter():
    script = load_script()
    chunks = script.naive_chunks("a" * 1700)
    assert [len(c) for c in chunks] == [800, 800, 100]
    assert "".join(chunks) == "a" * 1700


def test_bos_metin_parca_vermez():
    assert load_script().naive_chunks("") == []


def test_liste_her_belgeyi_sayar(capsys):
    script = load_script()
    assert script.main([]) == 0
    out = capsys.readouterr().out
    documents = load_corpus()
    assert len(documents) == 15
    for doc in documents:
        assert doc.doc_id in out
    total = sum(len(script.naive_chunks(d.body)) for d in documents)
    assert f"Toplam: 15 belge, {total} parça" in out


def test_belge_adi_parcalari_gosterir(capsys):
    script = load_script()
    doc = load_corpus()[0]
    expected = script.naive_chunks(doc.body)
    assert script.main([doc.doc_id.lower()]) == 0
    out = capsys.readouterr().out
    assert f"{len(expected)} parça" in out
    assert f"=== {doc.doc_id}#01 (" in out
    assert f"=== {doc.doc_id}#{len(expected):02d} (" in out
    assert expected[0] in out


def test_bilinmeyen_belge_hata_verir(capsys):
    assert load_script().main(["D99"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Hata:")
