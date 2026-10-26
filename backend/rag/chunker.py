"""Yapıya duyarlı parçalayıcı (docs/rag.md §3).

Belgeyi başlıklara göre böler; bölümü paragraf sınırlarından paketler. Tablo ve
numaralı prosedür bölünmez, hemen öncesindeki tanıtıcı paragrafla birlikte kalır.
Örtüşme yoktur. Çıktı deterministiktir (saat, rastgelelik, `set` sırası yok).

Docs'ta açık olmayan iki karar:
- `section` yolu `##` ve `###` başlıklarından kurulur; `#` belge başlığıdır ve
  `context`'te `title` olarak zaten vardır. Bölümde `##` yoksa `#` başlığı kullanılır.
- Tek cümle sınırı aşarsa bölünmez (daha küçük bir sınır yok).
"""

import re
from dataclasses import dataclass

from backend.rag.loader import CorpusError, Document

MAX_CHARS = 1200
MAX_HEADING_LEVEL = 3
HEADING = re.compile(r"^(#+)\s+(.*\S)\s*$")
NUMBERED = re.compile(r"^\d+\.\s")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
SEPARATOR = "\n\n"


@dataclass(frozen=True)
class _Atom:
    """Paketlenen en küçük birim. `whole` ise (tablo, prosedür) bölünmez."""

    text: str
    whole: bool


def _section_path(headings: dict[int, str], fallback: str) -> str:
    inner = [headings[level] for level in sorted(headings) if level >= 2]
    if inner:
        return " > ".join(inner)
    return headings.get(1, fallback)


def _sections(doc: Document) -> list[tuple[str, list[str]]]:
    """Gövdeyi (bölüm yolu, satırlar) çiftlerine ayırır; her başlık yeni bölüm açar."""
    sections: list[tuple[str, list[str]]] = [(doc.metadata["title"], [])]
    headings: dict[int, str] = {}
    for line in doc.body.split("\n"):
        match = HEADING.match(line)
        if match is None:
            sections[-1][1].append(line)
            continue
        level = len(match.group(1))
        if level > MAX_HEADING_LEVEL:
            raise CorpusError(
                f"{doc.doc_id}: başlık seviyesi en çok ### olabilir: {line!r}"
            )
        headings = {k: v for k, v in headings.items() if k < level}
        headings[level] = match.group(2)
        sections.append((_section_path(headings, doc.metadata["title"]), []))
    return sections


def _blocks(lines: list[str]) -> list[tuple[str, str]]:
    """Satırları ("para" | "table" | "list", metin) bloklarına ayırır."""
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("|"):
            start = i
            while i < len(lines) and lines[i].startswith("|"):
                i += 1
            blocks.append(("table", "\n".join(lines[start:i])))
        elif NUMBERED.match(line):
            start = end = i
            while i < len(lines):
                if NUMBERED.match(lines[i]):
                    end = i + 1
                elif lines[i].strip():
                    break
                i += 1
            blocks.append(("list", "\n".join(lines[start:end])))
            i = end
        else:
            start = i
            while (
                i < len(lines)
                and lines[i].strip()
                and not lines[i].startswith("|")
                and not NUMBERED.match(lines[i])
            ):
                i += 1
            blocks.append(("para", "\n".join(lines[start:i])))
    return blocks


def _atoms(lines: list[str]) -> list[_Atom]:
    atoms: list[_Atom] = []
    for kind, text in _blocks(lines):
        if kind == "para":
            atoms.append(_Atom(text, whole=False))
        elif atoms and not atoms[-1].whole:
            # Hemen öncesindeki paragraf tanıtıcıdır; tabloyla/prosedürle birleşir.
            atoms[-1] = _Atom(f"{atoms[-1].text}{SEPARATOR}{text}", whole=True)
        else:
            atoms.append(_Atom(text, whole=True))
    return atoms


def _split_sentences(paragraph: str) -> list[str]:
    """Sınırı aşan paragrafı cümle sınırlarından, sınırı aşmayan parçalara böler."""
    pieces: list[str] = []
    current = ""
    for sentence in SENTENCE_END.split(paragraph):
        if current and len(current) + 1 + len(sentence) > MAX_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    pieces.append(current)
    return pieces


def _pack(atoms: list[_Atom]) -> list[str]:
    """Birimleri sırayla, sınırı aşmayacak şekilde parçalara paketler."""
    units: list[str] = []
    for atom in atoms:
        if atom.whole or len(atom.text) <= MAX_CHARS:
            units.append(atom.text)
        else:
            units.extend(_split_sentences(atom.text))
    texts: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        extra = len(unit) + (len(SEPARATOR) if current else 0)
        if current and size + extra > MAX_CHARS:
            texts.append(SEPARATOR.join(current))
            current, size, extra = [], 0, len(unit)
        current.append(unit)
        size += extra
    if current:
        texts.append(SEPARATOR.join(current))
    return texts


def chunk_document(doc: Document) -> list[dict[str, str]]:
    """Belgeyi parçalara böler; her parça front matter alanlarını aynen taşır."""
    chunks: list[dict[str, str]] = []
    for section, lines in _sections(doc):
        for text in _pack(_atoms(lines)):
            chunks.append(
                {
                    **doc.metadata,
                    "chunk_id": f"{doc.doc_id}#{len(chunks) + 1:02d}",
                    "section": section,
                    "text": text,
                    "context": f"[{doc.doc_id} · {doc.metadata['title']} · {section}]",
                }
            )
    return chunks


def chunk_corpus(documents: list[Document]) -> list[dict[str, str]]:
    """Belgeleri verilen sırayla parçalar ve parça listelerini art arda koyar."""
    return [chunk for doc in documents for chunk in chunk_document(doc)]


def embedding_text(chunk: dict[str, str]) -> str:
    """Gömülecek metin: `context`, bir satır sonu, `text` (§3 madde 8)."""
    return f"{chunk['context']}\n{chunk['text']}"
