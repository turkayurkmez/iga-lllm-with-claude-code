"""RAG arama yöntemlerini karşılaştırır (docs/hibrit.md › Ölçüt).

`eval/arama_sorulari.json`'daki soruları bm25, vector, hybrid ve hybrid + priority
ile koşar, soru tipi başına recall@5 ve ilk sıra doğruluğunu tablo olarak basar,
ayrıntıyı `eval/out/` altına yazar (var olan dosyanın üzerine yazılmaz).

ÜCRETLİ: sorular tek Voyage isteğiyle gömülür (bm25 gömme istemez ama vector ve
hybrid ister). Vektörler `data/sorgu_onbellegi.json`'a yazılır, aynı sorular
tekrar gömülmez. İndeksi değiştirmez; indeks `scripts/rag_indeksle.py` ile kurulur.

Kullanım (repo kökünden):
    $env:PYTHONIOENCODING="utf-8"; python scripts/rag_karsilastir.py
    python scripts/rag_karsilastir.py --out eval/out/ikinci.json
"""

import argparse
import json
import sys
from math import ceil
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.rag import embed, search
from backend.rag.index import INDEX_DIR, META_FILE

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = ROOT / "eval" / "arama_sorulari.json"
DEFAULT_OUT = ROOT / "eval" / "out" / "arama_karsilastirma.json"
TOP_K = 5

# (soru tipi, tablo başlığı); tablodaki sütun sırası budur.
TYPES = (
    ("kelime", "Kelime"),
    ("anlam", "Anlam"),
    ("capraz_dil", "Çapraz dil"),
    ("oncelik", "Öncelik"),
)
# (satır adı, method, priority)
ROWS = (
    ("bm25", "bm25", False),
    ("vector", "vector", False),
    ("hybrid", "hybrid", False),
    ("hybrid + priority", "hybrid", True),
)


class QuestionsError(Exception):
    """Soru dosyası okunamadı ya da geçersiz; mesaj `Hata:` ile yazılır."""


def load_questions(path: Path | str) -> list[dict]:
    try:
        questions = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QuestionsError(f"Soru dosyası okunamadı ({path}): {exc}") from None
    if not isinstance(questions, list) or not questions:
        raise QuestionsError("Soru dosyası boş olmayan bir liste olmalı.")
    known = {name for name, _ in TYPES}
    for position, question in enumerate(questions, start=1):
        label = f"{position}. soru"
        if not isinstance(question, dict):
            raise QuestionsError(f"{label} bir nesne değil.")
        text, kind = question.get("soru"), question.get("tip")
        expected = question.get("beklenen_belge")
        if not isinstance(text, str) or not text.strip():
            raise QuestionsError(f"{label}: 'soru' boş.")
        if kind not in known:
            raise QuestionsError(f"{label}: bilinmeyen tip {kind!r}.")
        if (
            not isinstance(expected, list)
            or not expected
            or not all(isinstance(doc, str) for doc in expected)
        ):
            raise QuestionsError(f"{label}: 'beklenen_belge' boş olmayan liste olmalı.")
        if kind == "oncelik" and not isinstance(question.get("ilk_beklenen"), str):
            raise QuestionsError(f"{label}: oncelik sorusunda 'ilk_beklenen' gerekli.")
    return questions


class _CachedQueries:
    """`search()`'ün gömme isteğini önceden alınmış vektörlerle karşılar (istek yok)."""

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    def embed(self, texts, model, input_type):
        return SimpleNamespace(
            embeddings=[self.vectors[text] for text in texts], total_tokens=0
        )


def _doc_ids(results: list[dict]) -> list[str]:
    return list(dict.fromkeys(result["doc_id"] for result in results))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _cell(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def measure(questions: list[dict], found: dict[str, list[dict]]) -> dict:
    """Bir yöntemin recall@5 kırılımı ve ilk sıra sayısı; `found` soru id → sonuçlar."""
    recalls: dict[str, list[float]] = {name: [] for name, _ in TYPES}
    first_hits = first_total = 0
    for question in questions:
        results = found[question["id"]]
        expected = question["beklenen_belge"]
        seen = set(_doc_ids(results))
        recalls[question["tip"]].append(len(seen & set(expected)) / len(expected))
        if question["tip"] == "oncelik":
            first_total += 1
            first_hits += bool(results) and results[0]["doc_id"] == question[
                "ilk_beklenen"
            ]
    row = {name: _mean(values) for name, values in recalls.items()}
    row["tumu"] = _mean([value for values in recalls.values() for value in values])
    row["ilk_sira_dogru"] = f"{first_hits}/{first_total}" if first_total else "-"
    return row


def render_table(rows: list[dict]) -> list[str]:
    header = ["Yöntem", *(title for _, title in TYPES), "Tümü", "İlk sıra doğru"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for row in rows:
        cells = [f"`{row['yontem']}`"]
        cells += [_cell(row[name]) for name, _ in TYPES]
        cells += [_cell(row["tumu"]), row["ilk_sira_dogru"]]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _check_index(index_dir: str, first_question: str, model: str) -> None:
    """Ücretli istekten önce: indeks hazır mı, modeli ayarlı modelle aynı mı."""
    search.search(first_question, k=1, method="bm25", index_dir=index_dir)
    indexed = json.loads((Path(index_dir) / META_FILE).read_text(encoding="utf-8"))
    if indexed["model"] != model:
        raise search.IndexModelMismatchError(
            f"İndeks '{indexed['model']}' modeliyle kurulmuş, ayarlı model "
            f"'{model}'. İndeksi yeniden kurun."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Arama yöntemlerini karşılaştırır (ücretli: tek gömme isteği)."
    )
    parser.add_argument("--sorular", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--indeks", default=str(INDEX_DIR), help="İndeks klasörü.")
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), help="Sonuç dosyası; var olan yazılmaz."
    )
    args = parser.parse_args(argv)
    out = Path(args.out)

    try:
        questions = load_questions(args.sorular)
        if out.exists():
            raise QuestionsError(
                f"Sonuç dosyası zaten var ({out}); başka bir --out verin."
            )
        model = embed.embed_model()
        _check_index(args.indeks, questions[0]["soru"], model)
        texts = [question["soru"] for question in questions]
        queries = embed.embed_queries(texts, model=model)
        client = _CachedQueries(dict(zip(texts, queries.vectors, strict=True)))

        rows, details = [], {}
        for name, method, priority in ROWS:
            found = {
                question["id"]: search.search(
                    question["soru"],
                    k=TOP_K,
                    method=method,
                    priority=priority,
                    index_dir=args.indeks,
                    client=client,
                    model=model,
                )
                for question in questions
            }
            rows.append({"yontem": name, **measure(questions, found)})
            details[name] = {
                question_id: [result["chunk_id"] for result in results]
                for question_id, results in found.items()
            }

        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {"model": model, "k": TOP_K, "satirlar": rows, "sonuclar": details},
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
    except (
        QuestionsError,
        search.IndexNotReadyError,
        search.IndexModelMismatchError,
        embed.EmbedConfigError,
        embed.EmbedError,
        OSError,
    ) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    unique = len(set(texts))
    requests = ceil(queries.fetched / embed.BATCH_SIZE)
    print(
        f"Gömme: {unique} sorgu, {requests} istek "
        f"(önbellekten {unique - queries.fetched}).",
        file=sys.stderr,
    )
    print(f"Sonuç: {out}", file=sys.stderr)
    print("\n".join(render_table(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
