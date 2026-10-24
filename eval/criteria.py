"""Golden set ölçütleri (docs/eval.md › Ölçütler, Metne çevirme, Eşleşme).

Koşum başına ölçütler evaluate ile, koşum listesinin özeti summarize ile çıkar.
Değer referansları önceden çözülmüş gelir (eval.expected); bu modül hesap yapmaz,
model çağırmaz, dosya okumaz.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

PASSED, FAILED, NOT_APPLICABLE = "geçti", "kaldı", "uygulanmaz"
CRITERIA = ("durum", "tool", "arguman", "deger", "uydurmama", "netlestirme")

LOCAL_TZ = timezone(timedelta(hours=3))

# Önünde/arkasında harf ya da rakam olmayan yer ([^\W_] = Unicode harf/rakam).
_BEFORE = r"(?<![^\W_])"
_AFTER = r"(?![^\W_])"


def render(ref, value):
    """Değeri metinde aranacak yazımlara çevirir; ilk yazım raporda kullanılır."""
    if "literal" in ref:
        return [value]
    if isinstance(value, bool):
        raise TypeError(f"Metne çevrilemeyen değer: {value!r}.")
    if isinstance(value, int):
        return [str(value)]
    if isinstance(value, float):
        text = str(value)
        return [text, text.replace(".", ",")]
    if isinstance(value, str):
        return [_hhmm(value) or value]
    raise TypeError(f"Metne çevrilemeyen değer: {value!r}.")


def _hhmm(value):
    if "T" not in value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(LOCAL_TZ).strftime("%H:%M")


def _turkish_lower(text):
    return text.replace("İ", "i").replace("I", "ı").lower()


def _found(ref, rendered, text):
    if "literal" in ref and not re.search(r"\d", rendered):
        # Rakamsız anahtar sözcük: harf duyarsız, Türkçe ek için sağ sınır aranmaz.
        pattern = _BEFORE + re.escape(_turkish_lower(rendered))
        return re.search(pattern, _turkish_lower(text)) is not None
    return re.search(_BEFORE + re.escape(rendered) + _AFTER, text) is not None


def _items(value):
    return value if isinstance(value, list) else [value]


def _scan(pairs, text, *, want_found):
    """(ref, değer) çiftlerinden bulunma durumu want_found olan yazımları döndürür."""
    hits = []
    for ref, value in pairs:
        for item in _items(value):
            alternatives = render(ref, item)
            found = any(_found(ref, alt, text) for alt in alternatives)
            if found is want_found:
                hits.append(alternatives[0])
    return hits


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _executed_calls(result):
    return [
        call
        for turn in result["turns"]
        for call in turn["tool_calls"]
        if call["executed"]
    ]


def _verdict(ok):
    return PASSED if ok else FAILED


def evaluate(question, expect, forbid, result):
    """Bir koşumun ölçütleri.

    expect ve forbid [(ref, çözülmüş değer)] listesidir; literal ref'te değer metnin
    kendisidir. result AgentResult.model_dump() biçimindedir.
    """
    text = result["text"]
    done = result["status"] == "tamam"
    calls = _executed_calls(result)
    executed = {(call["name"], _canonical(call["input"])) for call in calls}

    missing = _scan(expect, text, want_found=False)
    found_forbidden = _scan(forbid, text, want_found=True)

    criteria = {
        "durum": _verdict(done),
        "tool": _verdict({call["name"] for call in calls} == set(question["tools"])),
        "arguman": NOT_APPLICABLE,
        "deger": NOT_APPLICABLE,
        "uydurmama": NOT_APPLICABLE,
        "netlestirme": NOT_APPLICABLE,
    }
    if question.get("args"):
        criteria["arguman"] = _verdict(
            all(
                (arg["name"], _canonical(arg["input"])) in executed
                for arg in question["args"]
            )
        )
    if expect:
        criteria["deger"] = _verdict(done and not missing)
    if forbid:
        criteria["uydurmama"] = _verdict(done and not found_forbidden)
    if question.get("asks"):
        criteria["netlestirme"] = _verdict(done and "?" in text)

    return {
        "criteria": criteria,
        "missing": missing,
        "found_forbidden": found_forbidden,
        "passed": all(v != FAILED for v in criteria.values()),
    }


def _rate(passed, total):
    return {
        "passed": passed,
        "total": total,
        "ratio": passed / total if total else None,
    }


def summarize(runs):
    """Golden skor, ölçüt başına oran, category skoru ve kararlı soru sayısı."""
    per_criterion = {name: [0, 0] for name in CRITERIA}
    per_category = defaultdict(lambda: [0, 0])
    per_question = defaultdict(list)
    for run in runs:
        for name, verdict in run["criteria"].items():
            if verdict != NOT_APPLICABLE:
                per_criterion[name][0] += verdict == PASSED
                per_criterion[name][1] += 1
        per_category[run["category"]][0] += run["passed"]
        per_category[run["category"]][1] += 1
        per_question[run["id"]].append(run["passed"])

    passed = sum(run["passed"] for run in runs)
    return {
        "score": _rate(passed, len(runs)),
        "criteria": {name: _rate(*per_criterion[name]) for name in CRITERIA},
        "categories": {
            name: _rate(*per_category[name]) for name in sorted(per_category)
        },
        "stable": {
            "stable": sum(all(results) for results in per_question.values()),
            "questions": len(per_question),
        },
    }
