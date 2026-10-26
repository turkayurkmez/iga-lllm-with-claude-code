"""Korpus okuyucu (docs/rag.md §2): front matter + gövde, doğrulamalı.

Yalnızca okur ve doğrular; parçalama (§3) bu modülde yoktur. Korpusa yazmaz,
`.env` okumaz, ağa çıkmaz.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[2] / "data" / "korpus"
STAMP = "**KURGUSAL — EĞİTİM AMAÇLI**"
REQUIRED_KEYS = (
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
LANGUAGES = ("tr", "en")
STATUSES = ("active", "superseded")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CorpusError(ValueError):
    """Belge ya da korpus docs/rag.md §2 biçimine uymuyor."""


@dataclass(frozen=True)
class Document:
    """Okunmuş bir belge: front matter alanları ve damgasız gövde."""

    doc_id: str
    metadata: dict[str, str]
    body: str
    path: Path


def _fail(path: Path, message: str) -> CorpusError:
    return CorpusError(f"{path.name}: {message}")


def _split_front_matter(path: Path, lines: list[str]) -> tuple[dict[str, str], int]:
    """Front matter sözlüğünü ve gövdenin başladığı satır numarasını döndürür."""
    if not lines or lines[0] != "---":
        raise _fail(path, "dosya `---` satırıyla başlamalı (front matter yok)")
    metadata: dict[str, str] = {}
    for number, line in enumerate(lines[1:], start=1):
        if line == "---":
            return metadata, number + 1
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not KEY_PATTERN.match(key):
            raise _fail(path, f"front matter satırı `anahtar: değer` değil: {line!r}")
        if key in metadata:
            raise _fail(path, f"front matter anahtarı tekrarlanmış: {key}")
        metadata[key] = value
    raise _fail(path, "front matter kapanmıyor (ikinci `---` yok)")


def _validate(path: Path, metadata: dict[str, str]) -> None:
    for key in REQUIRED_KEYS:
        if not metadata.get(key):
            raise _fail(path, f"zorunlu anahtar eksik ya da boş: {key}")
    if metadata["doc_id"] != path.stem:
        raise _fail(
            path, f"doc_id ({metadata['doc_id']}) dosya adıyla ({path.stem}) uyuşmuyor"
        )
    if metadata["language"] not in LANGUAGES:
        raise _fail(path, f"language {LANGUAGES} içinde olmalı: {metadata['language']}")
    if metadata["status"] not in STATUSES:
        raise _fail(path, f"status {STATUSES} içinde olmalı: {metadata['status']}")
    effective = metadata["effective_from"]
    try:
        if not DATE_PATTERN.match(effective):
            raise ValueError(effective)
        date.fromisoformat(effective)
    except ValueError:
        raise _fail(path, f"effective_from YYYY-MM-DD olmalı: {effective}") from None


def _strip_stamp(path: Path, body_lines: list[str]) -> str:
    """Gövdenin ilk ve son satırındaki damgayı çıkarır; damga yoksa hata verir."""
    lines = list(body_lines)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2 or lines[0] != STAMP or lines[-1] != STAMP:
        raise _fail(path, f"gövdenin ilk ve son satırı {STAMP} damgası olmalı")
    return "\n".join(lines[1:-1]).strip()


def load_document(path: Path | str) -> Document:
    """Tek belgeyi okur ve doğrular; biçim bozuksa `CorpusError` fırlatır."""
    path = Path(path)
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _fail(path, "dosya BOM'suz UTF-8 olmalı")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail(path, "dosya UTF-8 değil") from None
    lines = text.replace("\r\n", "\n").removesuffix("\n").split("\n")
    metadata, body_start = _split_front_matter(path, lines)
    _validate(path, metadata)
    body = _strip_stamp(path, lines[body_start:])
    return Document(doc_id=metadata["doc_id"], metadata=metadata, body=body, path=path)


def load_corpus(directory: Path | str = CORPUS_DIR) -> list[Document]:
    """Klasördeki tüm `*.md` belgelerini `doc_id` sırasıyla okur."""
    directory = Path(directory)
    if not directory.is_dir():
        raise CorpusError(f"korpus klasörü bulunamadı: {directory}")
    documents = [load_document(p) for p in sorted(directory.glob("*.md"))]
    if not documents:
        raise CorpusError(f"korpus klasöründe belge yok: {directory}")
    return sorted(documents, key=lambda d: d.doc_id)
