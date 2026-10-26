"""Yapıya duyarlı parçalayıcı sözleşmesi (docs/rag.md §3). API'siz, ağsız.

Gerçek korpus testleri `data/korpus`'u okur; korpusta 1200'ü aşan düz paragraf
olmadığı için uzun paragraf ve cümle bölme kuralları sentetik belgelerle sınanır.
"""

import re
from pathlib import Path

import pytest

from backend.rag.chunker import MAX_CHARS, chunk_corpus, chunk_document, embedding_text
from backend.rag.loader import CorpusError, Document, load_corpus

FRONT_MATTER_KEYS = (
    "doc_id",
    "title",
    "type",
    "authority",
    "airport",
    "language",
    "revision",
    "effective_from",
    "status",
)
HEADING = re.compile(r"^#{1,3}\s")
NUMBERED = re.compile(r"^\d+\.\s")


@pytest.fixture(scope="module")
def docs():
    return load_corpus()


@pytest.fixture(scope="module")
def chunks(docs):
    return chunk_corpus(docs)


def by_doc(chunks, doc_id):
    return [c for c in chunks if c["doc_id"] == doc_id]


def has_table(chunk):
    return any(line.startswith("|") for line in chunk["text"].split("\n"))


def has_numbered(chunk):
    return any(NUMBERED.match(line) for line in chunk["text"].split("\n"))


def make_doc(body, doc_id="D99", title="Deneme Belgesi"):
    metadata = {
        "doc_id": doc_id,
        "title": title,
        "type": "manual",
        "authority": "Kurgusal Makam",
        "airport": "XXXX",
        "language": "tr",
        "revision": "1",
        "effective_from": "2025-03-01",
        "status": "active",
    }
    return Document(
        doc_id=doc_id, metadata=metadata, body=body, path=Path(f"{doc_id}.md")
    )


def words(label, length):
    """`length` karakterlik, noktayla biten, rakamsız düz metin."""
    text = (label + " ") * (length // (len(label) + 1) + 1)
    return text[: length - 1].rstrip() + "."


# --- Gerçek korpus ---------------------------------------------------------


def test_korpus_parca_uretir(docs, chunks):
    assert len(docs) == 15
    assert len(chunks) >= len(docs)
    assert {c["doc_id"] for c in chunks} == {d.doc_id for d in docs}


def test_her_parca_front_matter_alanlarini_aynen_tasir(docs, chunks):
    metadata = {d.doc_id: d.metadata for d in docs}
    assert chunks
    for chunk in chunks:
        for key, value in metadata[chunk["doc_id"]].items():
            assert chunk[key] == value, (chunk["chunk_id"], key)
        for key in ("chunk_id", "section", "text", "context"):
            assert chunk[key], (chunk["chunk_id"], key)


def test_supersedes_gibi_ek_alanlar_da_tasinir(chunks):
    d03 = by_doc(chunks, "D03")
    assert d03
    assert all(c["supersedes"] == "D02" for c in d03)
    assert all("supersedes" not in c for c in by_doc(chunks, "D01"))


def test_chunk_id_belge_icinde_iki_haneli_ardisik(docs, chunks):
    for doc in docs:
        ids = [c["chunk_id"] for c in by_doc(chunks, doc.doc_id)]
        assert ids, doc.doc_id
        assert ids == [f"{doc.doc_id}#{n:02d}" for n in range(1, len(ids) + 1)]


def test_context_bicimi(chunks):
    assert chunks
    for chunk in chunks:
        expected = f"[{chunk['doc_id']} · {chunk['title']} · {chunk['section']}]"
        assert chunk["context"] == expected


def test_text_damga_ve_baslik_icermez(chunks):
    assert chunks
    for chunk in chunks:
        assert "KURGUSAL —" not in chunk["text"]
        for line in chunk["text"].split("\n"):
            assert not HEADING.match(line), (chunk["chunk_id"], line)
        assert chunk["text"] == chunk["text"].strip()


def test_ayni_belge_iki_kez_bolununce_ayni_sonuc(docs):
    first = chunk_corpus(docs)
    second = chunk_corpus(load_corpus())
    assert first
    assert first == second


def test_icerik_kaybolmaz_ve_cakismaz(docs, chunks):
    """Başlık dışındaki tüm satırlar, sırayla ve tam bir kez parçalarda bulunur."""
    for doc in docs:
        expected = [
            line
            for line in doc.body.split("\n")
            if line.strip() and not HEADING.match(line)
        ]
        got = [
            line
            for chunk in by_doc(chunks, doc.doc_id)
            for line in chunk["text"].split("\n")
            if line.strip()
        ]
        assert got == expected, doc.doc_id


def test_sinir_yalniz_tablo_ve_prosedur_parcalarinda_asilir(chunks):
    assert chunks
    for chunk in chunks:
        if not (has_table(chunk) or has_numbered(chunk)):
            assert len(chunk["text"]) <= MAX_CHARS, chunk["chunk_id"]
    over = [c for c in chunks if len(c["text"]) > MAX_CHARS]
    assert {c["doc_id"] for c in over} == {"D04", "D05"}


def test_d01_basliklara_gore_yedi_parca(chunks):
    d01 = by_doc(chunks, "D01")
    assert [c["section"] for c in d01] == [
        "1. Amaç ve kapsam",
        "2. Stand grupları",
        "3. Kod harfi uygunluğu > 3.1 A grubu",
        "3. Kod harfi uygunluğu > 3.2 B grubu",
        "3. Kod harfi uygunluğu > 3.3 Kod E uçaklar",
        "4. Tahsis öncelikleri",
        "5. Yeniden tahsis",
    ]


def test_d04_tablo_tek_parcada_tanitici_paragrafla(docs, chunks):
    body = next(d.body for d in docs if d.doc_id == "D04")
    table_lines = [line for line in body.split("\n") if line.startswith("|")]
    assert len(table_lines) == 14
    holders = [c for c in by_doc(chunks, "D04") if has_table(c)]
    assert len(holders) == 1
    holder = holders[0]
    assert holder["section"] == "4. Holdover süreleri"
    assert len(holder["text"]) > MAX_CHARS
    text_lines = holder["text"].split("\n")
    assert [line for line in text_lines if line.startswith("|")] == table_lines
    assert holder["text"].startswith("Holdover süresi, sıvı uygulamasının")
    assert "Aşağıdaki tablo" in holder["text"].split("\n\n")[0]
    assert holder["text"].split("\n\n")[1] == "\n".join(table_lines)


def test_d05_numarali_prosedur_tek_parcada(docs, chunks):
    body = next(d.body for d in docs if d.doc_id == "D05")
    steps = [line for line in body.split("\n") if NUMBERED.match(line)]
    assert len(steps) == 7
    holders = [c for c in by_doc(chunks, "D05") if has_numbered(c)]
    assert len(holders) == 1
    holder = holders[0]
    assert holder["section"] == "3. Arıza anında uygulanacak adımlar"
    assert len(holder["text"]) > MAX_CHARS
    assert [x for x in holder["text"].split("\n") if NUMBERED.match(x)] == steps
    assert holder["text"].startswith("Arıza bildirildiğinde aşağıdaki adımlar")


def test_d12_tablo_tek_parcada_ve_sinirin_altinda(docs, chunks):
    body = next(d.body for d in docs if d.doc_id == "D12")
    table_lines = [line for line in body.split("\n") if line.startswith("|")]
    assert len(table_lines) == 7
    holders = [c for c in by_doc(chunks, "D12") if has_table(c)]
    assert len(holders) == 1
    lines = holders[0]["text"].split("\n")
    assert [line for line in lines if line.startswith("|")] == table_lines
    assert holders[0]["text"].startswith("The table below lists")


def test_embedding_text_context_satir_sonu_text(chunks):
    assert chunks
    for chunk in chunks:
        assert embedding_text(chunk) == f"{chunk['context']}\n{chunk['text']}"


# --- Sentetik belgeler -----------------------------------------------------


def test_kisa_bolum_tek_parca_kalir():
    body = (
        "# Başlık\n\n## 1. Bölüm\n\nİlk paragraf.\n\n"
        "Tablo aşağıdadır.\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    )
    result = chunk_document(make_doc(body))
    assert len(result) == 1
    assert result[0]["text"] == (
        "İlk paragraf.\n\nTablo aşağıdadır.\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    )


def test_bos_govdeli_baslik_parca_uretmez():
    body = "# Başlık\n\n## 1. Boş\n\n## 2. Dolu\n\nMetin."
    result = chunk_document(make_doc(body))
    assert [c["section"] for c in result] == ["2. Dolu"]
    assert result[0]["chunk_id"] == "D99#01"


def test_baslik_yolu_ve_seviye_sifirlama():
    body = "# T\n\n## A\n\nBir.\n\n### B\n\nİki.\n\n## C\n\nÜç."
    result = chunk_document(make_doc(body))
    assert [c["section"] for c in result] == ["A", "A > B", "C"]


def test_yalniz_ana_baslik_altindaki_metin_ana_basligi_bolum_alir():
    result = chunk_document(make_doc("# Tek Başlık\n\nMetin."))
    assert [c["section"] for c in result] == ["Tek Başlık"]


def test_dorduncu_seviye_baslik_hata():
    with pytest.raises(CorpusError, match="####"):
        chunk_document(make_doc("# T\n\n## A\n\n#### Derin\n\nMetin."))


def test_uzun_bolum_paragraf_sinirindan_bolunur():
    paragraphs = [words(f"paragraf{n}", 400) for n in "abcde"]
    body = "# T\n\n## A\n\n" + "\n\n".join(paragraphs)
    result = chunk_document(make_doc(body))
    assert len(result) >= 2
    assert all(len(c["text"]) <= MAX_CHARS for c in result)
    assert all(c["section"] == "A" for c in result)
    assert [c["chunk_id"] for c in result] == [
        f"D99#{n:02d}" for n in range(1, len(result) + 1)
    ]
    rebuilt = [p for c in result for p in c["text"].split("\n\n")]
    assert rebuilt == paragraphs


def test_uzun_paragraf_cumle_sinirindan_bolunur():
    sentences = [words(f"cümle{n}", 90) for n in "abcdefghijklmnopqrst"]
    paragraph = " ".join(sentences)
    assert len(paragraph) > MAX_CHARS
    result = chunk_document(make_doc(f"# T\n\n## A\n\n{paragraph}"))
    assert len(result) >= 2
    for chunk in result:
        assert len(chunk["text"]) <= MAX_CHARS
        assert chunk["text"].endswith(".")
    assert " ".join(c["text"] for c in result) == paragraph


def test_tek_cumle_sinirdan_uzunsa_bolunmez():
    sentence = words("uzun", MAX_CHARS + 300)
    result = chunk_document(make_doc(f"# T\n\n## A\n\n{sentence}"))
    assert [c["text"] for c in result] == [sentence]


def test_buyuk_tablo_bolunmez_oncesindeki_ilgisiz_paragraf_ayri_kalir():
    unrelated = words("ilgisiz", 300)
    intro = words("tanitici", 100)
    rows = [f"| satır{n:02d} | {words('hücre', 60)} |" for n in range(25)]
    table = "\n".join(["| a | b |", "|---|---|", *rows])
    assert len(table) > MAX_CHARS
    body = f"# T\n\n## A\n\n{unrelated}\n\n{intro}\n\n{table}"
    result = chunk_document(make_doc(body))
    assert [c["text"] for c in result] == [unrelated, f"{intro}\n\n{table}"]


def test_tablodan_sonraki_paragraf_tabloya_eklenmez_sinir_asilirsa():
    rows = [f"| satır{n:02d} | {words('hücre', 60)} |" for n in range(25)]
    table = "\n".join(["| a | b |", "|---|---|", *rows])
    after = words("sonra", 200)
    result = chunk_document(make_doc(f"# T\n\n## A\n\n{table}\n\n{after}"))
    assert [c["text"] for c in result] == [table, after]


def test_prosedur_bos_satirlarla_ayrilsa_da_tek_parca():
    steps = [f"{n}. {words(f'adım{n}', 380)}" for n in range(1, 5)]
    body = "# T\n\n## A\n\nAdımlar şunlardır.\n\n" + "\n\n".join(steps)
    result = chunk_document(make_doc(body))
    assert len(result) == 1
    assert len(result[0]["text"]) > MAX_CHARS
    assert [x for x in result[0]["text"].split("\n") if NUMBERED.match(x)] == steps


def test_chunk_corpus_belgeleri_sirayla_birlestirir():
    first = make_doc("# T\n\n## A\n\nBir.", doc_id="D01")
    second = make_doc("# T\n\n## A\n\nİki.", doc_id="D02")
    result = chunk_corpus([first, second])
    assert [c["chunk_id"] for c in result] == ["D01#01", "D02#01"]
