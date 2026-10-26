"""Canlı akış testleri: tüketici başlatma, LiveHub ve GET /live/positions.

Sözleşme docs/canli_akis.md › Tüketici › Başlatma ve SSE. Testler koddan önce yazıldı;
backend/live.py yokken kırmızıdır. Ağa çıkılmaz: paho bağlantısı
`backend.live.connect_mqtt` yerine sahte fabrikayla verilir, mesajlar hub'a doğrudan
(paho gibi ayrı thread'den) beslenir. Akış kesmesi TestClient'la yapılamadığı için SSE
ASGI ile sürülür (test_audit.py › drive_chat deseni).
"""

import asyncio
import importlib
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect

from backend import main
from stream.consumer import PositionStore

ROOT = "aocc/sim/v1"
TZ = timezone(timedelta(hours=3))
URL_VAR = "COPILOT_MQTT_URL"
ROOT_VAR = "COPILOT_MQTT_ROOT"
DRIVE_TIMEOUT_S = 5


def load_live():
    # Modül yoksa her test ModuleNotFoundError ile kırmızı olur.
    return importlib.import_module("backend.live")


def epoch(hh: int, mm: int, ss: int = 0) -> int:
    return int(datetime(2026, 10, 20, hh, mm, ss, tzinfo=TZ).timestamp())


def enc(record) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


def position(key="dc110c28", ts=None, flight="TK2345") -> dict:
    return {
        "Key": key,
        "Latitude": 41.05,
        "Longitude": 28.4,
        "LastUpdate": epoch(16, 22) if ts is None else ts,
        "Flight": flight,
        "Onground": False,
        "Callsign": "ŞÇ2345",
    }


def clock_msg(ts: int) -> tuple[str, bytes]:
    now = datetime.fromtimestamp(ts, TZ).isoformat()
    return (f"{ROOT}/clock", enc({"now": now, "epoch": ts, "speed": 60}))


def pos_msg(record: dict) -> tuple[str, bytes]:
    return (f"{ROOT}/positions/{record['Key']}", enc(record))


class FakeHandle:
    def __init__(self):
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeConnect:
    def __init__(self):
        self.calls: list[tuple] = []
        self.handles: list[FakeHandle] = []

    def __call__(self, host, port, root, hub):
        self.calls.append((host, port, root, hub))
        handle = FakeHandle()
        self.handles.append(handle)
        return handle


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Gerçek .env ve ortam değeri testlere sızmasın; paho asla çağrılmasın."""
    monkeypatch.delenv(URL_VAR, raising=False)
    monkeypatch.delenv(ROOT_VAR, raising=False)
    live = load_live()
    monkeypatch.setattr(live, "ENV_FILE", tmp_path / "yok.env")


@pytest.fixture
def fake_connect(monkeypatch):
    fake = FakeConnect()
    monkeypatch.setattr(load_live(), "connect_mqtt", fake)
    return fake


# --- Başlatma -----------------------------------------------------------------------


def test_url_yoksa_tuketici_baslamaz_ve_endpoint_503(fake_connect):
    with TestClient(main.app) as client:
        assert fake_connect.calls == []
        assert main.app.state.live is None
        response = client.get("/live/positions")
        assert client.get("/health").status_code == 200

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.json() == {"detail": main.LIVE_UNAVAILABLE_MESSAGE}


def test_url_ortamdan_okunur_ve_kapanista_durur(fake_connect, monkeypatch):
    monkeypatch.setenv(URL_VAR, "mqtt://broker.local:1999")

    with TestClient(main.app):
        assert len(fake_connect.calls) == 1
        host, port, root, hub = fake_connect.calls[0]
        assert (host, port, root) == ("broker.local", 1999, ROOT)
        assert isinstance(hub, load_live().LiveHub)
        assert main.app.state.live is hub
        assert not fake_connect.handles[0].stopped

    assert fake_connect.handles[0].stopped
    assert main.app.state.live is None


def test_port_verilmezse_1883(fake_connect, monkeypatch):
    monkeypatch.setenv(URL_VAR, "mqtt://127.0.0.1")

    with TestClient(main.app):
        assert fake_connect.calls[0][:2] == ("127.0.0.1", 1883)


def test_kok_ortamdan_okunur(fake_connect, monkeypatch):
    monkeypatch.setenv(URL_VAR, "mqtt://127.0.0.1:1883")
    monkeypatch.setenv(ROOT_VAR, "aocc/live/v1")

    with TestClient(main.app):
        assert fake_connect.calls[0][2] == "aocc/live/v1"


def test_ortam_bossa_env_dosyasindan_okunur_ortama_yazilmaz(
    fake_connect, monkeypatch, tmp_path
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{URL_VAR}=mqtt://10.0.0.9:1884\n{ROOT_VAR}=x/y\n", encoding="utf-8"
    )
    monkeypatch.setattr(load_live(), "ENV_FILE", env_file)

    with TestClient(main.app):
        assert fake_connect.calls[0][:3] == ("10.0.0.9", 1884, "x/y")
    assert URL_VAR not in os.environ


def test_ortam_degeri_env_dosyasini_ezer(fake_connect, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"{URL_VAR}=mqtt://10.0.0.9:1884\n", encoding="utf-8")
    monkeypatch.setattr(load_live(), "ENV_FILE", env_file)
    monkeypatch.setenv(URL_VAR, "mqtt://10.0.0.5:1883")

    with TestClient(main.app):
        assert fake_connect.calls[0][:2] == ("10.0.0.5", 1883)


@pytest.mark.parametrize("url", ["http://127.0.0.1:1883", "mqtt://", "mqtt://h:port"])
def test_gecersiz_urlde_sunucu_acilir_tuketici_baslamaz(
    fake_connect, monkeypatch, caplog, url
):
    monkeypatch.setenv(URL_VAR, url)

    with caplog.at_level(logging.ERROR), TestClient(main.app) as client:
        assert fake_connect.calls == []
        assert client.get("/live/positions").status_code == 503
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


# --- LiveHub ------------------------------------------------------------------------


def feed_in_thread(hub, messages: list[tuple[str, bytes]]) -> None:
    """paho gibi ayrı bir thread'den besler."""
    thread = threading.Thread(
        target=lambda: [hub.handle_message(t, p) for t, p in messages]
    )
    thread.start()
    thread.join()


def test_hub_olaylari_tum_abonelere_dagitir():
    live = load_live()

    async def scenario():
        hub = live.LiveHub(ROOT)
        _, first = hub.subscribe()
        _, second = hub.subscribe()
        assert hub.subscriber_count == 2
        feed_in_thread(hub, [clock_msg(epoch(16, 22))])
        got = [
            await asyncio.wait_for(queue.get(), DRIVE_TIMEOUT_S)
            for queue in (first, second)
        ]
        hub.unsubscribe(first)
        hub.unsubscribe(second)
        return got, hub.subscriber_count

    got, remaining = asyncio.run(scenario())
    expected = PositionStore(ROOT).apply(*clock_msg(epoch(16, 22)))
    assert len(expected) == 1
    assert got == [expected[0], expected[0]]
    assert remaining == 0


def test_hub_kopus_durumu_degistirir():
    live = load_live()
    hub = live.LiveHub(ROOT)
    hub.handle_message(f"{ROOT}/status", enc({"state": "yayinda"}))
    hub.handle_disconnect()

    async def scenario():
        snapshot, _ = hub.subscribe()
        return snapshot

    assert asyncio.run(scenario())["status"] == {"state": "broker_yok"}


# --- SSE ----------------------------------------------------------------------------


def asgi_scope() -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/live/positions",
        "raw_path": b"/live/positions",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"test")],
        "client": ("test", 1),
        "server": ("test", 80),
    }


def parse_sse(text: str) -> list[tuple[str, object]]:
    """Olayları (ad, data) ve yorumları ("comment", metin) olarak döndürür."""
    items = []
    for block in text.split("\n\n"):
        if not block:
            continue
        if block.startswith(":"):
            items.append(("comment", block[1:].strip()))
            continue
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        items.append((lines["event"], json.loads(lines["data"])))
    return items


async def drive_live(*, until, after_snapshot=None) -> tuple[str, dict]:
    """GET /live/positions'ı ASGI ile sürer; until(öğeler) doğru olunca istemci gider.

    after_snapshot verilirse snapshot gönderildikten sonra ayrı thread'de çalışır.
    Uvicorn gibi (ASGI 2.4) kopan istemcide send OSError fırlatır.
    """
    gone = asyncio.Event()
    chunks: list[str] = []
    start: dict = {}
    fed = False

    async def receive() -> dict:
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        nonlocal fed
        if gone.is_set():
            raise OSError("istemci bağlantıyı kesti")
        if message["type"] == "http.response.start":
            start.update(message)
            return
        body = message.get("body", b"")
        if not body:
            return
        chunks.append(body.decode("utf-8"))
        items = parse_sse("".join(chunks))
        if after_snapshot is not None and not fed and items:
            fed = True
            threading.Thread(target=after_snapshot).start()
        if until(items):
            gone.set()
            raise OSError("istemci bağlantıyı kesti")

    try:
        await asyncio.wait_for(main.app(asgi_scope(), receive, send), DRIVE_TIMEOUT_S)
    except (OSError, ClientDisconnect):
        # Starlette ASGI 2.4'te send'in OSError'ını ClientDisconnect'e çevirir.
        pass
    return "".join(chunks), start


@pytest.fixture
def hub(monkeypatch):
    live = load_live()
    created = live.LiveHub(ROOT)
    monkeypatch.setattr(main.app.state, "live", created, raising=False)
    return created


def events_only(items):
    return [item for item in items if item[0] != "comment"]


def test_ilk_olay_snapshot_ve_basliklar(hub):
    expected = PositionStore(ROOT)
    for message in (clock_msg(epoch(16, 23)), pos_msg(position())):
        hub.handle_message(*message)
        expected.apply(*message)

    text, start = asyncio.run(drive_live(until=lambda items: len(items) >= 1))

    headers = dict(start["headers"])
    assert start["status"] == 200
    assert headers[b"content-type"] == b"text/event-stream; charset=utf-8"
    items = parse_sse(text)
    assert items[0] == ("snapshot", expected.snapshot())
    assert len(items[0][1]["positions"]) == 1
    assert "ŞÇ2345" in text, "data ensure_ascii=False yazılmalı"


def test_snapshottan_sonra_olaylar_depodaki_sirayla_iletilir(hub):
    hub.handle_message(*clock_msg(epoch(16, 0)))
    future = position(ts=epoch(16, 0, 30))
    later = [
        (f"{ROOT}/status", enc({"state": "yayinda"})),
        pos_msg(future),
        clock_msg(epoch(16, 0, 30)),
        (f"{ROOT}/positions/{future['Key']}", b""),
    ]
    expected_store = PositionStore(ROOT)
    expected_store.apply(*clock_msg(epoch(16, 0)))
    expected = [e for m in later for e in expected_store.apply(*m)]
    assert [name for name, _ in expected] == ["status", "clock", "position", "removed"]

    text, _ = asyncio.run(
        drive_live(
            after_snapshot=lambda: feed_in_thread(hub, later),
            until=lambda items: len(events_only(items)) >= 1 + len(expected),
        )
    )

    items = events_only(parse_sse(text))
    assert items[0][0] == "snapshot"
    assert items[1:] == expected


def test_olay_yoksa_ping_yorumu_gider(hub, monkeypatch):
    monkeypatch.setattr(main, "LIVE_PING_INTERVAL_S", 0.05)

    text, _ = asyncio.run(
        drive_live(until=lambda items: any(i == ("comment", "ping") for i in items))
    )

    assert ": ping\n\n" in text


def test_ping_araligi_15_saniye():
    assert main.LIVE_PING_INTERVAL_S == 15


def test_istemci_gidince_abonelik_birakilir(hub):
    asyncio.run(drive_live(until=lambda items: len(items) >= 1))

    assert hub.subscriber_count == 0


def test_broker_kopunca_yalnizca_durum_gider(hub):
    hub.handle_message(f"{ROOT}/status", enc({"state": "yayinda"}))

    text, _ = asyncio.run(
        drive_live(
            after_snapshot=hub.handle_disconnect,
            until=lambda items: len(events_only(items)) >= 2,
        )
    )

    items = events_only(parse_sse(text))
    assert items[1] == ("status", {"state": "broker_yok"})
