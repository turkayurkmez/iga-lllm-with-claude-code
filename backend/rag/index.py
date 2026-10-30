"""İndeks kurucu (docs/rag.md §5): korpusu parçalar, gömer, `data/indeks/`e yazar.

Yazım iki aşamalıdır: önce her şey bellekte hazırlanır (okuma, parçalama, gömme);
gömme ya da korpus hatasında diske hiçbir şey yazılmaz. Sonra üç dosya yanındaki
geçici klasöre (`indeks.yeni`) yazılır ve klasör yeniden adlandırmayla yerine konur;
eski indeks yedeğe (`indeks.eski`) alınır, yer değiştirme düşerse geri getirilir.
Böylece okuyan hiçbir zaman yarım ya da karışık bir indeks görmez. Sistem saati
okunmaz; aynı korpus aynı baytları üretir.
"""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from time import sleep

import numpy as np

from backend import injection
from backend.rag.chunker import chunk_corpus, embedding_text
from backend.rag.embed import embed_documents
from backend.rag.loader import CORPUS_DIR, load_corpus

INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "indeks"
CHUNKS_FILE = "chunks.json"
VECTORS_FILE = "vektorler.npy"
META_FILE = "meta.json"
REPLACE_ATTEMPTS = 5
REPLACE_WAIT_SECONDS = 0.1


def corpus_sha256(directory: Path | str = CORPUS_DIR) -> str:
    """Korpus `*.md` dosyalarının (ad + bayt, ada göre sıralı) birleşik özeti."""
    digest = hashlib.sha256()
    for path in sorted(Path(directory).glob("*.md")):
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _write_json(path: Path, data) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _replace(src: Path, dst: Path) -> None:
    """`os.replace`; Windows'ta yeni yazılmış klasör kısa süre kilitli kalabilir."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            sleep(REPLACE_WAIT_SECONDS * (attempt + 1))


def _swap(staging: Path, index_dir: Path) -> None:
    """Hazır klasörü yerine koyar; eski indeks hata olursa geri gelir."""
    backup = index_dir.with_name(index_dir.name + ".eski")
    if backup.exists():
        shutil.rmtree(backup)
    had_old = index_dir.exists()
    if had_old:
        _replace(index_dir, backup)
    try:
        _replace(staging, index_dir)
    except BaseException:
        if had_old:
            _replace(backup, index_dir)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if had_old:
        # Yeni indeks yerinde; yedek silinemezse bir sonraki kurulum temizler.
        shutil.rmtree(backup, ignore_errors=True)


def build_index(
    corpus_dir: Path | str = CORPUS_DIR,
    index_dir: Path | str = INDEX_DIR,
    client=None,
    model: str | None = None,
    exceptions_path: Path | str = injection.EXCEPTIONS_FILE,
) -> dict:
    """İndeksi kurar ve `meta.json` içeriğini döndürür.

    Hata durumunda (`CorpusError`, `EmbedError`, `EmbedConfigError`, `OSError`)
    var olan indeks olduğu gibi kalır. `client`/`model` verilmezse gömme katmanı
    `.env`'den kurar (backend/rag/embed.py). Şüpheli parçalar (docs/enjeksiyon.md E3)
    indekse alınmaz; `meta["quarantined"]`'a yazılır, bulgu yoksa alan eklenmez.
    """
    corpus_dir, index_dir = Path(corpus_dir), Path(index_dir)

    chunks, quarantined = injection.filter_chunks(
        chunk_corpus(load_corpus(corpus_dir)),
        injection.load_exceptions(exceptions_path),
    )
    for item in quarantined:
        print(
            f"Uyarı: {item['chunk_id']} karantinada: {', '.join(item['codes'])}",
            file=sys.stderr,
        )
    if not chunks:
        raise ValueError("Tüm parçalar karantinaya alındı; indeks kurulmadı.")
    result = embed_documents(
        [embedding_text(chunk) for chunk in chunks], client=client, model=model
    )
    vectors = np.asarray(result.vectors, dtype=np.float32)
    if vectors.ndim != 2 or len(vectors) != len(chunks) or not len(chunks):
        raise ValueError("Gömme sonucu parça sayısıyla uyuşmuyor ya da boş.")

    meta = {
        "model": result.model,
        "dimension": int(vectors.shape[1]),
        "chunk_count": len(chunks),
        "corpus_sha256": corpus_sha256(corpus_dir),
        "total_tokens": result.total_tokens,
    }
    if meta["total_tokens"] is None:
        del meta["total_tokens"]
    if quarantined:
        meta["quarantined"] = quarantined

    staging = index_dir.with_name(index_dir.name + ".yeni")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        _write_json(staging / CHUNKS_FILE, chunks)
        np.save(staging / VECTORS_FILE, vectors, allow_pickle=False)
        _write_json(staging / META_FILE, meta)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _swap(staging, index_dir)
    return meta
