"""Golden set dosyasının doğrulaması (docs/eval.md › Soru biçimi, Kurallar).

validate(golden) hata metinlerinin listesini döndürür; boş liste geçerli demektir.
Hesap yapılmaz, veri okunmaz; hesap adlarının varlığı eval.expected'den alınır.
"""

import re

from eval.expected import CALC_NAMES

QUESTION_COUNT = 20
TOP_FIELDS = {"version", "now", "questions"}
REQUIRED = {"id", "category", "behavior", "question", "tools"}
OPTIONAL = {"slots", "corruption", "now", "args", "expect", "forbid", "asks"}
CATEGORIES = {"ozet", "ucus", "belirsizlik", "bozulma", "kapsam_disi"}
BEHAVIORS = {
    "cevap",
    "hesap_yok",
    "netlestirme",
    "bulunamadi",
    "eski_veri",
    "veride_yok",
    "veri_okunamadi",
    "kapsam_disi",
}
TOOL_NAMES = {"get_flight_summary", "resolve_flight_identity", "get_flight_details"}
SCENARIOS = {
    "stale_position",
    "duplicate_callsign",
    "missing_field",
    "undefined_flight",
}

# Rakam yalnızca bu anahtarların metin değerlerinde serbesttir (literal ayrıca).
DIGIT_KEYS = {"version", "id", "question", "flight_no", "query"}

_VERSION = re.compile(r"\d+\.\d+\.\d+")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def validate(golden):
    if not isinstance(golden, dict):
        return ["Golden set bir JSON nesnesi olmalı."]
    errors = []
    unknown = set(golden) - TOP_FIELDS
    if unknown:
        errors.append(f"Bilinmeyen üst alan: {', '.join(sorted(unknown))}.")
    version = golden.get("version")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        errors.append("version MAJOR.MINOR.PATCH biçiminde olmalı.")
    errors += [f"now: {e}" for e in _calc_ref_errors(golden.get("now"))]
    _scan_numbers(golden, "golden", errors, prefix="")

    questions = golden.get("questions")
    if not isinstance(questions, list):
        errors.append("questions bir liste olmalı.")
        return errors
    if len(questions) != QUESTION_COUNT:
        errors.append(f"Tam {QUESTION_COUNT} soru olmalı, {len(questions)} var.")
    ids = [q.get("id") if isinstance(q, dict) else None for q in questions]
    for id_ in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"{id_}: id tekil olmalı.")
    expected_ids = [f"G{n:02d}" for n in range(1, len(questions) + 1)]
    if ids != expected_ids and len(set(ids)) == len(ids):
        errors.append("Sorular G01'den başlayarak id sırasıyla dizilmeli.")
    for index, q in enumerate(questions):
        errors += _question_errors(q, index)
    return errors


def _question_errors(q, index):
    if not isinstance(q, dict):
        return [f"Soru {index + 1}: nesne olmalı."]
    id_ = q.get("id") or f"Soru {index + 1}"
    errors = []
    unknown = set(q) - REQUIRED - OPTIONAL
    if unknown:
        errors.append(f"Bilinmeyen alan: {', '.join(sorted(unknown))}.")
    missing = REQUIRED - set(q)
    if missing:
        errors.append(f"Zorunlu alan yok: {', '.join(sorted(missing))}.")
    if "category" in q and q["category"] not in CATEGORIES:
        errors.append(f"Bilinmeyen category: {q['category']}.")
    if "behavior" in q and q["behavior"] not in BEHAVIORS:
        errors.append(f"Bilinmeyen behavior: {q['behavior']}.")
    if "asks" in q and not isinstance(q["asks"], bool):
        errors.append("asks mantıksal olmalı.")

    tools = q.get("tools", [])
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        errors.append("tools metin listesi olmalı.")
        tools = []
    for name in tools:
        if name not in TOOL_NAMES:
            errors.append(f"Bilinmeyen tool: {name}.")
    for arg in q.get("args", []):
        if not isinstance(arg, dict) or set(arg) != {"name", "input"}:
            errors.append("args öğesi {name, input} olmalı.")
        elif arg["name"] not in tools:
            errors.append(f"args içindeki {arg['name']} tools'ta yok.")

    text = q.get("question")
    if isinstance(text, str):
        errors += _placeholder_errors(text, q.get("slots", {}))
    else:
        errors.append("question metin olmalı.")
        text = ""
    for name, ref in (q.get("slots") or {}).items():
        errors += [f"slots.{name}: {e}" for e in _calc_ref_errors(ref)]
    if "now" in q:
        errors += [f"now: {e}" for e in _calc_ref_errors(q["now"])]
    if "corruption" in q:
        errors += _corruption_errors(q["corruption"])
    for key in ("expect", "forbid"):
        refs = q.get(key, [])
        if not isinstance(refs, list):
            errors.append(f"{key} liste olmalı.")
            continue
        for ref in refs:
            errors += [f"{key}: {e}" for e in _value_ref_errors(ref, text)]

    _scan_numbers(q, "soru", errors, prefix="", question=text)
    return [f"{id_}: {e}" for e in errors]


def _placeholder_errors(text, slots):
    errors = []
    names = _PLACEHOLDER.findall(text)
    if "{" in _PLACEHOLDER.sub("", text) or "}" in _PLACEHOLDER.sub("", text):
        errors.append("question'da yer tutucu dışında { ya da } var.")
    slot_names = set(slots) if isinstance(slots, dict) else set()
    for name in sorted(set(names) - slot_names):
        errors.append(f"{{{name}}} için slots'ta hesap yok: {name}.")
    for name in sorted(slot_names - set(names)):
        errors.append(f"slots.{name} için question'da yer tutucu yok: {name}.")
    return errors


def _calc_ref_errors(ref):
    if not isinstance(ref, dict) or "calc" not in ref:
        return ["hesap referansı {calc, params, on?} olmalı."]
    errors = []
    unknown = set(ref) - {"calc", "params", "on"}
    if unknown:
        errors.append(f"Bilinmeyen referans alanı: {', '.join(sorted(unknown))}.")
    if ref["calc"] not in CALC_NAMES:
        errors.append(f"Bilinmeyen hesap adı: {ref['calc']}.")
    if not isinstance(ref.get("params"), dict):
        errors.append("params nesne olmalı.")
    if ref.get("on", "eval") not in ("eval", "base"):
        errors.append(f"on eval ya da base olmalı: {ref['on']}.")
    return errors


def _value_ref_errors(ref, question):
    if isinstance(ref, dict) and "literal" in ref:
        if set(ref) != {"literal"}:
            return ["literal referansında başka alan olamaz."]
        literal = ref["literal"]
        if not isinstance(literal, str) or not literal:
            return ["literal boş olmayan metin olmalı."]
        if re.search(r"\d", literal) and literal not in question:
            return [f"Rakamlı literal soru metninde geçmiyor: {literal}."]
        return []
    return _calc_ref_errors(ref)


def _corruption_errors(corruption):
    if not isinstance(corruption, dict):
        return ["corruption nesne olmalı."]
    errors = []
    unknown = set(corruption) - {"scenario", "flight_no", "field"}
    if unknown:
        errors.append(f"Bilinmeyen corruption alanı: {', '.join(sorted(unknown))}.")
    if corruption.get("scenario") not in SCENARIOS:
        errors.append(f"Bilinmeyen scenario: {corruption.get('scenario')}.")
    if not isinstance(corruption.get("flight_no"), str):
        errors.append("corruption.flight_no zorunlu.")
    if "field" in corruption and corruption.get("scenario") != "missing_field":
        errors.append("corruption.field yalnızca missing_field'da verilir.")
    return errors


def _scan_numbers(node, where, errors, *, prefix, question=None, key=None):
    """JSON sayısını ve izinsiz alandaki rakamı arar; questions listesine inmez."""
    if isinstance(node, bool):
        return
    if isinstance(node, int | float):
        errors.append(f"{prefix or key}: JSON sayısı olamaz (beklenen değer yazılmaz).")
        return
    if isinstance(node, str):
        allowed = key in DIGIT_KEYS or (
            key == "literal" and question is not None and node in question
        )
        if re.search(r"\d", node) and not allowed:
            errors.append(f"{prefix or key}: izinsiz alanda rakam: {node}.")
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if where == "golden" and k == "questions" and not prefix:
                continue
            _scan_numbers(
                v,
                where,
                errors,
                prefix=f"{prefix}.{k}" if prefix else k,
                question=question,
                key=k,
            )
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _scan_numbers(
                v, where, errors, prefix=f"{prefix}[{i}]", question=question, key=key
            )
