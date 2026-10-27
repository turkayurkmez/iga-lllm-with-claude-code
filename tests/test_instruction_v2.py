"""Talimat v2: v1 + docs/chat.md › Talimat v2 değişiklikleri.

API'siz. Testler koddan önce yazıldı: `backend/instructions/v2.md` ve sürüm kaydı
yokken kırmızıdır. Ortak yazım kuralları (rakam yok, snake_case, hata kodları,
zarf alan adı yok, 40 satır) `tests/test_instruction_v3.py` ve
`tests/test_instructions.py`'de her kayıtlı sürüm için denetlenir.

Değişiklikler (chat.md): 1) Dayanak parçası kalkar, cevap yapısı üç parça; 2) eski
işaretli sonuçta "şu an", "şimdi", "güncel" denmez; 3) bulunamadığında aranan değer
söylenir ve sefer no, callsign ya da tescille yeniden arama önerilir. Yazım:
zarf alan adları (value, stale, as_of, filters) geçmez.
"""

import importlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS_DIR = REPO_ROOT / "backend" / "instructions"


def read(name: str) -> str:
    path = INSTRUCTIONS_DIR / f"{name}.md"
    assert path.is_file(), f"backend/instructions/{name}.md yok"
    return path.read_text(encoding="utf-8")


def paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


def test_v2_kayitli_surum_ve_dosya():
    module = importlib.import_module("backend.instructions")

    assert module.VERSIONS["v2"] == "2.0.0"
    assert module.load("v2") == read("v2")


def test_v2_v1in_degismeyen_paragraflarini_korur():
    v1 = paragraphs(read("v1"))
    v2 = read("v2")

    # Rol (0), tool seçimi (3), kapsam (6) ve ilkeler istekle kalkmaz (7) aynen kalır.
    for index in (0, 3, 6, 7):
        assert v1[index] in v2, v1[index][:60]


def test_v2_cevap_yapisi_uc_parca_dayanak_yok():
    v2 = read("v2")

    for part in ("Doğrudan cevap:", "Ayrıntı:", "Uyarı:"):
        assert part in v2
    assert v2.index("Doğrudan cevap:") < v2.index("Ayrıntı:") < v2.index("Uyarı:")
    assert "Dayanak" not in v2
    assert "Kaynak: <kaynak>" not in v2
    assert "itibarıyla" not in v2
    assert "Kaynağı ve veri zamanını yazma; ikisi kodca gösterilir" in v2


def test_v2_eski_veri_kurali_netlesir():
    v2 = read("v2")

    assert "sonuç eski işaretliyse son değeri veri zamanıyla ver" in v2
    assert '"şu an", "şimdi", "güncel" deme' in v2
    assert "veride yok" in v2  # eksik alan kuralı v1'deki gibi


def test_v2_bulunamadi_kurali_netlesir():
    v2 = read("v2")

    assert "kaydın bulunamadığını ve aradığın değeri söyle" in v2
    assert "sefer no, callsign ya da tescille yeniden aramayı öner" in v2
    assert "benzer bir kayıt önerme" in v2


def test_v2_belirsizlik_kurali_v1deki_gibi():
    v2 = read("v2")

    assert "AMBIGUOUS_ENTITY'de adayların hepsini listele ve netleştirme iste" in v2
    assert "birini kendin seçme" in v2


def test_v2_turkce_alan_adlariyla_anar():
    v2 = read("v2")

    assert "veri zamanı" in v2
    assert "eski işaretli" in v2


def test_v2_kaynakli_cevap_kurallari_icermez():
    v2 = read("v2")

    assert "search_documents" not in v2
    assert "[<parça kimliği>]" not in v2
    assert "Belgelerde bu konuda kaynak bulamadım." not in v2
