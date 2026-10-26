"""Tüketici deposu sözleşme testleri (docs/canli_akis.md › Tüketici › Depo, Bayatlık).

Testler koddan önce yazıldı; stream/consumer.py yokken hepsi kırmızıdır. Depo saf bir
sınıftır: mesajlar `apply(topic, payload)` ile doğrudan verilir, ağ ve sistem saati
kullanılmaz.
"""

import importlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT = "aocc/sim/v1"
TZ = timezone(timedelta(hours=3))

# TK2345'in sabit son konumu (docs/canli_akis.md › Ortak kurallar).
TK2345_KEY = "dc110c28"
TK2345_LAST = 1792502520


def load_consumer():
    # Modül yoksa her test ModuleNotFoundError ile kırmızı olur.
    return importlib.import_module("stream.consumer")


@pytest.fixture
def store():
    return load_consumer().PositionStore(ROOT)


def epoch(hh: int, mm: int, ss: int = 0) -> int:
    return int(datetime(2026, 10, 20, hh, mm, ss, tzinfo=TZ).timestamp())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ).isoformat()


def enc(record) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


def position(
    key: str = TK2345_KEY,
    ts: int = TK2345_LAST,
    flight: str = "TK2345",
    onground: bool = False,
    **fields,
) -> dict:
    return {
        "Key": key,
        "Latitude": 41.05,
        "Longitude": 28.4,
        "Track": 235,
        "Speed": 280,
        "Type": "A321",
        "Registration": "TC-LSD",
        "LastUpdate": ts,
        "Origin": "IST",
        "Destination": "VAN",
        "Flight": flight,
        "Onground": onground,
        "Callsign": "THY2345",
        **fields,
    }


def clock_body(ts: int, speed=60) -> dict:
    return {"now": iso(ts), "epoch": ts, "speed": speed}


def put_position(store, record: dict):
    return store.apply(f"{ROOT}/positions/{record['Key']}", enc(record))


def remove_position(store, key: str):
    return store.apply(f"{ROOT}/positions/{key}", b"")


def put_clock(store, ts: int):
    return store.apply(f"{ROOT}/clock", enc(clock_body(ts)))


def put_status(store, state: str):
    return store.apply(f"{ROOT}/status", enc({"state": state}))


def view(record: dict, now: int | None = None) -> dict:
    """Beklenen görünüm: kayıt aynen + final; saat varsa as_of, age_s, stale."""
    result = {**record, "final": record["Onground"] is True}
    if now is not None:
        age = now - record["LastUpdate"]
        result |= {
            "as_of": iso(now),
            "age_s": age,
            "stale": age > 300 and not result["final"],
        }
    return result


def clock_event(ts: int):
    return ("clock", clock_body(ts))


# --- Saat yokken / görünen nesneler ----------------------------------------------


def test_baslangic_snapshot_bos_ve_broker_yok(store):
    assert store.snapshot() == {
        "clock": None,
        "status": {"state": "broker_yok"},
        "positions": [],
    }


def test_saat_yokken_konum_gorunur_ve_bayatlik_yazilmaz(store):
    record = position()
    events = put_position(store, record)

    assert events == [("position", {**record, "final": False})]
    assert store.snapshot()["positions"] == [{**record, "final": False}]


def test_gelecek_konum_saklanir_saat_ulasinca_verilir(store):
    put_clock(store, epoch(16, 0))
    record = position(ts=epoch(16, 0, 30))

    assert put_position(store, record) == []
    assert store.snapshot()["positions"] == []

    events = put_clock(store, epoch(16, 0, 30))
    assert events == [
        clock_event(epoch(16, 0, 30)),
        ("position", view(record, epoch(16, 0, 30))),
    ]


def test_gelecek_konum_gelince_gosterilen_konum_saat_ulasana_dek_kalir(store):
    # Yayıncı adımın konumlarını o adımın saatinden önce yayınlar; yeni konum kısa
    # süre gelecektedir ve bu sırada uçak ekrandan düşmemelidir.
    put_clock(store, epoch(16, 0))
    current = position(ts=epoch(16, 0))
    put_position(store, current)
    upcoming = position(ts=epoch(16, 0, 30), Latitude=41.1)

    assert put_position(store, upcoming) == []
    assert store.snapshot()["positions"] == [view(current, epoch(16, 0))]
    assert put_clock(store, epoch(16, 0, 30)) == [
        clock_event(epoch(16, 0, 30)),
        ("position", view(upcoming, epoch(16, 0, 30))),
    ]
    assert store.snapshot()["positions"] == [view(upcoming, epoch(16, 0, 30))]


def test_saat_esitken_konum_gorunur(store):
    put_clock(store, TK2345_LAST)
    record = position()

    assert put_position(store, record) == [("position", view(record, TK2345_LAST))]


# --- Bayatlık ----------------------------------------------------------------------


def test_tk2345_162700de_guncel_162730da_bayat(store):
    put_clock(store, epoch(16, 22))
    record = position()
    put_position(store, record)

    # 16:27:00: yaş 300, eşiğe eşit, bayat değil; stale olayı yok.
    assert put_clock(store, epoch(16, 27)) == [clock_event(epoch(16, 27))]
    [shown] = store.snapshot()["positions"]
    assert (shown["age_s"], shown["stale"]) == (300, False)

    # 16:27:30: yaş 330, bayata geçiş; tek stale olayı.
    expected = view(record, epoch(16, 27, 30))
    assert expected["stale"] is True
    assert put_clock(store, epoch(16, 27, 30)) == [
        clock_event(epoch(16, 27, 30)),
        ("stale", expected),
    ]

    # Sonraki saatlerde yeniden stale olayı çıkmaz; konum silinmez.
    assert put_clock(store, epoch(16, 28)) == [clock_event(epoch(16, 28))]
    [shown] = store.snapshot()["positions"]
    assert shown == view(record, epoch(16, 28))
    assert shown["stale"] is True


def test_yeni_konum_bayatligi_sifirlar_ve_gecis_yeniden_bildirilir(store):
    put_clock(store, epoch(16, 0))
    put_position(store, position(ts=epoch(16, 0)))
    put_clock(store, epoch(16, 5, 30))  # bayat

    fresh = position(ts=epoch(16, 5, 30), Latitude=41.1)
    assert put_position(store, fresh) == [("position", view(fresh, epoch(16, 5, 30)))]

    events = put_clock(store, epoch(16, 11))
    assert events == [clock_event(epoch(16, 11)), ("stale", view(fresh, epoch(16, 11)))]


def test_bayat_konum_ilk_gorundugunde_position_olayi_stale_true_tasir(store):
    put_clock(store, epoch(16, 30))
    record = position()  # 16:22, yaş 480

    assert put_position(store, record) == [("position", view(record, epoch(16, 30)))]
    assert put_clock(store, epoch(16, 30, 30)) == [clock_event(epoch(16, 30, 30))]


# --- Final kuralı --------------------------------------------------------------------


def test_final_konum_bayat_olmaz_ve_stale_olayi_uretmez(store):
    put_clock(store, epoch(16, 0))
    record = position(ts=epoch(16, 0), onground=True)
    put_position(store, record)

    assert put_clock(store, epoch(16, 10)) == [clock_event(epoch(16, 10))]
    [shown] = store.snapshot()["positions"]
    assert shown["final"] is True
    assert shown["stale"] is False
    assert shown["age_s"] == 600


def test_final_konumun_degil_o_anki_konumun_ozelligidir(store):
    put_clock(store, epoch(16, 1))
    taxi = position(ts=epoch(16, 0), onground=True)
    airborne = position(ts=epoch(16, 1), onground=False)

    put_position(store, taxi)
    events = put_position(store, airborne)

    assert events == [("position", view(airborne, epoch(16, 1)))]
    assert events[0][1]["final"] is False


# --- Son bilinen konum --------------------------------------------------------------


def test_eski_lastupdate_atilir(store):
    put_clock(store, epoch(16, 30))
    newer = position(ts=epoch(16, 22))
    put_position(store, newer)

    assert put_position(store, position(ts=epoch(16, 21), Latitude=40.0)) == []
    assert store.snapshot()["positions"] == [view(newer, epoch(16, 30))]


def test_esit_lastupdate_yerine_gecer(store):
    put_clock(store, epoch(16, 30))
    put_position(store, position())
    same_time = position(Latitude=41.06)

    assert put_position(store, same_time) == [
        ("position", view(same_time, epoch(16, 30)))
    ]
    assert store.snapshot()["positions"] == [view(same_time, epoch(16, 30))]


def test_gorunen_konum_silinince_removed_cikar(store):
    put_clock(store, epoch(16, 30))
    put_position(store, position())

    assert remove_position(store, TK2345_KEY) == [("removed", {"Key": TK2345_KEY})]
    assert store.snapshot()["positions"] == []


def test_hic_gorunmemis_konum_silinince_olay_cikmaz(store):
    put_clock(store, epoch(16, 0))
    put_position(store, position())  # gelecekte

    assert remove_position(store, TK2345_KEY) == []
    assert remove_position(store, "ffffffff") == []
    # Silinen gelecek konum saat gelince de görünmez.
    assert put_clock(store, epoch(16, 30)) == [clock_event(epoch(16, 30))]


def test_silindikten_sonra_eski_konum_yeniden_kabul_edilir(store):
    put_clock(store, epoch(16, 30))
    put_position(store, position())
    remove_position(store, TK2345_KEY)
    older = position(ts=epoch(16, 0))

    assert put_position(store, older) == [("position", view(older, epoch(16, 30)))]


# --- Saat çapası --------------------------------------------------------------------


def test_geri_giden_saat_atilir(store):
    put_clock(store, epoch(16, 22))

    assert put_clock(store, epoch(16, 21)) == []
    assert store.snapshot()["clock"] == clock_body(epoch(16, 22))


def test_esit_saat_kabul_edilir_ve_clock_olayi_cikar(store):
    put_clock(store, epoch(16, 22))

    assert put_clock(store, epoch(16, 22)) == [clock_event(epoch(16, 22))]


def test_saat_ilerleyince_olaylar_clocktan_sonra_flight_key_sirasiyla(store):
    put_clock(store, epoch(16, 0))
    stale_soon = position(key="00000001", ts=epoch(16, 0), flight="TK3")
    future_b = position(key="0000000b", ts=epoch(16, 6), flight="TK1")
    future_a = position(key="0000000a", ts=epoch(16, 6), flight="TK1")
    future_c = position(key="0000000c", ts=epoch(16, 6), flight="TK2")
    for record in (stale_soon, future_b, future_a, future_c):
        put_position(store, record)

    now = epoch(16, 6)
    assert put_clock(store, now) == [
        clock_event(now),
        ("position", view(future_a, now)),
        ("position", view(future_b, now)),
        ("position", view(future_c, now)),
        ("stale", view(stale_soon, now)),
    ]


def test_saat_durumdan_bagimsiz_islenir(store):
    put_status(store, "bitti")

    assert put_clock(store, epoch(16, 22)) == [clock_event(epoch(16, 22))]


# --- Durum --------------------------------------------------------------------------


def test_durum_degisince_olay_ayni_durumda_olay_yok(store):
    assert put_status(store, "yayinda") == [("status", {"state": "yayinda"})]
    assert put_status(store, "yayinda") == []
    assert put_status(store, "bitti") == [("status", {"state": "bitti"})]
    assert store.snapshot()["status"] == {"state": "bitti"}


def test_broker_kopunca_broker_yok_ve_konumlar_korunur(store):
    put_status(store, "yayinda")
    put_clock(store, epoch(16, 22))
    put_position(store, position())

    assert store.broker_lost() == [("status", {"state": "broker_yok"})]
    assert store.broker_lost() == []
    snapshot = store.snapshot()
    assert snapshot["status"] == {"state": "broker_yok"}
    assert snapshot["positions"] == [view(position(), epoch(16, 22))]


# --- Snapshot ve görünüm -------------------------------------------------------------


def test_snapshot_flight_key_sirali(store):
    records = [
        position(key="0000000b", flight="TK9"),
        position(key="0000000c", flight="TK1"),
        position(key="0000000a", flight="TK1"),
    ]
    for record in records:
        put_position(store, record)

    keys = [p["Key"] for p in store.snapshot()["positions"]]
    assert keys == ["0000000a", "0000000c", "0000000b"]


def test_gorunum_kaydi_degistirmez_yalnizca_dort_alan_ekler(store):
    put_clock(store, epoch(16, 23))
    record = position()
    [(_, shown)] = put_position(store, record)

    assert {k: shown[k] for k in record} == record
    assert set(shown) - set(record) == {"as_of", "age_s", "stale", "final"}
    assert (shown["as_of"], shown["age_s"]) == ("2026-10-20T16:23:00+03:00", 60)


def test_donen_gorunum_degistirilse_de_depo_etkilenmez(store):
    put_clock(store, epoch(16, 23))
    [(_, shown)] = put_position(store, position())
    shown["Latitude"] = 0.0
    store.snapshot()["positions"][0]["Latitude"] = 0.0

    assert store.snapshot()["positions"][0]["Latitude"] == 41.05


# --- Uçuş kayıtları ------------------------------------------------------------------


def test_ucus_kaydi_saklanir_olay_uretmez_bos_govde_siler(store):
    flight = {"_id": "TK_2345_20261020_DEPARTURE", "flight_number": "TK2345"}
    topic = f"{ROOT}/flights/{flight['_id']}"

    assert store.apply(topic, enc(flight)) == []
    assert store.flights == {flight["_id"]: flight}
    assert store.apply(topic, b"") == []
    assert store.flights == {}


# --- Mesaj doğrulama -----------------------------------------------------------------


def _without(record: dict, key: str) -> dict:
    return {k: v for k, v in record.items() if k != key}


LATER_CLOCK = clock_body(epoch(17, 0))

INVALID = [
    ("konum-utf8-degil", f"{ROOT}/positions/{TK2345_KEY}", b"\xff\xfe"),
    ("konum-json-degil", f"{ROOT}/positions/{TK2345_KEY}", b"{bozuk"),
    ("konum-nesne-degil", f"{ROOT}/positions/{TK2345_KEY}", b"[1, 2]"),
    ("konum-key-uyusmaz", f"{ROOT}/positions/ffffffff", enc(position())),
    (
        "konum-key-yok",
        f"{ROOT}/positions/{TK2345_KEY}",
        enc(_without(position(), "Key")),
    ),
    (
        "konum-lastupdate-yok",
        f"{ROOT}/positions/{TK2345_KEY}",
        enc(_without(position(), "LastUpdate")),
    ),
    (
        "konum-lastupdate-metin",
        f"{ROOT}/positions/{TK2345_KEY}",
        enc(position(ts="16:22")),
    ),
    (
        "konum-lastupdate-bool",
        f"{ROOT}/positions/{TK2345_KEY}",
        enc(position(ts=True)),
    ),
    (
        "ucus-id-uyusmaz",
        f"{ROOT}/flights/TK_1_20261020_ARRIVAL",
        enc({"_id": "TK_2_20261020_ARRIVAL"}),
    ),
    # Saat örnekleri ileri bir an taşır; geri giden saat kuralıyla atılmış olmasınlar.
    ("saat-bos", f"{ROOT}/clock", b""),
    ("saat-epoch-metin", f"{ROOT}/clock", enc({**LATER_CLOCK, "epoch": "1"})),
    ("saat-epoch-bool", f"{ROOT}/clock", enc({**LATER_CLOCK, "epoch": True})),
    ("saat-now-yok", f"{ROOT}/clock", enc(_without(LATER_CLOCK, "now"))),
    ("saat-speed-metin", f"{ROOT}/clock", enc({**LATER_CLOCK, "speed": "60"})),
    ("durum-bilinmiyor", f"{ROOT}/status", enc({"state": "baska"})),
    ("durum-broker-yok-yayinlanamaz", f"{ROOT}/status", enc({"state": "broker_yok"})),
    ("durum-bos", f"{ROOT}/status", b""),
    ("kok-disi", f"aocc/live/v1/positions/{TK2345_KEY}", enc(position())),
    ("bilinmeyen-topic", f"{ROOT}/weather", enc({"x": 1})),
    ("eksik-seviye", f"{ROOT}/positions", enc(position())),
]


@pytest.mark.parametrize(
    ("topic", "payload"),
    [case[1:] for case in INVALID],
    ids=[case[0] for case in INVALID],
)
def test_gecersiz_mesaj_atilir_durum_degismez(store, topic, payload):
    put_status(store, "yayinda")
    put_clock(store, epoch(16, 30))
    before = store.snapshot()

    assert store.apply(topic, payload) == []
    assert store.snapshot() == before
    assert store.flights == {}


# --- Saflık ---------------------------------------------------------------------------


def test_depo_ag_ve_sistem_saati_kullanmaz():
    load_consumer()
    source = (REPO_ROOT / "stream" / "consumer.py").read_text(encoding="utf-8")
    forbidden = [
        r"\bimport\s+(time|socket|paho)\b",
        r"\bfrom\s+(time|socket|paho)\b",
        r"\.now\(",
        r"\.today\(",
        r"perf_counter|monotonic",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, source), f"Yasak kullanım: {pattern}"
