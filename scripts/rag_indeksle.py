"""RAG indeksini kurar (docs/rag.md §5): korpus → parça → gömme → data/indeks/.

UCRETLI: gerçek Voyage AI gömme çağrısı yapar (`VOYAGE_API_KEY`, `COPILOT_EMBED_MODEL`
.env'den). Gömme ya da korpus hatasında hiçbir şey yazılmaz, var olan indeks bozulmaz.
Gereksiz yere tekrar çalıştırmayın; korpus ve model değişmedikçe indeks aynı kalır.

Kullanım (repo kökünden):
    $env:PYTHONIOENCODING="utf-8"; python scripts/rag_indeksle.py
    python scripts/rag_indeksle.py --korpus data/korpus --indeks data/indeks
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.embed import EmbedConfigError, EmbedError
from backend.rag.index import INDEX_DIR, build_index
from backend.rag.loader import CORPUS_DIR, CorpusError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Korpusu parçalar, gömer ve indeks dosyalarını yazar (ücretli)."
    )
    parser.add_argument("--korpus", default=str(CORPUS_DIR), help="Korpus klasörü.")
    parser.add_argument("--indeks", default=str(INDEX_DIR), help="İndeks klasörü.")
    args = parser.parse_args(argv)

    try:
        meta = build_index(corpus_dir=args.korpus, index_dir=args.indeks)
    except (CorpusError, EmbedConfigError, EmbedError, OSError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(f"İndeks yazıldı: {args.indeks}")
    print(f"model: {meta['model']}")
    print(f"{meta['chunk_count']} parça, boyut {meta['dimension']}")
    if "total_tokens" in meta:
        print(f"toplam token: {meta['total_tokens']}")
    print(f"korpus özeti: {meta['corpus_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
