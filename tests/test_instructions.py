"""Sürümlü talimat yükleyicisi sözleşme testleri (docs/system-talimat.md › Versiyonlama).

Testler koddan önce yazıldı; backend.instructions yokken kırmızıdır. Talimat
metninin içeriği tests/test_prompts.py'de denetlenir.
"""

import hashlib
import importlib
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS_DIR = REPO_ROOT / "backend" / "instructions"
MAX_LINES = 40


def instructions():
    assert importlib.util.find_spec("backend.instructions") is not None, (
        "backend.instructions modülü yok."
    )
    return importlib.import_module("backend.instructions")


def test_varsayilan_surum_v3():
    assert instructions().DEFAULT_VERSION == "v3"


def test_ortam_bos_ya_da_tanimsizsa_varsayilan_v3(monkeypatch):
    monkeypatch.delenv("COPILOT_INSTRUCTION", raising=False)
    assert instructions().default_version() == "v3"

    monkeypatch.setenv("COPILOT_INSTRUCTION", "  ")
    assert instructions().default_version() == "v3"


def test_ortamdaki_surum_varsayilan_olur(monkeypatch):
    monkeypatch.setenv("COPILOT_INSTRUCTION", " v7 ")

    assert instructions().default_version() == "v7"


def test_varsayilan_yukleme_v3_dosyasini_doner():
    expected = (INSTRUCTIONS_DIR / "v3.md").read_text(encoding="utf-8")

    assert instructions().load() == expected


@pytest.mark.parametrize("name", ["v1", "v2", "v3", "v4"])
def test_surum_verilince_o_dosya_yuklenir(name):
    expected = (INSTRUCTIONS_DIR / f"{name}.md").read_text(encoding="utf-8")

    assert instructions().load(name) == expected


@pytest.mark.parametrize("version", ["v999", "v0", "1", "v1.md", "../prompts", ""])
def test_bilinmeyen_ya_da_gecersiz_surum_hata_verir(version):
    with pytest.raises(ValueError, match="Bilinmeyen talimat sürümü"):
        instructions().load(version)


def test_ozet_metnin_sha256_si():
    text = instructions().load("v1")

    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert instructions().summary(text) == expected


def test_kayitli_surumler_dosyalarla_birebir():
    files = {path.stem for path in INSTRUCTIONS_DIR.glob("*.md")}

    assert set(instructions().VERSIONS) == files


def test_kayitli_surumler_semver_bicimli():
    for name, version in instructions().VERSIONS.items():
        major, *_ = version.split(".")
        assert name == f"v{major}", f"{name} dosyası {version} sürümünü taşıyamaz."


@pytest.mark.parametrize("name", ["v1", "v2", "v3", "v4"])
def test_surum_dosyasi_kirk_satiri_asmaz(name):
    lines = (INSTRUCTIONS_DIR / f"{name}.md").read_text(encoding="utf-8").splitlines()

    assert len(lines) <= MAX_LINES, f"{name}.md {len(lines)} satır."


def test_prompts_varsayilan_surumu_kullanir():
    module = instructions()
    prompts = importlib.import_module("backend.prompts")

    version = module.default_version()

    assert prompts.SYSTEM_INSTRUCTIONS == module.load(version)
    assert prompts.SYSTEM_INSTRUCTIONS_VERSION == module.VERSIONS[version]
