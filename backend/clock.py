"""Uygulamanın tek saat kaynağı (docs/zarf.md › Saat tek yerden okunur).

Sistem saati backend/ altında yalnızca burada okunur. COPILOT_NOW doluysa now() her
çağrıda bu sabit anı döner; böylece simülasyon ve testler belirlenimci kalır. Değer
her çağrıda ortamdan yeniden okunur. .env, llm.py'deki gibi ortamdaki değerleri
ezmeden yüklenir.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ENV_VAR = "COPILOT_NOW"
TZ = timezone(timedelta(hours=3))

load_dotenv(ENV_FILE)


class ClockError(RuntimeError):
    """COPILOT_NOW geçerli bir saat dilimli zaman olmadığında fırlatılır."""


def now() -> datetime:
    raw = os.getenv(ENV_VAR, "").strip()
    if not raw:
        return datetime.now(TZ)

    try:
        fixed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ClockError(
            f"{ENV_VAR} geçerli bir ISO 8601 zamanı değil: {raw!r}. "
            "Örnek: 2026-10-20T16:22:00+03:00"
        ) from exc
    if fixed.utcoffset() is None:
        raise ClockError(
            f"{ENV_VAR} saat dilimi içermeli: {raw!r}. Örnek: 2026-10-20T16:22:00+03:00"
        )
    return fixed.astimezone(TZ)
