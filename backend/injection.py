"""Prompt enjeksiyonu savunması: tarama ve belge sınırlandırması.

Sözleşme docs/enjeksiyon.md'dedir. Bu modül saf fonksiyonlardan oluşur; dosya, ağ ya
da sistem saati kullanmaz. Kalıplar yalnızca `FINDINGS`'te tanımlanır.
"""

import copy
import json
import re

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
