"""Gömme katmanı (docs/rag.md §4): Voyage AI'yi yalnızca bu modül bilir.

Belge parçaları `input_type="document"`, sorular `input_type="query"` ile gömülür.
İstekler 128'lik gruplarla gider; 429'da bekleyip yeniden dener. Vektörler birim
uzunluğa getirilir (benzerlik iç çarpımdır). İndeks yazımı bu modülde yoktur: grup
başarısız olursa kısmi sonuç dönmez, istisna fırlar. Sistem saati okunmaz.
"""

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from time import sleep

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
# Sorgu vektörleri indeks klasörünün dışında tutulur (docs/hibrit.md › Önbellek).
QUERY_CACHE = Path(__file__).resolve().parents[2] / "data" / "sorgu_onbellegi.json"

BATCH_SIZE = 128
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = 1.0


class EmbedConfigError(RuntimeError):
    """Gömme için gereken ortam değişkeni eksik ya da boş."""


class EmbedError(RuntimeError):
    """Gömme isteği başarısız oldu; ayrıntı (anahtar, API yanıtı) mesaja girmez."""


@dataclass(frozen=True)
class EmbedResult:
    """Girdiyle aynı sırada birim vektörler, kullanılan model ve toplam token."""

    vectors: list[list[float]]
    model: str
    total_tokens: int | None


def _setting(name: str) -> str:
    load_dotenv(ENV_FILE)
    value = os.getenv(name, "").strip()
    if not value:
        raise EmbedConfigError(
            f"Ortam değişkeni eksik veya boş: {name}. Bu değişkeni {ENV_FILE} "
            "dosyasında ya da ortamda tanımlayın (şablon için .env.example)."
        )
    return value


def embed_model() -> str:
    """Ayarlı gömme modeli (`COPILOT_EMBED_MODEL`); eksikse `EmbedConfigError`."""
    return _setting("COPILOT_EMBED_MODEL")


def _make_client(api_key: str):
    # SDK yalnızca gerçek istemci gerektiğinde yüklenir; testler sahte istemci verir.
    import voyageai

    return voyageai.Client(api_key=api_key)


def _is_rate_limit(exc: Exception) -> bool:
    return 429 in (
        getattr(exc, "http_status", None),
        getattr(exc, "status_code", None),
    )


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm or not math.isfinite(norm):
        raise EmbedError("Gömme yanıtında sıfır ya da geçersiz uzunlukta vektör var.")
    return [x / norm for x in vector]


def _embed_batch(client, texts: list[str], model: str, input_type: str):
    """Tek grubu gönderir; yalnızca 429'da en çok MAX_ATTEMPTS deneme yapar."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return client.embed(texts, model=model, input_type=input_type)
        except Exception as exc:  # noqa: BLE001 - SDK hata türleri burada sızdırılmaz
            if not _is_rate_limit(exc):
                raise EmbedError("Gömme isteği başarısız oldu.") from None
            if attempt == MAX_ATTEMPTS - 1:
                raise EmbedError(
                    f"Hız sınırı aşıldı; {MAX_ATTEMPTS} denemeden sonra vazgeçildi."
                ) from None
            sleep(BACKOFF_SECONDS * 2**attempt)
    raise AssertionError("ulaşılamaz")  # pragma: no cover


def _embed(texts: list[str], input_type: str, client, model: str | None):
    model = model if model is not None else _setting("COPILOT_EMBED_MODEL")
    if not texts:
        return EmbedResult(vectors=[], model=model, total_tokens=None)
    if client is None:
        client = _make_client(_setting("VOYAGE_API_KEY"))

    vectors: list[list[float]] = []
    total_tokens = 0
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        response = _embed_batch(client, batch, model, input_type)
        embeddings = list(response.embeddings)
        if len(embeddings) != len(batch):
            raise EmbedError(
                f"Gömme yanıtı {len(batch)} yerine {len(embeddings)} vektör içeriyor."
            )
        vectors.extend(_normalize(list(v)) for v in embeddings)
        total_tokens += getattr(response, "total_tokens", 0) or 0

    if len({len(v) for v in vectors}) != 1:
        raise EmbedError("Gömme yanıtındaki vektör boyutları tutarsız.")
    return EmbedResult(vectors=vectors, model=model, total_tokens=total_tokens)


@dataclass(frozen=True)
class QueryVectors:
    """Girdiyle aynı sırada birim vektörler; `fetched` API'ye giden benzersiz sorgu."""

    vectors: list[list[float]]
    model: str
    fetched: int


def _is_vector(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) for x in value
    )


def _read_query_cache(path: Path) -> dict[str, dict[str, list[float]]]:
    """Önbelleği okur; yok, bozuk ya da beklenmedik biçimliyse boş sayılır."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if not all(
        isinstance(queries, dict) and all(_is_vector(v) for v in queries.values())
        for queries in data.values()
    ):
        return {}
    return data


def _write_query_cache(path: Path, data: dict) -> None:
    """Geçici dosya + `os.replace`; Windows'ta kısa kilitler için 5 kez dener.

    Yazılamıyorsa sessizce vazgeçilir: önbellek yalnızca hızlandırır.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        for attempt in range(MAX_ATTEMPTS):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                sleep(0.1 * 2**attempt)
    except OSError:
        tmp.unlink(missing_ok=True)


def embed_queries(
    texts: list[str],
    client=None,
    model: str | None = None,
    cache_path: Path | str | None = None,
) -> QueryVectors:
    """Soruları `input_type="query"` ile gömer; vektörleri diskte önbelleğe alır.

    Anahtar model + sorgu metnidir. Önbellekte olmayan benzersiz sorgular tek
    istekle (en çok `BATCH_SIZE` başına bir) gömülür; hepsi önbellekteyse istemci
    kurulmaz. `cache_path` verilmezse `QUERY_CACHE` çağrı anında okunur.
    """
    if any(not text.strip() for text in texts):
        raise ValueError("Soru metni boş olamaz.")
    model = model if model is not None else _setting("COPILOT_EMBED_MODEL")
    path = Path(QUERY_CACHE if cache_path is None else cache_path)

    data = _read_query_cache(path)
    cached = data.get(model, {})
    missing = [text for text in dict.fromkeys(texts) if text not in cached]
    if missing:
        fresh = _embed(missing, "query", client, model).vectors
        data[model] = {**cached, **dict(zip(missing, fresh, strict=True))}
        _write_query_cache(path, data)
        cached = data[model]
    return QueryVectors(
        vectors=[cached[text] for text in texts], model=model, fetched=len(missing)
    )


def embed_documents(
    texts: list[str], client=None, model: str | None = None
) -> EmbedResult:
    """Belge parçası metinlerini `input_type="document"` ile gömer.

    `client` verilmezse `VOYAGE_API_KEY` ile Voyage istemcisi kurulur; `model`
    verilmezse `COPILOT_EMBED_MODEL` okunur.
    """
    return _embed(list(texts), "document", client, model)


def embed_query(text: str, client=None, model: str | None = None) -> list[float]:
    """Soruyu `input_type="query"` ile gömer ve tek birim vektör döndürür."""
    if not text.strip():
        raise ValueError("Soru metni boş olamaz.")
    return _embed([text], "query", client, model).vectors[0]
