"""Arama (docs/rag.md §6, docs/hibrit.md): vektör, BM25 ve hibrit (RRF).

Vektör araması soruyu gömer, parçaları iç çarpımla sıralar; BM25 gömme gerektirmez.
Filtreler sıralamadan önce uygulanır. Skor eşiği yoktur; yalnızca okur, indeksi
değiştirmez. İndeks yoksa ya da modeli `.env`'dekinden farklıysa gömme çağrısı
yapılmadan reddedilir. Modele parça göndermez (M5.3).
"""

import json
from pathlib import Path

import numpy as np

from backend.rag import bm25
from backend.rag.embed import embed_model, embed_query
from backend.rag.index import CHUNKS_FILE, INDEX_DIR, META_FILE, VECTORS_FILE

DEFAULT_K = 5
METHODS = ("vector", "bm25", "hybrid")
RRF_CANDIDATES = 20
RRF_K = 60
FILTER_FIELDS = ("status", "language", "type", "doc_id")
RESULT_FIELDS = ("chunk_id", "doc_id", "revision", "status", "language", "section")


class IndexNotReadyError(RuntimeError):
    """İndeks yok, eksik ya da okunamıyor (§7: INDEX_NOT_READY)."""

    code = "INDEX_NOT_READY"


class IndexModelMismatchError(RuntimeError):
    """İndeksin modeli `.env`'dekinden farklı (§7: INDEX_MODEL_MISMATCH)."""

    code = "INDEX_MODEL_MISMATCH"


def _load_index(index_dir: Path) -> tuple[dict, list[dict], np.ndarray]:
    names = (META_FILE, CHUNKS_FILE, VECTORS_FILE)
    missing = [n for n in names if not (index_dir / n).is_file()]
    if missing:
        raise IndexNotReadyError(
            f"İndeks hazır değil ({index_dir}): eksik dosya: {', '.join(missing)}. "
            "scripts/rag_indeksle.py ile kurun."
        )
    try:
        meta = json.loads((index_dir / META_FILE).read_text(encoding="utf-8"))
        chunks = json.loads((index_dir / CHUNKS_FILE).read_text(encoding="utf-8"))
        vectors = np.load(index_dir / VECTORS_FILE, allow_pickle=False)
        model = meta["model"]
    except (OSError, ValueError, KeyError, TypeError):
        raise IndexNotReadyError(
            f"İndeks okunamadı ({index_dir}); scripts/rag_indeksle.py ile yeniden kurun."
        ) from None
    if vectors.ndim != 2 or len(vectors) != len(chunks) or not isinstance(model, str):
        raise IndexNotReadyError(
            f"İndeks tutarsız ({index_dir}); scripts/rag_indeksle.py ile yeniden kurun."
        )
    return meta, chunks, vectors


def _fuse(
    vector_ranked: list[tuple[float, int]],
    bm25_ranked: list[tuple[float, int]],
    rrf_k: int,
    chunk_id,
) -> list[tuple[float, int]]:
    """RRF: `Σ 1 / (rrf_k + sıra)`, sıra 1'den başlar; listede olmayan terim eklemez.

    Eşit skorda vektör sırası önce gelir; vektör listesinde olmayanlar sona ve
    kendi aralarında `chunk_id` artan kalır.
    """
    fused: dict[int, float] = {}
    vector_rank: dict[int, int] = {}
    for rank, (_, index) in enumerate(vector_ranked, start=1):
        fused[index] = fused.get(index, 0.0) + 1 / (rrf_k + rank)
        vector_rank[index] = rank
    for rank, (_, index) in enumerate(bm25_ranked, start=1):
        fused[index] = fused.get(index, 0.0) + 1 / (rrf_k + rank)
    return sorted(
        ((score, index) for index, score in fused.items()),
        key=lambda pair: (
            -pair[0],
            vector_rank.get(pair[1], len(vector_ranked) + 1),
            chunk_id(pair[1]),
        ),
    )


def search(
    query: str,
    k: int = DEFAULT_K,
    status: str | None = None,
    language: str | None = None,
    type: str | None = None,
    doc_id: str | None = None,
    index_dir: Path | str | None = None,
    client=None,
    model: str | None = None,
    method: str = "vector",
    rrf_candidates: int = RRF_CANDIDATES,
    rrf_k: int = RRF_K,
) -> list[dict]:
    """En iyi `k` parçayı döndürür: skor azalan, eşitlikte `chunk_id` artan.

    `method="vector"` (varsayılan) ve `"hybrid"`: `model` verilmezse
    `COPILOT_EMBED_MODEL` okunur ve indeksin modeliyle karşılaştırılır.
    `method="bm25"`: gömme çağrısı yapmaz, model ve `client` kullanılmaz.
    `"hybrid"`: iki yöntemin ilk `rrf_candidates` adayı RRF ile birleşir
    (docs/hibrit.md). `index_dir` verilmezse `INDEX_DIR` çağrı anında okunur
    (testler modül değişkenini değiştirebilsin diye varsayılan burada bağlanmaz).
    """
    if not query.strip():
        raise ValueError("Soru metni boş olamaz.")
    if k < 1:
        raise ValueError("k en az 1 olmalı.")
    if rrf_candidates < 1:
        raise ValueError("rrf_candidates en az 1 olmalı.")
    if rrf_k < 0:
        raise ValueError("rrf_k negatif olamaz.")
    if method not in METHODS:
        raise ValueError(
            f"Bilinmeyen arama yöntemi '{method}'; geçerli: {', '.join(METHODS)}."
        )

    meta, chunks, vectors = _load_index(
        Path(INDEX_DIR if index_dir is None else index_dir)
    )
    if method != "bm25":
        expected = model if model is not None else embed_model()
        if meta["model"] != expected:
            raise IndexModelMismatchError(
                f"İndeks '{meta['model']}' modeliyle kurulmuş, ayarlı model "
                f"'{expected}'. İndeksi yeniden kurun."
            )

    wanted = {
        "status": status,
        "language": language,
        "type": type,
        "doc_id": doc_id,
    }
    candidates = [
        i
        for i, chunk in enumerate(chunks)
        if all(value is None or chunk.get(f) == value for f, value in wanted.items())
    ]
    if not candidates:
        return []

    def by_score_then_id(pairs: list[tuple[float, int]]) -> list[tuple[float, int]]:
        return sorted(pairs, key=lambda pair: (-pair[0], chunks[pair[1]]["chunk_id"]))

    if method != "bm25":
        query_vector = np.asarray(
            embed_query(query, client=client, model=expected), dtype=np.float64
        )
        scores = vectors[candidates].astype(np.float64) @ query_vector
        vector_ranked = by_score_then_id(
            list(zip(scores.tolist(), candidates, strict=True))
        )
    if method != "vector":
        by_index = bm25.score(query, [chunk["text"] for chunk in chunks], candidates)
        bm25_ranked = by_score_then_id([(v, i) for i, v in by_index.items()])

    if method == "vector":
        ranked = vector_ranked
    elif method == "bm25":
        ranked = bm25_ranked
    else:
        ranked = _fuse(
            vector_ranked[:rrf_candidates],
            bm25_ranked[:rrf_candidates],
            rrf_k,
            lambda i: chunks[i]["chunk_id"],
        )
    return [
        {
            "score": score,
            **{field: chunks[i][field] for field in RESULT_FIELDS},
            "text": chunks[i]["text"],
        }
        for score, i in ranked[:k]
    ]
