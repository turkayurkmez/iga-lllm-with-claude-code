"""Sürümlü system talimatları (docs/system-talimat.md › Versiyonlama).

Her MAJOR sürüm bu klasörde `v<MAJOR>.md` dosyasıdır; tam sürüm (MAJOR.MINOR.PATCH)
`VERSIONS`'ta tutulur. Metin dosyadan olduğu gibi okunur, birleştirilmez ya da
biçimlendirilmez.
"""

import hashlib
import os
from pathlib import Path

# COPILOT_INSTRUCTION boş ya da tanımsızsa kullanılan sürüm.
DEFAULT_VERSION = "v3"
ENV_VAR = "COPILOT_INSTRUCTION"

# Dosya adı → tam sürüm. Metin değişince buradaki sürüm de artar.
VERSIONS = {
    "v1": "1.0.0",
    "v2": "2.0.0",
    "v3": "3.0.0",
    "v4": "4.0.0",
    "v5": "5.0.0",
}

_DIR = Path(__file__).resolve().parent


def default_version() -> str:
    """Kullanılacak sürüm: COPILOT_INSTRUCTION, boşsa DEFAULT_VERSION.

    Değer her çağrıda süreç ortamından okunur; .env'deki değer yalnızca backend.llm
    .env'yi yükledikten sonra görünür. Değer burada doğrulanmaz, load() doğrular.
    """
    return os.environ.get(ENV_VAR, "").strip() or DEFAULT_VERSION


def load(version: str = DEFAULT_VERSION) -> str:
    """Verilen sürümün talimat metnini döner; bilinmeyen sürümde ValueError."""
    # Yalnızca kayıtlı adlar kabul edilir; böylece klasör dışına çıkılamaz.
    if version not in VERSIONS:
        raise ValueError(f"Bilinmeyen talimat sürümü: {version!r}")
    return (_DIR / f"{version}.md").read_text(encoding="utf-8")


def summary(text: str) -> str:
    """Talimat metninin SHA-256 özeti (hex); modele giden metni byte byte tanımlar."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
