"""Ortak pytest ayarları: talimat sürümü seçimi (docs/system-talimat.md › Versiyonlama).

`--instruction v3` agent testlerinin kullandığı talimat dosyasını seçer
(backend/instructions/v3.md). Verilmezse sırayla ortamdaki COPILOT_INSTRUCTION,
.env'deki değer ve v3 kullanılır. Seçilen dosya ve özeti oturum sonunda yazılır.
"""

import hashlib
import os
import re
from pathlib import Path

import pytest
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS_DIR = REPO_ROOT / "backend" / "instructions"
ENV_VAR = "COPILOT_INSTRUCTION"
FALLBACK = "v3"
NAME_PATTERN = re.compile(r"^v\d+$")
INSTRUCTION_KEY = pytest.StashKey[str]()


def pytest_addoption(parser):
    parser.addoption(
        "--instruction",
        default=None,
        help=(
            "Agent testlerinin talimat sürümü (ör. v1 → backend/instructions/v1.md). "
            f"Verilmezse {ENV_VAR}, o da boşsa {FALLBACK}."
        ),
    )


def _resolve(config: pytest.Config) -> str:
    value = config.getoption("--instruction") or os.environ.get(ENV_VAR, "")
    if not value.strip():
        # .env ortama yazılmaz; yalnızca değeri okunur.
        value = dotenv_values(REPO_ROOT / ".env").get(ENV_VAR) or ""
    return value.strip() or FALLBACK


def pytest_configure(config: pytest.Config) -> None:
    name = _resolve(config)
    if not NAME_PATTERN.match(name) or not (INSTRUCTIONS_DIR / f"{name}.md").is_file():
        raise pytest.UsageError(
            f"Bilinmeyen talimat sürümü: {name!r} "
            f"(backend/instructions/{name}.md bulunamadı)."
        )
    config.stash[INSTRUCTION_KEY] = name


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    name = config.stash[INSTRUCTION_KEY]
    text = (INSTRUCTIONS_DIR / f"{name}.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    terminalreporter.write_line(f"talimat: {name}.md (Özet: {digest[:12]})")


@pytest.fixture(autouse=True)
def audit_dir(tmp_path, monkeypatch) -> Path:
    """Her testin kendi audit klasörü (docs/audit.md › Kurallar 7).

    /chat'i çağıran her test buraya yazar; repo'daki logs/audit'e hiçbir test yazmaz.
    Klasör oluşturulmaz: ilk yazımda oluşturulması da sözleşmedir.
    """
    path = tmp_path / "audit"
    monkeypatch.setenv("COPILOT_AUDIT_DIR", str(path))
    return path


@pytest.fixture
def instruction_name(pytestconfig) -> str:
    """--instruction ile seçilen talimat sürümünün adı (ör. "v1")."""
    return pytestconfig.stash[INSTRUCTION_KEY]
