"""Radar biçimli referans günü simüle saatle MQTT'ye yayınlar (docs/canli_akis.md › Yayıncı).

Repo kökünden çalıştırın:
    python -m stream.publisher --in data/referans/seed42-2026-10-20-radar.json \
        --from HH:MM [--speed 60 | --interval 2] [--no-wait] \
        [--broker mqtt://127.0.0.1:1883] [--root aocc/sim/v1]

Yayınlanan mesajların içeriği ve sırası yalnızca --in ve --from'dan türer; --speed /
--interval, --no-wait ve sistem saati yalnızca yayın anını etkiler. Konum ve saat
mesajları yayınlandıktan sonra stdout'a `<topic> <gövde>` olarak yazılır; özet ve
hatalar stderr'dedir. Broker'a bağlanan kısım
`main(connect=...)` ile değiştirilebilir; testler sahte istemci verir.
"""

import argparse
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from stream import messages
from stream.messages import Message
from synth.stream import StreamError, load_input, parse_day, parse_from, parse_speed

BROKER_ENV = "COPILOT_MQTT_URL"
DEFAULT_BROKER = "mqtt://127.0.0.1:1883"
DEFAULT_SPEED = 60.0
# Topic seviyesine giren değer ayraç ve joker karakter içeremez.
TOPIC_PART_RE = re.compile(r"^[^/+#\s]+$")
CONNECT_TIMEOUT_S = 10
PUBLISH_TIMEOUT_S = 10


class PublisherError(Exception):
    """Girdi ya da argüman geçersiz; mesaj kullanıcıya gösterilir."""


class Client(Protocol):
    def publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> None: ...

    def disconnect(self) -> None: ...


Connect = Callable[[str, int, Message], Client]


class MqttClient:
    """paho istemcisini sarar.

    QoS 0 yayını sokete yazılana kadar beklenir. QoS 1 onayı (PUBACK) tek tek
    beklenmez: her biri ~150 ms sürdüğü için 600 uçuş akışı ~1 dk geciktiriyordu.
    Onaylar kapanıştan önce toplu beklenir; tek bağlantıda sıra MQTT'de korunur.
    """

    def __init__(self, client: mqtt.Client):
        self._client = client
        self._pending: list[mqtt.MQTTMessageInfo] = []

    def publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(mqtt.error_string(info.rc))
        if qos > 0:
            self._pending.append(info)
            return
        info.wait_for_publish(timeout=PUBLISH_TIMEOUT_S)
        if not info.is_published():
            raise ConnectionError("Yayın zaman aşımına uğradı.")

    def disconnect(self) -> None:
        # Bekleyen QoS 1 mesajları (son durum dahil) gönderilmeden kapatılmaz.
        for info in self._pending:
            info.wait_for_publish(timeout=PUBLISH_TIMEOUT_S)
        # Temiz kapanış: broker LWT'yi yayınlamaz.
        self._client.disconnect()
        self._client.loop_stop()


def connect_mqtt(host: str, port: int, will: Message) -> MqttClient:
    client = mqtt.Client(CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.will_set(will.topic, will.payload, will.qos, will.retain)
    connected = threading.Event()
    result = {}

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        result["reason_code"] = reason_code
        connected.set()

    client.on_connect = on_connect
    client.connect(host, port)
    client.loop_start()
    if not connected.wait(CONNECT_TIMEOUT_S) or result["reason_code"].is_failure:
        client.loop_stop()
        raise ConnectionError("Broker bağlantıyı kabul etmedi.")
    return MqttClient(client)


def parse_broker(value: str) -> tuple[str, int]:
    try:
        return messages.parse_broker_url(value)
    except ValueError as error:
        raise PublisherError(f"--broker {error}") from None


def topic_part(value, label: str) -> str:
    if not isinstance(value, str) or not TOPIC_PART_RE.match(value):
        raise PublisherError(f"Geçersiz {label}: {value!r}")
    return value


def read_flights(data: dict) -> list[dict]:
    flights = data.get("flights")
    if not isinstance(flights, list):
        raise PublisherError("Girdide flights listesi yok.")
    for record in flights:
        if not isinstance(record, dict):
            raise PublisherError(f"Geçersiz uçuş kaydı: {record!r}")
        topic_part(record.get("_id"), "uçuş _id'si")
    return flights


def read_positions(data: dict) -> list[dict]:
    positions = data.get("positions")
    if not isinstance(positions, list):
        raise PublisherError("Girdide positions listesi yok.")
    for record in positions:
        if not isinstance(record, dict):
            raise PublisherError(f"Geçersiz konum kaydı: {record!r}")
        topic_part(record.get("Key"), "konum Key'i")
        last_update = record.get("LastUpdate")
        if not isinstance(last_update, int) or isinstance(last_update, bool):
            raise PublisherError(f"Konumda tamsayı LastUpdate yok: {record!r}")
    return positions


def plan_steps(positions: list[dict], start: int) -> list[tuple[int, list[dict]]]:
    """30 sn'lik adımlar: her adımda (önceki adım, adım] aralığına düşen konumlar.

    Adım 0 tam --from anıdır; --from'dan önceki konumlar hiçbir adıma girmez. Son adım
    son konumu içeren adımdır; konum yoksa yalnızca adım 0 vardır.
    """
    selected = sorted(
        (record for record in positions if record["LastUpdate"] >= start),
        key=lambda record: (record["LastUpdate"], record["Key"]),
    )
    steps = []
    index = 0
    step = start
    while True:
        batch = []
        while index < len(selected) and selected[index]["LastUpdate"] <= step:
            batch.append(selected[index])
            index += 1
        steps.append((step, batch))
        if index == len(selected):
            return steps
        step += messages.CLOCK_STEP_S


class Progress:
    def __init__(self):
        self.published = 0
        self.first_clock = "-"
        self.last_clock = "-"


def send(client: Client, message: Message) -> None:
    client.publish(message.topic, message.payload, message.qos, message.retain)


def send_and_echo(client: Client, message: Message) -> None:
    """Yayınlar, ardından stdout'a `<topic> <gövde>` yazar (mosquitto_sub -v biçimi).

    Satır yayın başarılı olduktan sonra yazılır; byte olarak yazıldığı için konsol
    kodlamasından bağımsız UTF-8 kalır.
    """
    send(client, message)
    out = sys.stdout.buffer
    out.write(message.topic.encode("utf-8") + b" " + message.payload + b"\n")
    out.flush()


def parse_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError:
        raise PublisherError(f"--interval bir sayı olmalı: {value}") from None
    # nan da bu kontrolden geçemez.
    if not interval > 0:
        raise PublisherError("--interval 0'dan büyük olmalı.")
    return interval


def resolve_speed(speed: str | None, interval: str | None) -> float:
    """--interval N, --speed 30/N'e denktir; ikisi birlikte verilemez."""
    if interval is None:
        return parse_speed(speed if speed is not None else str(DEFAULT_SPEED))
    if speed is not None:
        raise PublisherError("--speed ve --interval birlikte verilemez.")
    return messages.CLOCK_STEP_S / parse_interval(interval)


def stream_steps(
    client: Client,
    root: str,
    steps: list[tuple[int, list[dict]]],
    speed: float,
    wait: bool,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    progress: Progress,
) -> None:
    start = steps[0][0]
    started = monotonic()
    for step, batch in steps:
        if wait:
            # Hedef an başlangıçtan hesaplanır; bekleme süreleri toplanmadığı için
            # kayma birikmez (synth.stream ile aynı).
            delay = started + (step - start) / speed - monotonic()
            if delay > 0:
                sleep(delay)
        for record in batch:
            send_and_echo(client, messages.position(root, record))
            progress.published += 1
        send_and_echo(client, messages.clock(root, step, speed))
        now = datetime.fromtimestamp(step, messages.TZ).isoformat()
        if progress.first_clock == "-":
            progress.first_clock = now
        progress.last_clock = now


def main(
    argv: list[str] | None = None,
    connect: Connect = connect_mqtt,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.perf_counter,
) -> int:
    parser = argparse.ArgumentParser(
        description="Radar biçimli konumları simüle saatle MQTT'ye yayınlar."
    )
    parser.add_argument("--in", dest="input", help="Radar biçimli referans dosya")
    parser.add_argument("--from", dest="start", help="Simüle başlangıç saati, HH:MM")
    parser.add_argument(
        "--speed", help=f"Simüle sn / gerçek sn (varsayılan {DEFAULT_SPEED:g})"
    )
    parser.add_argument(
        "--interval", help="İki 30 sn'lik adım arasındaki gerçek sn (= --speed 30/N)"
    )
    parser.add_argument("--no-wait", action="store_true", help="Beklemeden yayınla")
    parser.add_argument("--broker", help=f"mqtt://host:port (varsayılan {BROKER_ENV})")
    parser.add_argument("--root", default=messages.DEFAULT_ROOT, help="Topic kökü")
    args = parser.parse_args(argv)

    # Tüm doğrulama bağlantıdan önce yapılır; hata durumunda hiçbir mesaj yayınlanmaz.
    try:
        if not args.input:
            raise PublisherError("--in verilmeli.")
        broker = args.broker or os.environ.get(BROKER_ENV, "") or DEFAULT_BROKER
        host, port = parse_broker(broker)
        data = load_input(args.input)
        day = parse_day(data)
        start = parse_from(args.start, day)
        speed = resolve_speed(args.speed, args.interval)
        flights = read_flights(data)
        positions = read_positions(data)
    except (StreamError, PublisherError) as error:
        print(f"Hata: {error}", file=sys.stderr)
        return 1

    root = args.root
    # Önceki koşunun konumları kalmasın diye girdideki tüm Key'ler temizlenir.
    keys = sorted({record["Key"] for record in positions})
    steps = plan_steps(positions, int(start.timestamp()))

    try:
        client = connect(host, port, messages.status(root, messages.STATE_LOST))
    except OSError as error:
        print(f"Hata: Broker'a bağlanılamadı ({host}:{port}): {error}", file=sys.stderr)
        return 1

    progress = Progress()
    code = 0
    try:
        for key in keys:
            send(client, messages.position_clear(root, key))
        send(
            client,
            messages.status(
                root,
                messages.STATE_ON,
                source=args.input,
                date=day.isoformat(),
                **{"from": args.start},
            ),
        )
        for record in flights:
            send(client, messages.flight(root, record))
        stream_steps(
            client, root, steps, speed, not args.no_wait, sleep, monotonic, progress
        )
    except KeyboardInterrupt:
        code = 130
    except OSError as error:
        # Bağlantı koptuysa durumu broker LWT ile koptu olarak yazar.
        print(
            f"Hata: Yayın sırasında broker bağlantısı koptu: {error}", file=sys.stderr
        )
        return 1

    send(client, messages.status(root, messages.STATE_DONE))
    client.disconnect()
    print(
        f"yayınlanan={progress.published} ilk={progress.first_clock} "
        f"son={progress.last_clock}",
        file=sys.stderr,
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
