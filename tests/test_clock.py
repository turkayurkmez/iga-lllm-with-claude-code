"""Saat modülü sözleşme testleri (docs/zarf.md › Saat tek yerden okunur).

Testler koddan önce yazıldı; backend/clock.py yokken kırmızıdır.
"""

import importlib
import importlib.util
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ISTANBUL = timezone(timedelta(hours=3))
CLOCK_CALL = re.compile(
    r"\b(?:datetime\.now|datetime\.utcnow|datetime\.today|date\.today|time\.time)\("
)


def load_clock():
    assert importlib.util.find_spec("backend.clock") is not None, "backend/clock.py yok"
    return importlib.import_module("backend.clock")


def test_copilot_now_doluysa_sabit_saat_doner(monkeypatch):
    clock = load_clock()
    monkeypatch.setenv("COPILOT_NOW", "2026-10-20T16:22:00+03:00")

    assert clock.now() == datetime(2026, 10, 20, 16, 22, tzinfo=ISTANBUL)
    assert clock.now() == clock.now()


def test_copilot_now_baska_saat_dilimindeyse_istanbul_saatine_cevrilir(monkeypatch):
    clock = load_clock()
    monkeypatch.setenv("COPILOT_NOW", "2026-10-20T13:22:00+00:00")

    now = clock.now()

    assert now.utcoffset() == timedelta(hours=3)
    assert now.isoformat() == "2026-10-20T16:22:00+03:00"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_copilot_now_bos_ya_da_tanimsizsa_sistem_saati_doner(monkeypatch, value):
    clock = load_clock()
    if value is None:
        monkeypatch.delenv("COPILOT_NOW", raising=False)
    else:
        monkeypatch.setenv("COPILOT_NOW", value)

    before = datetime.now(ISTANBUL)
    now = clock.now()
    after = datetime.now(ISTANBUL)

    assert now.utcoffset() == timedelta(hours=3)
    assert before <= now <= after


@pytest.mark.parametrize(
    "value", ["2026-10-20T16:22:00", "yarın", "2026-13-40T16:22:00+03:00"]
)
def test_gecersiz_copilot_now_turkce_hata_verir(monkeypatch, value):
    clock = load_clock()
    monkeypatch.setenv("COPILOT_NOW", value)

    with pytest.raises(clock.ClockError, match="COPILOT_NOW"):
        clock.now()


def test_sistem_saati_yalnizca_clock_modulunde_okunur():
    load_clock()
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "backend").rglob("*.py"))
        if path.name != "clock.py"
        and CLOCK_CALL.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
