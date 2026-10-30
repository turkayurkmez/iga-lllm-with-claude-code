"""Talimat v3: v2 + kaynaklı cevap kuralları (docs/kaynakli.md, docs/system-talimat.md).

API'siz. v3 = v1 + `docs/chat.md › Talimat v2` değişiklikleri (v2.md) + atıf, sürüm,
çelişki ve bilmiyorum kuralları. Yazım kuralları (rakam yok, snake_case yalnızca tool
adları, zarf alan adı yok, hata kodları, 40 satır) her kayıtlı sürümde denetlenir;
v2'ye özgü içerik `tests/test_instruction_v2.py`'dedir, burada yalnızca v3'e özgü olan.
Metin parçaları (tırnak içindeki cümleler) talimatla birlikte sabitlenir.
"""

import importlib
import re
from pathlib import Path

import pytest

from backend.tools import tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTRUCTIONS_DIR = REPO_ROOT / "backend" / "instructions"
KAYNAKLI = REPO_ROOT / "docs" / "kaynakli.md"
SABIT_CUMLE = "Belgelerde bu konuda kaynak bulamadım."
ZARF_KODLARI = {
    "NOT_FOUND",
    "AMBIGUOUS_ENTITY",
    "STALE_DATA",
    "CAPABILITY_NOT_IN_SCOPE",
    "SCHEMA_VALIDATION_FAILED",
}
CODE_PATTERN = re.compile(r"\b[A-Z]+(?:_[A-Z]+)+\b")
SNAKE_CASE_PATTERN = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
OPERATIONAL_PATTERNS = {
    "rakam": re.compile(r"\d"),
    "sefer no": re.compile(r"\b(?:TK|THY)\d+"),
    "tescil": re.compile(r"\bTC-[A-Z]{3}\b"),
    "dosya uzantısı": re.compile(r"[\w-]+\.(?:json|py|md|csv)\b"),
    "dosya yolu": re.compile(r"\b(?:data|synth|backend|docs)[/\\]"),
}


def instructions():
    return importlib.import_module("backend.instructions")


def read(name: str) -> str:
    path = INSTRUCTIONS_DIR / f"{name}.md"
    assert path.is_file(), f"backend/instructions/{name}.md yok"
    return path.read_text(encoding="utf-8")


def paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


# ───────── Kayıt ─────────


def test_v3_kayitli_ve_aktif():
    module = instructions()

    assert module.VERSIONS["v3"] == "3.0.0"
    assert module.DEFAULT_VERSION == "v3"
    assert module.VERSIONS["v1"] == "1.0.0"
    assert module.load("v3") == read("v3")


# ───────── Yazım kuralları: her kayıtlı sürümde ─────────


@pytest.mark.parametrize("name", ["v1", "v2", "v3", "v4"])
@pytest.mark.parametrize("kind", OPERATIONAL_PATTERNS)
def test_operasyon_verisi_yok(name, kind):
    assert OPERATIONAL_PATTERNS[kind].findall(read(name)) == []


@pytest.mark.parametrize("name", ["v1", "v2", "v3", "v4"])
def test_snake_case_yalniz_kayitli_tool_adlari(name):
    registered = {definition["name"] for definition in tool_definitions()}

    assert set(SNAKE_CASE_PATTERN.findall(read(name))) <= registered


@pytest.mark.parametrize("name", ["v1", "v2", "v3", "v4"])
def test_hata_kodlari_zarftaki_kodlardan(name):
    assert set(CODE_PATTERN.findall(read(name))) <= ZARF_KODLARI


@pytest.mark.parametrize("name", ["v2", "v3", "v4"])
def test_zarf_alan_adlari_gecmez(name):
    # docs/chat.md › Talimat v2: "veri zamanı", "eski işaretli" gibi Türkçe adlar.
    found = re.findall(
        r"\b(?:value|stale|as_of|filters|tool_version|author)\b",
        read(name),
        re.IGNORECASE,
    )

    assert found == []


@pytest.mark.parametrize("name", ["v1", "v2", "v3", "v4"])
def test_markdown_baslik_xml_ve_bicimlendirme_yok(name):
    text = read(name)

    assert not re.search(r"^#", text, re.MULTILINE)
    assert "{" not in text
    assert "}" not in text
    # Yer tutucular (<kaynak>) serbest; XML etiketi çiftleri (</...>) yok.
    assert not re.search(r"</[A-Za-z]+>", text)


# ───────── v3: v2'nin çekirdeği korunur ─────────


def test_v3_v2nin_degismeyen_paragraflarini_korur():
    v2 = paragraphs(read("v2"))
    v3 = read("v3")

    # Rol, veri yalnızca tool'dan, hesap servise ait, eksik/eski veri, kapsam ve
    # ilkeler istekle kalkmaz: v2'de olduğu gibi kalan paragraflar.
    for index in (0, 1, 2, 5, 6, 7):
        assert v2[index] in v3, v2[index][:60]


def test_v3_dayanak_satiri_yok_cevap_yapisi_uc_parca():
    v3 = read("v3")

    for part in ("Doğrudan cevap:", "Ayrıntı:", "Uyarı:"):
        assert part in v3
    assert v3.index("Doğrudan cevap:") < v3.index("Ayrıntı:") < v3.index("Uyarı:")
    assert "Dayanak" not in v3
    assert "Kaynak: <kaynak>" not in v3
    assert "Kaynağı ve veri zamanını yazma" in v3
    assert "Türkçe, kısa ve düz cümlelerle yaz" in v3
    assert "muhtemelen" in v3  # yumuşatma yasağı


def test_v3_v2_degisikliklerini_icerir():
    v3 = read("v3")

    assert "sonuç eski işaretliyse" in v3
    assert "sefer no, callsign ya da tescille yeniden aramayı öner" in v3


# ───────── v3: kaynaklı cevap kuralları ─────────


def test_v3_belge_aramasi_tool_secimine_eklenir_ve_tek_yerde_adlanir():
    v3 = read("v3")

    assert v3.count("search_documents") == 1
    selection = next(p for p in paragraphs(v3) if "search_documents" in p)
    assert "resolve_flight_identity" in selection
    assert "get_flight_summary" in selection


def test_v3_atif_kurali():
    v3 = read("v3")

    assert "[<parça kimliği>]" in v3
    assert "Belge adı, bölüm, revizyon ve tarihi sen yazma" in v3
    assert "tool'dan gelmeyen kimlik yazma" in v3
    assert "yalnızca belge aramasının getirdiği parçalardan ver" in v3
    assert "sayı, süre ve mesafeyi parça metninde yazdığı gibi al" in v3


def test_v3_belge_cevaplarinin_dayanagi_etiketlerdir():
    v3 = read("v3")

    assert "Belgeden aldığın cümlelerin dayanağı sonlarındaki etiketlerdir" in v3


def test_v3_surum_kurali():
    v3 = read("v3")

    assert "yürürlükteki sürümler" in v3
    assert "eski sürümleri de getiren seçenekle ara" in v3
    assert "eski sürüm diye an" in v3
    assert "güncel kural gibi sunma" in v3
    assert "iki sürümü yan yana ver" in v3
    assert "ikisini de etiketle" in v3


def test_v3_celiski_ve_oncelik_kurali():
    v3 = read("v3")

    assert "birini sessizce seçme" in v3
    assert "İkisini de kendi etiketiyle göster" in v3
    assert "üst düzey kaynak" in v3
    assert "teyit gerektiğini belirt" in v3
    assert "bağlayıcı olmayan rehber" in v3
    assert "bağlayıcı belgeyi esas al" in v3


def test_v3_bilmiyorum_kurali_sabit_cumle():
    v3 = read("v3")

    assert SABIT_CUMLE in v3
    assert SABIT_CUMLE in KAYNAKLI.read_text(encoding="utf-8")
    assert "gelen parçalar soruyu cevaplamıyorsa" in v3
    assert "Tahmin etme" in v3
    assert "hafızandan" in v3


def test_v3_belge_aramasinda_not_found_ozel_cumle_ister():
    v3 = read("v3")

    # İlke 5 uçuş kayıtları içindir; belge aramasında sabit cümle geçerlidir.
    assert "belge araması dışında" in v3
    assert "NOT_FOUND" in v3


def test_v3_cevap_dili_ve_ingilizce_kaynak():
    v3 = read("v3")

    assert "İngilizce bir kaynak kullanırsan özetini Türkçe ver" in v3
    assert "etiketi koru" in v3
