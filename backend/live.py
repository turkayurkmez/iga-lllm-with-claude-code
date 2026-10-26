"""Canlı konum tüketicisi: paho aboneliği ve SSE dağıtımı.

Sözleşme docs/canli_akis.md › Tüketici › Başlatma. Durum `stream.consumer.PositionStore`'da
tutulur; bu modül depoyu paho thread'i ile SSE istemcileri (asyncio) arasında paylaştırır.
`start()` COPILOT_MQTT_URL boşsa hiçbir şey başlatmaz. Testler `connect_mqtt`'i sahte
fabrikayla değiştirir; böylece ağa çıkılmaz.
"""

import asyncio
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Protocol

import paho.mqtt.client as mqtt
from dotenv import dotenv_values
from paho.mqtt.enums import CallbackAPIVersion

from backend import clock
from stream import messages
from stream.consumer import Event, PositionStore

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
URL_VAR = "COPILOT_MQTT_URL"
ROOT_VAR = "COPILOT_MQTT_ROOT"
RECONNECT_MIN_S = 1
RECONNECT_MAX_S = 30


def read_setting(name: str) -> str:
    """Önce süreç ortamı, boşsa .env; .env ortama yazılmaz."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return (dotenv_values(ENV_FILE).get(name) or "").strip()


class LiveHub:
    """Depoyu kilitle sarar; olayları SSE abonelerinin kuyruklarına dağıtır.

    Mesajlar paho thread'inden gelir; kuyruklara her abonenin event loop'u üzerinden
    yazılır. Dağıtım kilit altında yapıldığı için abonenin aldığı snapshot ile
    kuyruğuna düşen ilk olay arasında olay kaçmaz.
    """

    def __init__(self, root: str):
        self._store = PositionStore(root)
        self._lock = threading.Lock()
        self._subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def subscribe(self) -> tuple[dict, asyncio.Queue]:
        """Çalışan event loop içinde çağrılır; (snapshot, olay kuyruğu) döner."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers[queue] = loop
            return self._store.snapshot(), queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.pop(queue, None)

    def sim_now(self) -> datetime | None:
        """Son clock.epoch'un +03:00 anı; saat mesajı yoksa None."""
        with self._lock:
            clock_message = self._store.clock
        if clock_message is None:
            return None
        return datetime.fromtimestamp(clock_message["epoch"], clock.TZ)

    def positions_for_flight(self, flight_no: str) -> list[dict]:
        """Görünür konumlardan Flight'ı flight_no olanlar (kopya)."""
        with self._lock:
            records = self._store.shown_records()
        return [record for record in records if record.get("Flight") == flight_no]

    def handle_message(self, topic: str, payload: bytes) -> None:
        with self._lock:
            self._dispatch(self._store.apply(topic, payload))

    def handle_disconnect(self) -> None:
        with self._lock:
            self._dispatch(self._store.broker_lost())

    def _dispatch(self, events: list[Event]) -> None:
        if not events:
            return
        for queue, loop in list(self._subscribers.items()):
            try:
                for event in events:
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                # Abonenin event loop'u kapanmış; kuyruğu okuyan kalmadı.
                self._subscribers.pop(queue, None)


class Handle(Protocol):
    def stop(self) -> None: ...


class MqttSubscriber:
    """paho aboneliği: <kök>/# (QoS 1), kopuşta 1–30 sn arayla yeniden bağlanır."""

    def __init__(self, host: str, port: int, root: str, hub: LiveHub):
        self._root = root
        self._hub = hub
        client = mqtt.Client(CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.reconnect_delay_set(RECONNECT_MIN_S, RECONNECT_MAX_S)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        # connect_async: broker o an yoksa açılış beklemez; loop thread'i yeniden dener.
        client.connect_async(host, port)
        client.loop_start()
        self._client = client

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            logger.error("Broker bağlantıyı reddetti: %s", reason_code)
            return
        logger.info("Broker'a bağlanıldı; %s/# dinleniyor.", self._root)
        client.subscribe(f"{self._root}/#", qos=1)

    def _on_message(self, _client, _userdata, message) -> None:
        # Callback'teki istisna paho thread'ini durdurur; depo istisna fırlatmasa da korunur.
        try:
            self._hub.handle_message(message.topic, message.payload)
        except Exception:
            logger.exception("Canlı konum mesajı işlenemedi.")

    def _on_disconnect(
        self, _client, _userdata, _flags, reason_code, _properties
    ) -> None:
        logger.warning("Broker bağlantısı koptu: %s", reason_code)
        self._hub.handle_disconnect()


# Canlı mod: lifespan tüketiciyi başlatınca açılır (docs/canli_akis.md › Canlı mod ve
# tool'lar). Tool'lar ve operasyonel saat buradan okur.
_active: LiveHub | None = None


def activate(hub: LiveHub) -> None:
    global _active
    _active = hub
    clock.set_simulated_source(hub.sim_now)


def deactivate() -> None:
    global _active
    _active = None
    clock.set_simulated_source(None)


def active() -> LiveHub | None:
    return _active


def connect_mqtt(host: str, port: int, root: str, hub: LiveHub) -> Handle:
    return MqttSubscriber(host, port, root, hub)


def start() -> tuple[LiveHub, Handle] | None:
    """COPILOT_MQTT_URL doluysa tüketiciyi başlatır; boş ya da geçersizse None."""
    url = read_setting(URL_VAR)
    if not url:
        return None
    try:
        host, port = messages.parse_broker_url(url)
    except ValueError:
        logger.exception("%s geçersiz; canlı konum tüketicisi başlatılmadı.", URL_VAR)
        return None
    root = read_setting(ROOT_VAR) or messages.DEFAULT_ROOT
    hub = LiveHub(root)
    # Fabrika çağrı anında modülden okunur; testler onu değiştirebilsin.
    handle = connect_mqtt(host, port, root, hub)
    logger.info("Canlı konum tüketicisi başlatıldı: %s:%s, kök %s", host, port, root)
    return hub, handle
