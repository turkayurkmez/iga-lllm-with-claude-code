"""Prompt enjeksiyonu savunması: tarama ve belge sınırlandırması.

Sözleşme docs/enjeksiyon.md'dedir. Bu modül saf fonksiyonlardan oluşur; ağ ya da sistem
saati kullanmaz, tek dosya okuması `load_exceptions`'tadır. Kalıplar yalnızca `FINDINGS`'te tanımlanır.
"""

import copy
import json
import re
from pathlib import Path

SEARCH_TOOL = "search_documents"

# Kalıplar Türkçe i/ı farkını yok saymak için normalize edilmiş metne uygulanır
# (bkz. `_fold`): metinde `İ`/`ı` `i`'ye çevrilir, kalıplarda yalnızca `i` yazılır.
FINDINGS: dict[str, re.Pattern[str]] = {
    "yok_say": re.compile(
        r"(?:(?:[oö]nceki|yukaridaki|tum)\s+(?:talimat\w*|kural\w*|y[oö]nerge\w*)"
        r"[^.\n]{0,40}?(?:yok\s+say|unut|dikkate\s+alma)"
        r"|ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+"
        r"(?:instructions|rules))",
        re.IGNORECASE,
    ),
    "rol_taklidi": re.compile(
        r"^\s*(?:system|assistant|sistem|asistan)\s*:", re.IGNORECASE | re.MULTILINE
    ),
    "ifsa_istegi": re.compile(
        r"(?:sistem\s+(?:talimat|prompt|mesaj)\w*[^.\n]{0,40}?"
        r"(?:yazdir|g[oö]ster|payla[sş]|ifsa|a[cç]ikla)|system\s+prompt)",
        re.IGNORECASE,
    ),
    "gizli_unicode": re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]"),
    "html_yorumu": re.compile(r"<!--"),
}

_HIDDEN = FINDINGS["gizli_unicode"]
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_DELIMITER = re.compile(r"<\s*/?\s*belge", re.IGNORECASE)
_DELIMITER_REPLACEMENT = "[belge-etiketi]"


def _fold(text: str) -> str:
    # str.lower() `İ`'yi iki karakter yapar; i/ı farkı kalıpları atlatmasın diye elle.
    return text.replace("İ", "i").replace("ı", "i")


def scan_text(text: str) -> list[str]:
    """Metinde eşleşen bulgu kodları; alfabetik ve tekrarsız."""
    folded = _fold(text)
    return sorted(code for code, pattern in FINDINGS.items() if pattern.search(folded))


def sanitize(text: str) -> str:
    """Gizli Unicode ve kontrol karakterlerini siler, belge sınırlayıcısını etkisizleştirir."""
    text = _CONTROL.sub("", _HIDDEN.sub("", text))
    return _DELIMITER.sub(_DELIMITER_REPLACEMENT, text)


def _fence(chunk: dict) -> dict:
    fenced = dict(chunk)
    fenced["text"] = (
        f'<belge id="{chunk["chunk_id"]}">\n{sanitize(chunk["text"])}\n</belge>'
    )
    return fenced


def render_tool_result(name: str, envelope: dict) -> str:
    """Modele giden tool_result içeriği; zarfın kendisi değişmez.

    search_documents parçalarının metni güvenilmez veridir: `<belge id>` ile çevrilir.
    """
    value = envelope.get("value")
    if name != SEARCH_TOOL or not isinstance(value, list):
        return json.dumps(envelope, ensure_ascii=False)
    rendered = copy.copy(envelope)
    rendered["value"] = [_fence(chunk) for chunk in value]
    return json.dumps(rendered, ensure_ascii=False)


# --- İndeks zamanı tarama (docs/enjeksiyon.md E3) ---------------------------------

EXCEPTIONS_FILE = Path(__file__).resolve().parents[1] / "data" / "korpus_istisna.json"
SCANNED_CHUNK_FIELDS = ("title", "section", "text")


def load_exceptions(path: Path | str = EXCEPTIONS_FILE) -> set[tuple[str, str]]:
    """Belge sahibinin onayladığı (chunk_id, kod) istisnaları; dosya yoksa boş küme."""
    path = Path(path)
    if not path.exists():
        return set()
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"İstisna dosyası okunamadı: {path.name}") from exc
    if not isinstance(records, list):
        raise ValueError("İstisna dosyası bir liste olmalı.")
    exceptions = set()
    for record in records:
        fields = ("chunk_id", "code", "reason")
        if not isinstance(record, dict) or not all(
            isinstance(record.get(f), str) and record[f].strip() for f in fields
        ):
            raise ValueError("İstisna kaydı chunk_id, code ve dolu reason taşımalı.")
        exceptions.add((record["chunk_id"], record["code"]))
    return exceptions


def filter_chunks(
    chunks: list[dict], exceptions: set[tuple[str, str]] | frozenset = frozenset()
) -> tuple[list[dict], list[dict]]:
    """Şüpheli parçaları ayırır: (kalanlar, karantina). Sıra korunur.

    Parçanın başlığı, bölümü ve metni taranır; istisnadaki (chunk_id, kod) sayılmaz.
    """
    kept, quarantined = [], []
    for chunk in chunks:
        codes = {
            code
            for field in SCANNED_CHUNK_FIELDS
            for code in scan_text(chunk.get(field, ""))
        }
        codes = sorted(c for c in codes if (chunk["chunk_id"], c) not in exceptions)
        if codes:
            quarantined.append({"chunk_id": chunk["chunk_id"], "codes": codes})
        else:
            kept.append(chunk)
    return kept, quarantined


# --- Çıktı denetimi ve mesaj işaretleri (docs/enjeksiyon.md E5, E6) ----------------

NUMBER = re.compile(r"\d+(?::\d{2})?")
CITATION_TAG = re.compile(r"\[D\d{2}#\d{2,}\]")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
MIN_LEAK_CHARS = 40


def unverified_numbers(answer: str, question: str, envelopes: list[dict]) -> list[str]:
    """Cevaptaki, soruda ya da tool `value`'larında bulunmayan sayı ve saatler.

    Bilinçli gevşektir: yalnızca simge eşlemesi yapar (`14:05` ISO damgadaki saatle,
    `37` bir rakam dizisiyle eşleşir); biçim farkları ve hesap kapsam dışıdır.
    """
    allowed = set(NUMBER.findall(question))
    for envelope in envelopes:
        allowed |= set(NUMBER.findall(json.dumps(envelope.get("value"), ensure_ascii=False)))
    found = set(NUMBER.findall(CITATION_TAG.sub("", answer)))
    return sorted(found - allowed)


def leaks_instruction(answer: str, system_text: str) -> bool:
    """Talimatın en az 40 karakterlik bir cümlesi cevapta aynen geçiyorsa True."""
    normalized_answer = " ".join(answer.split())
    sentences = SENTENCE_END.split(" ".join(system_text.split()))
    return any(
        len(sentence) >= MIN_LEAK_CHARS and sentence in normalized_answer
        for sentence in sentences
    )


def message_flags(message: str) -> list[str]:
    """Kullanıcı mesajındaki bulgular, `message:<kod>` biçiminde; isteği reddetmez."""
    return [f"message:{code}" for code in scan_text(message)]
