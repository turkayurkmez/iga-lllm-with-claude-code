"""Eval hesap adları sözleşme testleri (docs/eval.md › Hesap adları).

Testler koddan önce yazıldı; eval.expected yokken kırmızıdır. Tek giriş noktası
compute(ref, base, data, now) kullanılır. Veri, spec §8 alan adlarıyla elle kurulmuş
küçük bir sözlüktür; dosya okunmaz, tool çağrılmaz.
"""

import ast
import copy
import importlib
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "eval" / "expected.py"

NOW = datetime.fromisoformat("2026-10-20T12:32:30+03:00")


def t(hhmm):
    return f"2026-10-20T{hhmm}:00+03:00"


def flight(flight_id, flight_no, callsign, registration, sched, est, cancelled):
    return {
        "flight_id": flight_id,
        "flight_no": flight_no,
        "callsign": callsign,
        "registration": registration,
        "aircraft_type": "A321",
        "origin": "XXXX",
        "destination": "VAN",
        "scheduled_time": t(sched),
        "estimated_time": t(est),
        "cancelled": cancelled,
    }


def movement(flight_id, movement_type, stand=None, gate=None, block=None, rwy=None):
    return {
        "flight_id": flight_id,
        "movement_type": movement_type,
        "stand_code": stand,
        "gate_code": gate,
        "actual_block_time": block,
        "actual_runway_time": rwy,
    }


def position(flight_id, hhmm, lat, lon):
    return {
        "flight_id": flight_id,
        "ts": t(hhmm),
        "lat": lat,
        "lon": lon,
        "heading_deg": 90.0,
        "speed_kt": 10.0,
        "phase": "TAXI_OUT",
    }


# 5 uçuş: iki iptal XQ1 (sefer no tekil değil), TC-AAA'nın arrival/departure çifti,
# iptal TK0015. FL-20261020-0099 yetimdir: movements/delays/positions'ta var,
# flights'ta yok; hiçbir hesapta kullanılmaz.
DATA = {
    "meta": {"seed": 1, "date": "2026-10-20", "generator_version": "1.0.0"},
    "stands": [
        {"stand_code": "S1"},
        {"stand_code": "S2"},
        {"stand_code": "S3"},
    ],
    "flights": [
        flight("FL-20261020-0001", "XQ1", "THY0101", "TC-XQA", "09:00", "09:00", True),
        flight("FL-20261020-0002", "XQ1", "THY0102", "TC-XQA", "11:00", "11:00", True),
        flight(
            "FL-20261020-0003", "TK100", "THY100", "TC-AAA", "10:00", "10:00", False
        ),
        flight(
            "FL-20261020-0004", "TK101", "THY101", "TC-AAA", "12:00", "12:30", False
        ),
        flight(
            "FL-20261020-0005", "TK0015", "THY0015", "TC-BBB", "13:00", "13:00", True
        ),
    ],
    "movements": [
        movement("FL-20261020-0001", "ARRIVAL"),
        movement("FL-20261020-0002", "DEPARTURE"),
        movement("FL-20261020-0003", "ARRIVAL", "S1", "G1", t("09:58"), t("09:52")),
        movement("FL-20261020-0004", "DEPARTURE", "S2", "G2", t("12:31"), t("12:40")),
        movement("FL-20261020-0005", "DEPARTURE"),
        movement("FL-20261020-0099", "DEPARTURE", "S3", "G3"),
    ],
    "delays": [
        {
            "flight_id": "FL-20261020-0004",
            "delay_minutes": 30,
            "delay_code": "93",
            "category": "REACTIONARY",
        },
        {
            "flight_id": "FL-20261020-0099",
            "delay_minutes": 50,
            "delay_code": "81",
            "category": "WEATHER",
        },
    ],
    # Sıra bilerek karışık: hesap ts'ye göre seçmeli, liste sırasına göre değil.
    "positions": [
        position("FL-20261020-0004", "12:33", 41.3, 28.73),
        position("FL-20261020-0004", "12:31", 41.1, 28.71),
        position("FL-20261020-0004", "12:32", 41.2, 28.72),
        position("FL-20261020-0099", "12:35", 40.0, 29.0),
    ],
}


@pytest.fixture
def expected():
    return importlib.import_module("eval.expected")


def calc(expected, name, params=None, *, base=None, data=None, now=NOW, on=None):
    ref = {"calc": name, "params": params or {}}
    if on is not None:
        ref["on"] = on
    base = DATA if base is None else base
    data = DATA if data is None else data
    return expected.compute(ref, base, data, now)


def without_flight(flight_no):
    data = copy.deepcopy(DATA)
    data["flights"] = [f for f in data["flights"] if f["flight_no"] != flight_no]
    return data


# --- Modül ---


def test_modul_var():
    # Üst paket yokken find_spec("eval.expected") istisna fırlatır; önce paket.
    assert importlib.util.find_spec("eval") is not None
    assert importlib.util.find_spec("eval.expected") is not None


def test_modul_tool_katmanini_import_etmez():
    assert MODULE_PATH.is_file()
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert imported, "modülde hiç import bulunamadı"
    assert not [name for name in imported if name.startswith("backend")]


def test_hesap_veriyi_degistirmez(expected):
    data = copy.deepcopy(DATA)
    calc(
        expected,
        "identity.candidates",
        {"query": "TC-AAA", "field": "flight_no"},
        base=data,
        data=data,
    )
    calc(
        expected,
        "position.last",
        {"flight_no": "TK101", "field": "ts"},
        base=data,
        data=data,
    )
    assert data == DATA


# --- summary.* ---


@pytest.mark.parametrize(
    ("name", "direction", "value"),
    [
        ("summary.total", "all", 5),
        ("summary.total", "arrival", 2),
        ("summary.total", "departure", 3),
        ("summary.cancelled", "all", 3),
        ("summary.cancelled", "arrival", 1),
        ("summary.cancelled", "departure", 2),
        ("summary.delayed", "all", 1),
        ("summary.delayed", "arrival", 0),
        ("summary.delayed", "departure", 1),
        ("summary.not_cancelled", "all", 2),
        ("summary.not_cancelled", "arrival", 1),
        ("summary.not_cancelled", "departure", 1),
    ],
)
def test_ozet_yetim_kayitlari_saymaz(expected, name, direction, value):
    result = calc(expected, name, {"direction": direction})
    assert result == value
    assert type(result) is int


def test_ozet_sifir_bos_sonuc_degildir(expected):
    data = copy.deepcopy(DATA)
    data["delays"] = []
    assert calc(expected, "summary.delayed", {"direction": "all"}, data=data) == 0


@pytest.mark.parametrize("direction", ["ALL", "gelen", ""])
def test_ozet_enum_disi_yon_hatadir(expected, direction):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "summary.total", {"direction": direction})


# --- flight.field ---


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scheduled_time", t("12:00")),
        ("estimated_time", t("12:30")),
        ("registration", "TC-AAA"),
        ("callsign", "THY101"),
        ("aircraft_type", "A321"),
        ("origin", "XXXX"),
        ("destination", "VAN"),
        ("stand_code", "S2"),
        ("gate_code", "G2"),
        ("actual_block_time", t("12:31")),
        ("actual_runway_time", t("12:40")),
        ("delay_minutes", 30),
        ("delay_code", "93"),
        ("delay_category", "REACTIONARY"),
    ],
)
def test_ucus_alani_uc_tablodan_okunur(expected, field, value):
    params = {"flight_no": "TK101", "field": field}
    assert calc(expected, "flight.field", params) == value


def test_ucus_alani_sefer_no_tam_esitlikle_aranir(expected):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "flight.field", {"flight_no": "tk101", "field": "stand_code"})


@pytest.mark.parametrize(
    ("flight_no", "field"),
    [
        ("ZZ9999", "stand_code"),  # uçuş yok
        ("XQ1", "stand_code"),  # sefer no tekil değil
        ("TK0015", "stand_code"),  # iptal: kaynakta null
        ("TK100", "delay_minutes"),  # gecikme kaydı yok
        ("TK101", "status"),  # tanımsız alan
    ],
)
def test_ucus_alani_bos_sonuc_hatadir(expected, flight_no, field):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "flight.field", {"flight_no": flight_no, "field": field})


def test_ucus_alani_kaynakta_olmayan_anahtar_hatadir(expected):
    data = copy.deepcopy(DATA)
    del data["flights"][3]["estimated_time"]
    with pytest.raises(expected.ExpectedError):
        calc(
            expected,
            "flight.field",
            {"flight_no": "TK101", "field": "estimated_time"},
            data=data,
        )


def test_ucus_alani_yetim_kayittan_okunmaz(expected):
    data = without_flight("TK101")
    with pytest.raises(expected.ExpectedError):
        calc(
            expected,
            "flight.field",
            {"flight_no": "TK101", "field": "stand_code"},
            data=data,
        )


# --- on: eval / base ---


def test_on_verilmezse_eval_verisi_kullanilir(expected):
    data = without_flight("TK101")
    with pytest.raises(expected.ExpectedError):
        calc(
            expected,
            "flight.field",
            {"flight_no": "TK101", "field": "stand_code"},
            data=data,
            on="eval",
        )
    params = {"flight_no": "TK101", "field": "stand_code"}
    assert calc(expected, "flight.field", params, data=data, on="base") == "S2"


def test_on_base_bozulmadan_onceki_veriyi_kullanir(expected):
    data = copy.deepcopy(DATA)
    data["flights"] = data["flights"][:2]
    params = {"direction": "all"}
    assert calc(expected, "summary.total", params, data=data) == 2
    assert calc(expected, "summary.total", params, data=data, on="base") == 5


def test_on_bilinmeyen_deger_hatadir(expected):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "summary.total", {"direction": "all"}, on="ham")


# --- identity.candidates ---


def test_adaylar_tescille_flight_id_sirasiyla(expected):
    params = {"query": "TC-AAA", "field": "flight_no"}
    assert calc(expected, "identity.candidates", params) == ["TK100", "TK101"]


def test_adaylar_istenen_alani_dondurur(expected):
    params = {"query": "TC-AAA", "field": "gate_code"}
    assert calc(expected, "identity.candidates", params) == ["G1", "G2"]


def test_adaylar_kirpma_harf_ve_bastaki_sifir_yok_sayilir(expected):
    # THY0101 (XQ1) ve THY101 (TK101) callsign'ları sıfır kırpılınca eşittir.
    params = {"query": " thy101 ", "field": "flight_no"}
    assert calc(expected, "identity.candidates", params) == ["XQ1", "TK101"]


def test_adaylar_ayni_kayit_bir_kez_sayilir(expected):
    data = copy.deepcopy(DATA)
    data["flights"][2]["callsign"] = "TC-AAA"
    params = {"query": "TC-AAA", "field": "flight_no"}
    assert calc(expected, "identity.candidates", params, data=data) == [
        "TK100",
        "TK101",
    ]


def test_adaylar_tescilde_sifir_kirpilmaz(expected):
    data = copy.deepcopy(DATA)
    # Harf + rakam biçimi: sefer no'da sıfır kırpılırdı, tescilde kırpılmaz.
    data["flights"][2]["registration"] = "N01"
    data["flights"][3]["registration"] = "N1"
    data["flights"][4]["registration"] = "N1"
    params = {"query": "N01", "field": "flight_no"}
    with pytest.raises(expected.ExpectedError):
        calc(expected, "identity.candidates", params, data=data)


@pytest.mark.parametrize("query", ["TC-BBB", "TK10", "ZZ9999", "THY"])
def test_adaylar_ikiden_azsa_hatadir(expected, query):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "identity.candidates", {"query": query, "field": "flight_no"})


def test_adaylardan_birinde_alan_yoksa_hatadir(expected):
    # XQ1 iptal: gate_code null.
    with pytest.raises(expected.ExpectedError):
        calc(expected, "identity.candidates", {"query": "THY101", "field": "gate_code"})


# --- position.last / position.track_end ---


@pytest.mark.parametrize(
    ("field", "value"),
    [("ts", t("12:32")), ("lat", 41.2), ("lon", 28.72), ("phase", "TAXI_OUT")],
)
def test_son_konum_now_ve_oncesindeki_en_buyuk_ts(expected, field, value):
    params = {"flight_no": "TK101", "field": field}
    assert calc(expected, "position.last", params) == value


def test_son_konum_esit_ts_dahildir(expected):
    now = datetime.fromisoformat(t("12:31"))
    params = {"flight_no": "TK101", "field": "ts"}
    assert calc(expected, "position.last", params, now=now) == t("12:31")


def test_son_konum_ts_zaman_olarak_karsilastirilir(expected):
    # Aynı an UTC'de: 09:32:30Z = 12:32:30+03:00.
    now = datetime.fromisoformat("2026-10-20T09:32:30+00:00")
    params = {"flight_no": "TK101", "field": "ts"}
    assert calc(expected, "position.last", params, now=now) == t("12:32")


def test_son_konum_iz_baslamadiysa_hatadir(expected):
    now = datetime.fromisoformat(t("12:00"))
    with pytest.raises(expected.ExpectedError):
        calc(expected, "position.last", {"flight_no": "TK101", "field": "ts"}, now=now)


def test_son_konum_now_yoksa_hatadir(expected):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "position.last", {"flight_no": "TK101", "field": "ts"}, now=None)


def test_son_konum_tanimsiz_alan_hatadir(expected):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "position.last", {"flight_no": "TK101", "field": "speed"})


def test_iz_sonu_nowdan_bagimsizdir(expected):
    params = {"flight_no": "TK101"}
    assert calc(expected, "position.track_end", params, now=None) == t("12:33")
    early = datetime.fromisoformat(t("12:00"))
    assert calc(expected, "position.track_end", params, now=early) == t("12:33")


def test_iz_sonu_konumu_olmayan_ucusta_hatadir(expected):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "position.track_end", {"flight_no": "TK100"})


# --- flights.pick ---


def test_secim_iptalde_tekil_sefer_no_ilk_ucus(expected):
    # XQ1 iki kez geçtiği için atlanır.
    assert calc(expected, "flights.pick", {"cancelled": True}) == "TK0015"


def test_secim_iptal_olmayan_ilk_ucus(expected):
    assert calc(expected, "flights.pick", {"cancelled": False}) == "TK100"


def test_secim_uygun_ucus_yoksa_hatadir(expected):
    data = copy.deepcopy(DATA)
    for row in data["flights"]:
        row["cancelled"] = False
    with pytest.raises(expected.ExpectedError):
        calc(expected, "flights.pick", {"cancelled": True}, data=data)


def test_secim_mantiksal_olmayan_deger_hatadir(expected):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "flights.pick", {"cancelled": "true"})


# --- stands.codes ---


def test_stand_kodlari_hepsi(expected):
    assert calc(expected, "stands.codes") == ["S1", "S2", "S3"]


def test_stand_kodlari_bossa_hatadir(expected):
    data = copy.deepcopy(DATA)
    data["stands"] = []
    with pytest.raises(expected.ExpectedError):
        calc(expected, "stands.codes", data=data)


# --- Referans biçimi ---


def test_bilinmeyen_hesap_adi_hatadir(expected):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "summary.average", {"direction": "all"})


@pytest.mark.parametrize(
    "params",
    [{}, {"direction": "all", "airline": "TK"}],
)
def test_eksik_ya_da_fazla_param_hatadir(expected, params):
    with pytest.raises(expected.ExpectedError):
        calc(expected, "summary.total", params)


def test_hata_valueerror_alt_sinifi_ve_turkce(expected):
    assert issubclass(expected.ExpectedError, ValueError)
    with pytest.raises(expected.ExpectedError, match="Bilinmeyen hesap"):
        calc(expected, "summary.average", {"direction": "all"})


def test_tablodaki_tum_hesap_adlari_tanimli(expected):
    names = {
        "summary.total",
        "summary.cancelled",
        "summary.delayed",
        "summary.not_cancelled",
        "flight.field",
        "identity.candidates",
        "position.last",
        "position.track_end",
        "flights.pick",
        "stands.codes",
    }
    assert set(expected.CALC_NAMES) == names
