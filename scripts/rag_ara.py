"""RAG indeksinde komut satırından arama (docs/rag.md §6, docs/hibrit.md).

`--method vector` (varsayılan) ve `hybrid` soruyu gömmek için gerçek Voyage çağrısı
yapar (ücretli, soru başına tek istek); `bm25` gömme yapmaz, `.env` istemez.
İndeksi değiştirmez. İndeks `scripts/rag_indeksle.py` ile kurulur.

Kullanım (repo kökünden):
    $env:PYTHONIOENCODING="utf-8"; python scripts/rag_ara.py "pist kapanış prosedürü"
    python scripts/rag_ara.py "TK2345 gecikme" --method bm25
    python scripts/rag_ara.py "soru" -k 3 --status active --language tr
    python scripts/rag_ara.py "soru" --type procedure --doc-id D05
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.embed import EmbedConfigError, EmbedError
from backend.rag.index import INDEX_DIR
from backend.rag.search import (
    DEFAULT_K,
    METHODS,
    IndexModelMismatchError,
    IndexNotReadyError,
    search,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAG indeksinde arama (ücretli).")
    parser.add_argument("soru", help="Aranacak soru.")
    parser.add_argument("-k", type=int, default=DEFAULT_K, help="Sonuç sayısı.")
    parser.add_argument("--status", help="Filtre: active ya da superseded.")
    parser.add_argument("--language", help="Filtre: tr ya da en.")
    parser.add_argument("--type", help="Filtre: belge türü.")
    parser.add_argument("--doc-id", help="Filtre: belge kimliği (ör. D05).")
    parser.add_argument(
        "--method",
        choices=METHODS,
        default="vector",
        help="Arama yöntemi; bm25 gömme (Voyage) ayarı istemez.",
    )
    parser.add_argument("--indeks", default=str(INDEX_DIR), help="İndeks klasörü.")
    args = parser.parse_args(argv)

    try:
        results = search(
            args.soru,
            k=args.k,
            status=args.status,
            language=args.language,
            type=args.type,
            doc_id=args.doc_id,
            method=args.method,
            index_dir=args.indeks,
        )
    except (
        IndexNotReadyError,
        IndexModelMismatchError,
        EmbedConfigError,
        EmbedError,
        ValueError,
    ) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    if not results:
        print("Sonuç yok.")
        return 0
    for number, result in enumerate(results, start=1):
        print(
            f"{number}. {result['score']:.4f}  {result['chunk_id']}  "
            f"r{result['revision']} {result['status']} {result['language']}  "
            f"{result['section']}"
        )
        print(f"   {result['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
