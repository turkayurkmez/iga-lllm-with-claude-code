"""Korpus okuyucu sözleşmesi (docs/rag.md §2). API'siz, gerçek korpusa dokunmaz."""

import importlib.util

import pytest

from backend.rag import loader
from backend.rag.loader import CorpusError, load_corpus, load_document

STAMP = loader.STAMP

VALID = f"""---
doc_id: D99
title: Deneme Belgesi
type: manual
authority: Kurgusal Makam
airport: XXXX
language: tr
revision: 2
effective_from: 2025-03-01
status: active
supersedes: D98
---
{STAMP}

# Başlık

Gövde metni.

{STAMP}
"""


def write(tmp_path, text, name="D99.md"):
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def test_modul_var():
    assert importlib.util.find_spec("backend.rag.loader") is not None


def test_gecerli_belge_okunur(tmp_path):
    doc = load_document(write(tmp_path, VALID))
    assert doc.doc_id == "D99"
    assert doc.metadata["title"] == "Deneme Belgesi"
    assert doc.metadata["supersedes"] == "D98"
    assert doc.metadata["revision"] == "2"


def test_damga_govdeye_girmez(tmp_path):
    doc = load_document(write(tmp_path, VALID))
    assert doc.body == "# Başlık\n\nGövde metni."
    assert "KURGUSAL" not in doc.body


def test_crlf_normallestirilir(tmp_path):
    doc = load_document(write(tmp_path, VALID.replace("\n", "\r\n")))
    assert "\r" not in doc.body
    assert doc.metadata["status"] == "active"


@pytest.mark.parametrize("key", loader.REQUIRED_KEYS)
def test_zorunlu_anahtar_eksikse_hata(tmp_path, key):
    text = "\n".join(
        line for line in VALID.split("\n") if not line.startswith(f"{key}:")
    )
    with pytest.raises(CorpusError, match=key):
        load_document(write(tmp_path, text))


@pytest.mark.parametrize(
    ("eski", "yeni", "parca"),
    [
        ("language: tr", "language: de", "language"),
        ("status: active", "status: draft", "status"),
        ("effective_from: 2025-03-01", "effective_from: 2025-13-01", "effective_from"),
        ("effective_from: 2025-03-01", "effective_from: 1.3.2025", "effective_from"),
        ("doc_id: D99", "doc_id: D98", "doc_id"),
    ],
)
def test_gecersiz_deger_hata(tmp_path, eski, yeni, parca):
    with pytest.raises(CorpusError, match=parca):
        load_document(write(tmp_path, VALID.replace(eski, yeni)))


def test_front_matter_yoksa_hata(tmp_path):
    with pytest.raises(CorpusError, match="front matter"):
        load_document(write(tmp_path, VALID.split("---\n", 2)[2]))


def test_front_matter_kapanmazsa_hata(tmp_path):
    with pytest.raises(CorpusError, match="kapanmıyor"):
        load_document(write(tmp_path, "---\ndoc_id: D99\n"))


def test_tekrarlanan_anahtar_hata(tmp_path):
    with pytest.raises(CorpusError, match="tekrarlanmış"):
        load_document(write(tmp_path, VALID.replace("---\nd", "---\ntitle: X\nd", 1)))


def test_damga_eksikse_hata(tmp_path):
    text = VALID.rstrip().removesuffix(STAMP)
    with pytest.raises(CorpusError, match="damga"):
        load_document(write(tmp_path, text))


def test_bom_reddedilir(tmp_path):
    path = tmp_path / "D99.md"
    path.write_bytes(b"\xef\xbb\xbf" + VALID.encode("utf-8"))
    with pytest.raises(CorpusError, match="BOM"):
        load_document(path)


def test_korpus_doc_id_sirasiyla_okunur(tmp_path):
    write(tmp_path, VALID.replace("D99", "D02"), "D02.md")
    write(tmp_path, VALID.replace("D99", "D01"), "D01.md")
    assert [d.doc_id for d in load_corpus(tmp_path)] == ["D01", "D02"]


def test_bos_ya_da_olmayan_klasor_hata(tmp_path):
    with pytest.raises(CorpusError, match="belge yok"):
        load_corpus(tmp_path)
    with pytest.raises(CorpusError, match="bulunamadı"):
        load_corpus(tmp_path / "yok")


def test_gercek_korpus_okunur():
    documents = load_corpus()
    assert len(documents) == 15
    assert all(d.body and "KURGUSAL —" not in d.body for d in documents)
