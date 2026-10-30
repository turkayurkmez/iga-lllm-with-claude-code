"""Talimat v5: v4 + oturum geçmişi ilkesi (spec: 2026-10-30-…-design.md › A › Talimat).

API'siz. Yazım kuralları (rakam yok, snake_case yalnızca tool adları, hata kodları,
zarf alan adı yok) v5'te de `test_instruction_v3.py` ve `test_instructions.py` içinde
her kayıtlı sürüm için denetlenir; burada yalnızca v5'e özgü olan vardır.
"""

import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS_DIR = REPO_ROOT / "backend" / "instructions"
CONTRACT = REPO_ROOT / "docs" / "system-talimat.md"
MAX_LINES = 40


def instructions():
    return importlib.import_module("backend.instructions")


def read(name: str) -> str:
    path = INSTRUCTIONS_DIR / f"{name}.md"
    assert path.is_file(), f"backend/instructions/{name}.md yok"
    return path.read_text(encoding="utf-8")


def paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


def added() -> list[str]:
    v4 = set(paragraphs(read("v4")))
    return [p for p in paragraphs(read("v5")) if p not in v4]


def test_v5_kayitli_ama_varsayilan_v3_kalir():
    module = instructions()

    assert module.VERSIONS["v5"] == "5.0.0"
    assert module.load("v5") == read("v5")
    # Varsayılanı değiştirmek ölçüm sonrası kullanıcı kararıdır.
    assert module.DEFAULT_VERSION == "v3"


def test_v5_v4un_butun_paragraflarini_aynen_icerir():
    v4, v5 = paragraphs(read("v4")), read("v5")

    assert v4
    for paragraph in v4:
        assert paragraph in v5, paragraph[:60]


def test_v5_tek_yeni_paragraf_ekler_ve_neden_ile_biter():
    new = added()

    assert len(new) == 1
    assert "Neden:" in new[0]
    assert "önceki tur" in new[0]


def test_v5_yeni_ilke_sayiyi_bu_turun_tool_cagrisina_baglar():
    (paragraph,) = added()

    assert "yeniden çağır" in paragraph
    assert "önceki cevaptan sayı verme" in paragraph


def test_v5_yeni_ilke_kisa_cevabi_onceki_sorunun_cevabi_sayar_ve_emin_degilse_sorar():
    (paragraph,) = added()

    assert "kısa cevabı" in paragraph
    assert "araç notundaki tarifi koru" in paragraph
    assert "kullanıcıya sor" in paragraph


def test_v5_dosya_kirk_satiri_asmaz():
    assert len(read("v5").splitlines()) <= MAX_LINES


def test_v5_gunlukte_var():
    text = CONTRACT.read_text(encoding="utf-8")
    _, _, section = text.partition("## Değişiklik günlüğü")

    assert "`5.0.0`" in section
