"""search_documents: korpusta kaynaklı arama (sözleşme: docs/kaynakli.md).

`search.search()` ile hibrit arar, eşiği ham vektör puanına (`vector_score`)
uygular ve parçaları belge/sürüm bilgisiyle zenginleştirir. Skor modele gitmez.
Arama altyapısı hataları (indeks, model, gömme, eşik ayarı) `DataError` olur; zarfı
run_tool kurar. Tool zarf kurmaz ve sistem saatini okumaz.
"""

from backend.envelope import ErrorCode
from backend.rag import embed, search
from backend.tools._ortak import DataError

SOURCE = "data/korpus"
METHOD = "hybrid"
LIMIT = 5
LIMIT_SUPERSEDED = 8

NOT_FOUND = {
    "code": ErrorCode.NOT_FOUND,
    "message": "Belgelerde bu konuda kaynak bulunamadı.",
}


def _item(result: dict, chunk: dict, replaced_by: dict[str, str]) -> dict:
    """Arama sonucunu ve parçanın belge bilgilerini sözleşmedeki alanlara çevirir."""
    item = {
        "chunk_id": result["chunk_id"],
        "doc_id": result["doc_id"],
        "title": chunk["title"],
        "section": result["section"],
        "revision": result["revision"],
        "effective_from": chunk["effective_from"],
        "status": result["status"],
    }
    # Kaynakta olmayan alan yazılmaz (docs/zarf.md › Eksik alan hata değildir).
    if chunk.get("supersedes"):
        item["supersedes"] = chunk["supersedes"]
    if result["doc_id"] in replaced_by:
        item["superseded_by"] = replaced_by[result["doc_id"]]
    item["authority"] = chunk["authority"]
    item["priority_level"] = search.TYPE_LEVELS.get(chunk["type"], 1)
    item["language"] = result["language"]
    item["text"] = result["text"]
    return item


def search_documents(query: str, include_superseded: bool = False) -> dict:
    try:
        threshold = search.rag_threshold()
        results = search.search(
            query,
            k=LIMIT_SUPERSEDED if include_superseded else LIMIT,
            method=METHOD,
            **({} if include_superseded else {"status": "active"}),
        )
        chunks = search.load_chunks() if results else []
    except (
        search.IndexNotReadyError,
        search.IndexModelMismatchError,
        embed.EmbedConfigError,
        embed.EmbedError,
    ) as exc:
        raise DataError(f"Belge araması kullanılamadı: {type(exc).__name__}") from exc

    if not results or max(r["vector_score"] for r in results) < threshold:
        return {"value": None, "source": SOURCE, "error": NOT_FOUND}

    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    replaced_by = {c["supersedes"]: c["doc_id"] for c in chunks if c.get("supersedes")}
    value = [_item(r, by_id[r["chunk_id"]], replaced_by) for r in results]
    return {"value": value, "source": SOURCE}
