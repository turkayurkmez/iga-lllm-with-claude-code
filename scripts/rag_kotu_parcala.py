"""EĞİTİM DEMOSU: kötü chunking. Kurala bakmadan sabit 800 karakterlik parçalar.

Başlık, paragraf, tablo ve numaralı adım sınırları yok sayılır; metin ortasından
kesilir. Amaç, docs/rag.md §3'teki kuralların neden gerektiğini göstermek. Gerçek
hat bu script'i kullanmaz.

Kullanım:
    python scripts/rag_kotu_parcala.py            # belge başına parça sayısı
    python scripts/rag_kotu_parcala.py D05        # D05'in parçaları
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag.loader import CorpusError, load_corpus

CHUNK_SIZE = 800


def naive_chunks(body: str, size: int = CHUNK_SIZE) -> list[str]:
    """Metni hiçbir kurala bakmadan `size` karakterlik dilimlere böler."""
    return [body[i : i + size] for i in range(0, len(body), size)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sabit 800 karakterlik kötü chunking demosu."
    )
    parser.add_argument(
        "belge",
        nargs="?",
        help="Parçaları gösterilecek belge adı (ör. D05); verilmezse sayılar listelenir.",
    )
    args = parser.parse_args(argv)

    try:
        documents = load_corpus()
    except CorpusError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    if args.belge is None:
        total = 0
        print(f"{'Belge':<6} {'Karakter':>9} {'Parça':>6}  Başlık")
        for doc in documents:
            count = len(naive_chunks(doc.body))
            total += count
            title = doc.metadata["title"]
            print(f"{doc.doc_id:<6} {len(doc.body):>9} {count:>6}  {title}")
        print(f"Toplam: {len(documents)} belge, {total} parça")
        return 0

    wanted = args.belge.strip().upper().removesuffix(".MD")
    doc = next((d for d in documents if d.doc_id.upper() == wanted), None)
    if doc is None:
        known = ", ".join(d.doc_id for d in documents)
        print(
            f"Hata: belge bulunamadı: {args.belge} (var olanlar: {known})",
            file=sys.stderr,
        )
        return 1

    chunks = naive_chunks(doc.body)
    print(f"{doc.doc_id} · {doc.metadata['title']} — {len(chunks)} parça")
    for number, chunk in enumerate(chunks, start=1):
        print(f"\n=== {doc.doc_id}#{number:02d} ({len(chunk)} karakter) ===")
        print(chunk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
