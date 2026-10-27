"""BM25 anahtar kelime araması (docs/hibrit.md › BM25 için metin hazırlama, BM25 skoru).

Hazır paket ve gömme katmanı kullanmaz; yalnızca standart kütüphane. Tablo her
çağrıda, verilen metinlerden bellekte kurulur; diske yazılmaz, çağrılar arası saklanmaz.
"""

import math
import re
import unicodedata
from collections import Counter

K1 = 1.5
B = 0.75
STEM_LENGTH = 5

# Adım 1: kesme işaretinden (düz ya da kıvrık) sonraki ek, işaretle birlikte atılır.
_APOSTROPHE_SUFFIX = re.compile(r"['’][^\W_]*")
# Adım 2: harf ve rakam dizileri sözcüktür (alt çizgi ayırıcıdır).
_WORD = re.compile(r"[^\W_]+")
# Adım 3: `str.lower()` "İ"yi "i" + birleştirici noktaya çevirir, "I"yı "ı" bırakır;
# bu üçünü küçük harften önce doğrudan "i"ye indiriyoruz.
_DOTTED_I = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def _fold(text: str) -> str:
    """Türkçe-duyarlı küçük harf ve ASCII'ye indirme (ç ş ğ ü ö → c s g u o)."""
    lowered = text.translate(_DOTTED_I).lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    """Metni sözcüklere ayırır; sıra ve tekrarlar korunur (terim sıklığı için)."""
    words = _WORD.findall(_fold(_APOSTROPHE_SUFFIX.sub("", text)))
    # Adım 4: rakam içermeyen sözcüklerde yalnızca ilk 5 harf; TK2345 gibi
    # rakamlı sözcükler kısaltılmaz.
    return [
        word if any(ch.isdigit() for ch in word) else word[:STEM_LENGTH]
        for word in words
    ]


def score(query: str, texts: list[str], candidates: list[int]) -> dict[int, float]:
    """`candidates` içindeki parçaların Okapi BM25 skorlarını döndürür.

    `idf` ve ortalama parça uzunluğu `texts`'in tamamından hesaplanır; yalnızca
    skorlanan parçalar `candidates` ile sınırlanır. Skoru 0 olan parça sonuçta
    yoktur. Sorgudaki tekrar eden sözcük bir kez sayılır.
    """
    documents = [Counter(tokenize(text)) for text in texts]
    lengths = [sum(counts.values()) for counts in documents]
    total = len(documents)
    average = sum(lengths) / total if total else 0.0
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms or average == 0:
        return {}

    document_frequency = {
        term: sum(1 for counts in documents if term in counts) for term in terms
    }
    scores = {}
    for index in candidates:
        counts = documents[index]
        norm = K1 * (1 - B + B * lengths[index] / average)
        value = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            n = document_frequency[term]
            idf = math.log(1 + (total - n + 0.5) / (n + 0.5))
            value += idf * tf * (K1 + 1) / (tf + norm)
        if value > 0:
            scores[index] = value
    return scores
