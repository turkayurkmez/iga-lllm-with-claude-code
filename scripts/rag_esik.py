"""Kaynaklı cevap eşiğini ölçer (docs/kaynakli.md › Eşik).

`eval/kaynakli_sorulari.json`'daki her soru için `vector` yöntemiyle en yüksek
vektör puanını (iç çarpım) bulur; cevaplanabilir ve cevaplanamaz soruları ayrı
kategorilerde, en düşük ve en yüksek puanlarıyla özetler. İki kategori ayrışıyorsa
`COPILOT_RAG_ESIK` için seçilebilecek aralığı söyler. `include_superseded: false`
sorularda yalnızca `status: active` parçalar aranır (tool'un varsayılanı).

ÜCRETLİ: sorgular tek Voyage isteğiyle gömülür. Vektörler `rag_karsilastir.py`
ile ortak `data/sorgu_onbellegi.json`'a (anahtar: model + sorgu metni) yazılır,
önbellekteki sorgu tekrar gömülmez. İndeksi değiştirmez; ayrıntı `eval/out/`'a
yazılır (var olan dosyanın üzerine yazılmaz).

Kullanım (repo kökünden):
    $env:PYTHONIOENCODING="utf-8"; python scripts/rag_esik.py
    python scripts/rag_esik.py --out eval/out/ikinci_esik.json
"""

import argparse
import json
import sys
from math import ceil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag_karsilastir import _CachedQueries, _check_index

from backend.rag import embed, search
from backend.rag.index import INDEX_DIR

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_QUESTIONS = ROOT / "eval" / "kaynakli_sorulari.json"
DEFAULT_OUT = ROOT / "eval" / "out" / "kaynakli_esik.json"
ANSWERABLE, UNANSWERABLE = "cevaplanabilir", "cevaplanamaz"
CATEGORIES = (ANSWERABLE, UNANSWERABLE)


class QuestionsError(Exception):
    """Soru dosyası okunamadı ya da geçersiz; mesaj `Hata:` ile yazılır."""


def load_questions(path: Path | str) -> list[dict]:
    try:
        questions = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QuestionsError(f"Soru dosyası okunamadı ({path}): {exc}") from None
    if not isinstance(questions, list) or not questions:
        raise QuestionsError("Soru dosyası boş olmayan bir liste olmalı.")
    seen = set()
    for position, question in enumerate(questions, start=1):
        label = f"{position}. soru"
        if not isinstance(question, dict):
            raise QuestionsError(f"{label} bir nesne değil.")
        text, answerable = question.get("soru"), question.get("cevaplanabilir")
        expected = question.get("beklenen_belgeler")
        if not isinstance(question.get("id"), str) or question["id"] in seen:
            raise QuestionsError(f"{label}: 'id' metin olmalı ve tekrar etmemeli.")
        seen.add(question["id"])
        if not isinstance(text, str) or not text.strip():
            raise QuestionsError(f"{label}: 'soru' boş.")
        if not isinstance(answerable, bool):
            raise QuestionsError(f"{label}: 'cevaplanabilir' true/false olmalı.")
        if not isinstance(question.get("include_superseded"), bool):
            raise QuestionsError(f"{label}: 'include_superseded' true/false olmalı.")
        if not isinstance(expected, list) or not all(
            isinstance(doc, str) for doc in expected
        ):
            raise QuestionsError(f"{label}: 'beklenen_belgeler' liste olmalı.")
        if answerable != bool(expected):
            raise QuestionsError(
                f"{label}: cevaplanabilir soruda beklenen belge olmalı, "
                "cevaplanamaz soruda olmamalı."
            )
    return questions


def _fmt(value: float | None) -> str:
    # `+ 0.0` "-0.0000" yazılmasını önler.
    return "-" if value is None else f"{value + 0.0:.4f}"


def summarize(rows: list[dict]) -> dict[str, dict]:
    summary = {}
    for category in CATEGORIES:
        scores = [
            row["puan"]
            for row in rows
            if row["kategori"] == category and row["puan"] is not None
        ]
        summary[category] = {
            "soru_sayisi": sum(1 for row in rows if row["kategori"] == category),
            "en_dusuk": min(scores, default=None),
            "en_yuksek": max(scores, default=None),
        }
    return summary


def gap_line(summary: dict[str, dict]) -> str | None:
    low = summary[ANSWERABLE]["en_dusuk"]
    high = summary[UNANSWERABLE]["en_yuksek"]
    if low is None or high is None:
        return None
    if high < low:
        return (
            f"Ayrım: cevaplanamaz en yüksek {_fmt(high)} < cevaplanabilir en düşük "
            f"{_fmt(low)}; eşik ({_fmt(high)}, {_fmt(low)}] aralığında seçilebilir."
        )
    return (
        f"Çakışma: cevaplanamaz en yüksek {_fmt(high)} >= cevaplanabilir en düşük "
        f"{_fmt(low)}; tek bir vektör eşiği ikisini ayıramaz."
    )


def render(rows: list[dict], summary: dict[str, dict]) -> list[str]:
    lines = [
        "| Soru | Kategori | En yüksek vektör puanı | Parça | Beklenen belgede |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        hit = {True: "evet", False: "hayır", None: "-"}[row["beklenen_belgede"]]
        lines.append(
            f"| {row['id']} | {row['kategori']} | {_fmt(row['puan'])} | "
            f"{row['chunk_id'] or '-'} | {hit} |"
        )
    lines += ["", "| Kategori | Soru sayısı | En düşük | En yüksek |", "|---|---|---|---|"]
    for category in CATEGORIES:
        stats = summary[category]
        lines.append(
            f"| {category} | {stats['soru_sayisi']} | {_fmt(stats['en_dusuk'])} | "
            f"{_fmt(stats['en_yuksek'])} |"
        )
    line = gap_line(summary)
    if line:
        lines += ["", line]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Kaynaklı cevap eşiğini ölçer (ücretli: tek gömme isteği)."
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
        texts = list(dict.fromkeys(question["soru"] for question in questions))
        queries = embed.embed_queries(texts, model=model)
        client = _CachedQueries(dict(zip(texts, queries.vectors, strict=True)))

        rows = []
        for question in questions:
            filters = {} if question["include_superseded"] else {"status": "active"}
            results = search.search(
                question["soru"],
                k=1,
                method="vector",
                index_dir=args.indeks,
                client=client,
                model=model,
                **filters,
            )
            top = results[0] if results else None
            answerable = question["cevaplanabilir"]
            rows.append(
                {
                    "id": question["id"],
                    "kategori": ANSWERABLE if answerable else UNANSWERABLE,
                    "include_superseded": question["include_superseded"],
                    "puan": top["score"] if top else None,
                    "chunk_id": top["chunk_id"] if top else None,
                    "doc_id": top["doc_id"] if top else None,
                    "beklenen_belgede": (
                        top is not None
                        and top["doc_id"] in question["beklenen_belgeler"]
                        if answerable
                        else None
                    ),
                }
            )
        summary = summarize(rows)

        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {"model": model, "sorular": rows, "kategoriler": summary},
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

    requests = ceil(queries.fetched / embed.BATCH_SIZE)
    print(
        f"Gömme: {len(texts)} sorgu, {requests} istek "
        f"(önbellekten {len(texts) - queries.fetched}).",
        file=sys.stderr,
    )
    print(f"Sonuç: {out}", file=sys.stderr)
    print("\n".join(render(rows, summary)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
