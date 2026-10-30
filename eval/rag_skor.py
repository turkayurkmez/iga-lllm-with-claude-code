"""RAG skor hesabı (docs/rag_olcum.md).

Saf modül: ham kayıtlardan ve sorulardan skor ile Markdown rapor üretir. Ağa
çıkmaz, dosya okumaz/yazmaz, girdiyi değiştirmez. Sözleşme testleri
`tests/test_eval_rag_skor.py`'dedir.
"""

import re

RET_SENTENCE = "Belgelerde bu konuda kaynak bulamadım."
RECALL_K = 5

NOTES = (
    (
        "Cümle düzeyinde destek denetimi bu eğitimde ölçülmemiştir, "
        "sonraki adım olarak LLM ile notlama önerilir."
    ),
    (
        "Skor on soruda hesaplanmıştır; her cevaplanabilir soru recall'ı "
        "yaklaşık 14 puan oynatır. Küçük farklar değil belirgin düşüşler "
        "okunmalıdır."
    ),
)

_TAG = re.compile(r"\[[^\[\]#\s]+#\d+\]")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def classify(record):
    """Cevabı ret / cevap / belirsiz sınıflarından birine koyar."""
    has_ret = RET_SENTENCE in record["answer"]
    has_citation = bool(record["citations"])
    if has_ret and not has_citation:
        return "ret"
    if has_citation and not has_ret:
        return "cevap"
    return "belirsiz"


def _sentences(text):
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def _top_docs(record):
    """Her aramanın ilk beş sonucundaki belgelerin birleşimi."""
    docs = set()
    for search in record["searches"]:
        docs.update(search["doc_ids"][:RECALL_K])
    return docs


def _cited_docs(record):
    docs = []
    for c in record["citations"]:
        doc = c.get("doc_id")
        if c.get("dogrulandi") and doc and doc not in docs:
            docs.append(doc)
    return docs


def _superseded(record):
    return sum(
        1
        for c in record["citations"]
        if c.get("dogrulandi") and c.get("status") == "superseded"
    )


def score(records, questions):
    """Ham kayıtlardan beş metriği ve soru bazında satırları hesaplar."""
    by_id = {r["id"]: r for r in records}
    pairs = [(q, by_id[q["id"]]) for q in questions if q["id"] in by_id]

    per_question = {}
    classes = {}
    rows = []
    precision_ok = precision_total = 0
    old_target = old_expected = 0
    plain_sentences = total_sentences = 0
    unverified = total_citations = 0

    for q, rec in pairs:
        cls = classify(rec)
        classes[q["id"]] = cls
        answerable = q["cevaplanabilir"]
        expected = set(q["beklenen_belgeler"])

        recall_full = None
        if answerable:
            recall_full = bool(expected) and expected <= _top_docs(rec)
            per_question[q["id"]] = int(recall_full)
            for c in rec["citations"]:
                precision_total += 1
                if c.get("doc_id") in expected:
                    precision_ok += 1

        old = _superseded(rec)
        if q["include_superseded"]:
            old_expected += old
        else:
            old_target += old

        if cls != "ret":
            for sentence in _sentences(rec["answer"]):
                total_sentences += 1
                if not _TAG.search(sentence):
                    plain_sentences += 1
        total_citations += len(rec["citations"])
        unverified += sum(1 for c in rec["citations"] if not c.get("dogrulandi"))

        rows.append(
            {
                "id": q["id"],
                "recall_tam": recall_full,
                "ret_sinifi": cls,
                "belgeler": _cited_docs(rec),
                "eski_surum_atfi": old > 0,
            }
        )

    u_ids = [q["id"] for q, _ in pairs if not q["cevaplanabilir"]]
    s_ids = [q["id"] for q, _ in pairs if q["cevaplanabilir"]]
    return {
        "recall": {
            "hit": sum(per_question.values()),
            "total": len(per_question),
            "per_question": per_question,
        },
        "answerability": {
            "u_ret": sum(1 for i in u_ids if classes[i] == "ret"),
            "u_total": len(u_ids),
            "s_gereksiz_ret": sum(1 for i in s_ids if classes[i] == "ret"),
            "s_total": len(s_ids),
            "belirsiz": sum(1 for c in classes.values() if c == "belirsiz"),
            "classes": classes,
        },
        "citation_precision": {
            "dogru": precision_ok,
            "toplam": precision_total,
            "oran": precision_ok / precision_total if precision_total else None,
        },
        "eski_surum": {"hedef": old_target, "beklenen": old_expected},
        "atifsiz": {
            "atifsiz_cumle": plain_sentences,
            "toplam_cumle": total_sentences,
            "dogrulanamayan": unverified,
            "toplam_atif": total_citations,
        },
        "rows": rows,
    }


def _ratio(num, den):
    return f"{num}/{den}" + (f" ({num / den:.0%})" if den else " (-)")


def render(result):
    """`score` sonucunu Markdown rapora çevirir."""
    rc = result["recall"]
    an = result["answerability"]
    cp = result["citation_precision"]
    old = result["eski_surum"]
    at = result["atifsiz"]
    lines = [
        "# RAG skor raporu",
        "",
        "## Özet",
        "",
        "| Metrik | Değer |",
        "|---|---|",
        f"| recall@5 | {_ratio(rc['hit'], rc['total'])} |",
        (
            f"| Cevaplanabilirlik | U'da ret {an['u_ret']}/{an['u_total']}; "
            f"S'de gereksiz ret {an['s_gereksiz_ret']}/{an['s_total']}; "
            f"belirsiz {an['belirsiz']} |"
        ),
        f"| Citation precision | {_ratio(cp['dogru'], cp['toplam'])} |",
        (
            f"| Eski sürüm kullanımı | hedef 0: {old['hedef']}; "
            f"eski sürüm beklenen sorularda (skora girmez): {old['beklenen']} |"
        ),
        (
            "| atıfsız cümle / doğrulanamayan atıf oranı | "
            f"atıfsız cümle {_ratio(at['atifsiz_cumle'], at['toplam_cumle'])}; "
            f"doğrulanamayan atıf "
            f"{_ratio(at['dogrulanamayan'], at['toplam_atif'])} |"
        ),
        "",
        "## Sorular",
        "",
        "| Soru | Recall tam | Ret sınıfı | Atıf yapılan belgeler | Eski sürüm atfı |",
        "|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        recall = (
            "-"
            if row["recall_tam"] is None
            else ("evet" if row["recall_tam"] else "hayır")
        )
        docs = ", ".join(row["belgeler"]) or "-"
        old_cell = "var" if row["eski_surum_atfi"] else "yok"
        lines.append(
            f"| {row['id']} | {recall} | {row['ret_sinifi']} | {docs} | {old_cell} |"
        )
    lines += ["", *(f"- {note}" for note in NOTES), ""]
    return "\n".join(lines)
