"""Canlı mod ve tool'lar (docs/canli_akis.md › Canlı mod ve tool'lar, docs/tools.md).

Testler koddan önce yazıldı. Canlı depo `backend.live.LiveHub`'a mesajlar doğrudan
verilerek kurulur; ağa çıkılmaz. Kapalı moddaki davranış tests/test_tools.py'de de
sınanır; buradaki kapalı mod testleri karşılaştırma için tutulur.
"""

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import clock, main
from backend.tools import run_tool

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "data" / "referans" / "seed42-2026-10-20.json"
ROOT = "aocc/sim/v1"
TZ = timezone(timedelta(hours=3))
TK2345_ID = "FL-20261020-0270"
NOW = "2026-10-20T16:22:00+03:00"


def load_live():
    return importlib.import_module("backend.live")


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 10, 20, hh, mm, ss, tzinfo=TZ)


def epoch(hh: int, mm: int, ss: int = 0) -> int:
    return int(at(hh, mm, ss).timestamp())


def enc(record) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


def live_position(key="dc110c28", ts=None, flight="TK2345", **fields) -> dict:
    record = {
        "Key": key,
        "Latitude": 40.5,
        "Longitude": 29.0,
        "Track": 90,
        "Speed": 250,
        "LastUpdate": epoch(16, 10) if ts is None else ts,
        "Flight": flight,
        "Onground": False,
    }
    return record | fields


def put_position(hub, record: dict) -> None:
    hub.handle_message(f"{ROOT}/positions/{record['Key']}", enc(record))


def put_clock(hub, ts: int) -> None:
    now = datetime.fromtimestamp(ts, TZ).isoformat()
    hub.handle_message(f"{ROOT}/clock", enc({"now": now, "epoch": ts, "speed": 60}))


def details() -> dict:
    envelope = run_tool("get_flight_details", {"flight_id": TK2345_ID})
    assert envelope["error"] is None, envelope["error"]
    return envelope


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.setenv("COPILOT_DATA", str(REFERENCE))
    monkeypatch.setenv("COPILOT_NOW", NOW)
    yield
    # Bir testte açılan canlı mod sonrakine taşınmasın.
    load_live().deactivate()


@pytest.fixture
def hub():
    live = load_live()
    created = live.LiveHub(ROOT)
    live.activate(created)
    return created


# --- Operasyonel saat ---------------------------------------------------------------


def test_kapali_modda_operasyonel_saat_now_ile_ayni():
    assert load_live().active() is None
    assert clock.operational_now() == clock.now() == at(16, 22)


def test_canli_modda_saat_simule_an_audit_saati_degismez(hub):
    put_clock(hub, epoch(16, 10))

    assert clock.operational_now() == at(16, 10)
    assert clock.operational_now().utcoffset() == timedelta(hours=3)
    # Audit clock.now() kullanır; gerçek (burada COPILOT_NOW) saatte kalır.
    assert clock.now() == at(16, 22)


def test_canli_modda_saat_mesaji_yoksa_now(hub):
    assert clock.operational_now() == at(16, 22)


def test_canli_modda_zarfin_as_ofu_simule_an(hub):
    put_clock(hub, epoch(16, 10))

    assert details()["as_of"] == "2026-10-20T16:10:00+03:00"


def test_deactivate_sonrasi_eski_davranis(hub):
    put_clock(hub, epoch(16, 10))
    put_position(hub, live_position())
    load_live().deactivate()

    assert clock.operational_now() == at(16, 22)
    position = details()["value"]["position"]
    assert position["ts"] == NOW
    assert "phase" in position, "Kapalı modda konum dosyadan gelmeli"


# --- get_flight_details konumu ------------------------------------------------------


def test_kapali_modda_konum_dosyadan():
    position = details()["value"]["position"]

    assert position["ts"] == NOW
    assert "phase" in position


def test_canli_modda_konum_depodan_eslenir(hub):
    put_clock(hub, epoch(16, 10))
    put_position(hub, live_position())

    envelope = details()

    assert envelope["value"]["position"] == {
        "ts": "2026-10-20T16:10:00+03:00",
        "lat": 40.5,
        "lon": 29.0,
        "heading_deg": 90,
        "speed_kt": 250,
    }
    assert envelope["value"]["flight_no"] == "TK2345"


def test_canli_modda_eslesen_kayit_yoksa_konum_yok_dosyaya_dusulmez(hub):
    put_clock(hub, epoch(16, 22))
    put_position(hub, live_position(key="aaaa0001", flight="TK9999"))

    value = details()["value"]

    assert "position" not in value
    assert value["flight_no"] == "TK2345"
    assert value["stand_code"] == "R236"


def test_canli_modda_ayni_seferde_en_yeni_kayit(hub):
    put_clock(hub, epoch(16, 10))
    put_position(hub, live_position(key="aaaa0001", ts=epoch(16, 8), Latitude=41.0))
    put_position(hub, live_position(key="aaaa0002", ts=epoch(16, 5), Latitude=42.0))

    position = details()["value"]["position"]

    assert position["ts"] == "2026-10-20T16:08:00+03:00"
    assert position["lat"] == 41.0


def test_canli_modda_gelecek_kayit_kullanilmaz(hub):
    put_clock(hub, epoch(16, 0))
    put_position(hub, live_position(ts=epoch(16, 0)))
    put_position(hub, live_position(ts=epoch(16, 0, 30), Latitude=41.9))

    position = details()["value"]["position"]

    assert position["ts"] == "2026-10-20T16:00:00+03:00"
    assert position["lat"] == 40.5


def test_saat_mesaji_yokken_operasyonel_saatten_sonraki_kayit_kullanilmaz(
    hub, monkeypatch
):
    monkeypatch.setenv("COPILOT_NOW", "2026-10-20T16:05:00+03:00")
    # Saat yokken depo her konumu görünür sayar; seçim operasyonel saate göre yapılır.
    put_position(hub, live_position(key="aaaa0001", ts=epoch(16, 4)))
    put_position(hub, live_position(key="aaaa0002", ts=epoch(16, 10)))

    position = details()["value"]["position"]

    assert position["ts"] == "2026-10-20T16:04:00+03:00"


def test_canli_kayitta_olmayan_alan_yazilmaz(hub):
    put_clock(hub, epoch(16, 10))
    record = live_position()
    del record["Track"], record["Speed"]
    put_position(hub, record)

    position = details()["value"]["position"]

    assert position == {"ts": "2026-10-20T16:10:00+03:00", "lat": 40.5, "lon": 29.0}


def test_canli_modda_bayat_konum_da_ts_ile_verilir(hub):
    put_clock(hub, epoch(16, 30))
    put_position(hub, live_position(ts=epoch(16, 22)))

    envelope = details()

    assert envelope["value"]["position"]["ts"] == NOW
    assert envelope["as_of"] == "2026-10-20T16:30:00+03:00"
    assert envelope["stale"] is False


# --- Lifespan ----------------------------------------------------------------------


class FakeHandle:
    def stop(self) -> None:
        pass


def test_lifespan_canli_modu_acip_kapatir(monkeypatch, tmp_path):
    live = load_live()
    monkeypatch.setattr(live, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.setattr(live, "connect_mqtt", lambda *args: FakeHandle())
    monkeypatch.setenv("COPILOT_MQTT_URL", "mqtt://127.0.0.1:1883")
    monkeypatch.delenv("COPILOT_MQTT_ROOT", raising=False)

    with TestClient(main.app):
        assert live.active() is not None
        assert live.active() is main.app.state.live

    assert live.active() is None
    assert clock.operational_now() == at(16, 22)


def test_lifespan_url_yoksa_canli_mod_kapali(monkeypatch, tmp_path):
    live = load_live()
    monkeypatch.setattr(live, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.delenv("COPILOT_MQTT_URL", raising=False)

    with TestClient(main.app):
        assert live.active() is None
