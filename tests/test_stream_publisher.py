"""Yayıncı sözleşme testleri (docs/canli_akis.md › Yayıncı).

Testler koddan önce yazıldı; stream/publisher.py yokken hepsi kırmızıdır. Broker'a
bağlanan kısım `main(argv, connect=..., sleep=..., monotonic=...)` ile enjekte edilir:
testler sahte broker ve sahte saatle süreç içinde çalışır, ağa çıkmaz, gerçekten
beklemez.
"""

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "data" / "referans" / "seed42-2026-10-20-radar.json"
ROOT = "aocc/sim/v1"
TZ = timezone(timedelta(hours=3))
DAY = "2026-10-20"

# TK2345'in sabit son konumu (docs/canli_akis.md › Ortak kurallar).
TK2345_KEY = "dc110c28"
TK2345_LAST = 1792502520


def load_publisher():
    # Modül yoksa her test ModuleNotFoundError ile kırmızı olur.
    return importlib.import_module("stream.publisher")


def epoch(hh: int, mm: int, ss: int = 0) -> int:
    return int(datetime(2026, 10, 20, hh, mm, ss, tzinfo=TZ).timestamp())


def body(record) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


class FakeTime:
    """Sahte monoton saat; sleep zamanı ilerletir, her yayın `publish_cost` sürer."""

    def __init__(self, publish_cost: float = 0.0, interrupt_on_sleep: int = 0):
        self.now = 0.0
        self.sleeps: list[float] = []
        self.publish_cost = publish_cost
        self.interrupt_on_sleep = interrupt_on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if len(self.sleeps) == self.interrupt_on_sleep:
            raise KeyboardInterrupt
        self.now += seconds


class FakeBroker:
    """connect() sahte istemciyi döndürür; yayınları zamanlarıyla kaydeder."""

    def __init__(
        self,
        clock: FakeTime,
        fail: Exception | None = None,
        fail_publish_at: int | None = None,
    ):
        self.clock = clock
        self.fail = fail
        # Bu sıradaki (0'dan) yayın OSError fırlatır ve kaydedilmez.
        self.fail_publish_at = fail_publish_at
        self.publish_calls = 0
        self.connect_calls: list[tuple] = []
        self.messages: list[tuple[str, bytes, int, bool]] = []
        self.times: list[float] = []
        self.disconnected = False

    def connect(self, host: str, port: int, will):
        self.connect_calls.append((host, port, tuple(will)))
        if self.fail is not None:
            raise self.fail
        return self

    def publish(self, topic: str, payload: bytes, qos: int, retain: bool) -> None:
        assert not self.disconnected, "Bağlantı kapandıktan sonra yayın yapıldı"
        call = self.publish_calls
        self.publish_calls += 1
        if call == self.fail_publish_at:
            raise ConnectionResetError(10054, "reset")
        self.messages.append((topic, payload, qos, retain))
        self.times.append(self.clock.now)
        self.clock.now += self.clock.publish_cost

    def disconnect(self) -> None:
        self.disconnected = True


class Run:
    def __init__(self, code, broker, clock, out, err):
        self.code = code
        self.broker = broker
        self.clock = clock
        self.out = out
        self.err = err

    @property
    def messages(self):
        return self.broker.messages

    def topics(self, kind: str) -> list[tuple[str, bytes, int, bool]]:
        prefix = f"{ROOT}/{kind}"
        return [m for m in self.messages if m[0].startswith(prefix)]


@pytest.fixture(autouse=True)
def no_env_broker(monkeypatch):
    monkeypatch.delenv("COPILOT_MQTT_URL", raising=False)


@pytest.fixture
def run(capsys):
    def _run(args, clock=None, fail=None, fail_publish_at=None):
        publisher = load_publisher()
        clock = clock or FakeTime()
        broker = FakeBroker(clock, fail, fail_publish_at)
        code = publisher.main(
            args, connect=broker.connect, sleep=clock.sleep, monotonic=clock.monotonic
        )
        captured = capsys.readouterr()
        return Run(code, broker, clock, captured.out, captured.err)

    return _run


def position(key: str, ts: int, flight: str = "TK1") -> dict:
    return {
        "Key": key,
        "Latitude": 41.05,
        "Longitude": 28.4,
        "Track": 235,
        "Speed": 280,
        "Type": "A321",
        "Registration": "TC-ŞĞÜ",
        "LastUpdate": ts,
        "Origin": "IST",
        "Destination": "VAN",
        "Flight": flight,
        "Onground": False,
        "Callsign": "THY1",
    }


FLIGHTS = [
    {"_id": "TK_2_20261020_ARRIVAL", "flight_number": "TK2", "origin_iata": "İZM"},
    {"_id": "TK_1_20261020_DEPARTURE", "flight_number": "TK1"},
]

# --from 10:00 için: 09:59:30 süzülür, 10:00:10 hizasızdır, 10:00:30'da iki kayıt
# ters Key sırasıyla verilmiştir, 10:01:00 adımı konumsuzdur.
POSITIONS = [
    position("bbbb0001", epoch(9, 59, 30)),
    position("aaaa0001", epoch(10, 0, 0)),
    position("aaaa0001", epoch(10, 0, 10)),
    position("cccc0001", epoch(10, 0, 30), "TK2"),
    position("aaaa0001", epoch(10, 0, 30)),
    position("cccc0001", epoch(10, 1, 30), "TK2"),
]


def write_input(tmp_path: Path, data: dict | str, name: str = "radar.json") -> Path:
    path = tmp_path / name
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def small_input(tmp_path) -> Path:
    data = {"meta": {"date": DAY}, "flights": FLIGHTS, "positions": POSITIONS}
    return write_input(tmp_path, data)


def clock_msg(ts: int, speed=60) -> tuple[str, bytes, int, bool]:
    now = datetime.fromtimestamp(ts, TZ).isoformat()
    return (f"{ROOT}/clock", body({"now": now, "epoch": ts, "speed": speed}), 0, True)


def pos_msg(record: dict) -> tuple[str, bytes, int, bool]:
    return (f"{ROOT}/positions/{record['Key']}", body(record), 0, True)


def decoded(messages) -> list[tuple[str, object, int, bool]]:
    """Gövdeleri JSON olarak çözer; sayı biçimi (60 / 60.0) karşılaştırmayı bozmaz."""
    return [(t, json.loads(p) if p else None, q, r) for t, p, q, r in messages]


# --- Akış ---------------------------------------------------------------------


def test_kucuk_girdide_mesaj_sirasi_sozlesmedeki_gibi(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    assert result.code == 0, result.err
    clears = [
        (f"{ROOT}/positions/{key}", b"", 0, True)
        for key in ("aaaa0001", "bbbb0001", "cccc0001")
    ]
    status_on = (
        f"{ROOT}/status",
        body(
            {
                "state": "yayinda",
                "source": str(small_input),
                "date": DAY,
                "from": "10:00",
            }
        ),
        1,
        True,
    )
    flights = [(f"{ROOT}/flights/{f['_id']}", body(f), 1, True) for f in FLIGHTS]
    p = POSITIONS
    steps = [
        pos_msg(p[1]),
        clock_msg(epoch(10, 0, 0)),
        pos_msg(p[2]),
        pos_msg(p[4]),
        pos_msg(p[3]),
        clock_msg(epoch(10, 0, 30)),
        clock_msg(epoch(10, 1, 0)),
        pos_msg(p[5]),
        clock_msg(epoch(10, 1, 30)),
    ]
    status_off = (f"{ROOT}/status", body({"state": "bitti"}), 1, True)
    expected = [*clears, status_on, *flights, *steps, status_off]
    assert decoded(result.messages) == decoded(expected)
    assert result.broker.disconnected


def test_lwt_koptu_olarak_baglanirken_verilir(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    assert len(result.broker.connect_calls) == 1
    _, _, will = result.broker.connect_calls[0]
    topic, payload, qos, retain = will
    assert (topic, json.loads(payload), qos, retain) == (
        f"{ROOT}/status",
        {"state": "koptu"},
        1,
        True,
    )


def test_konum_ve_ucus_govdesi_kaynak_kaydin_kendisidir(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    positions = [m for m in result.topics("positions") if m[1]]
    flights = result.topics("flights")
    assert len(positions) == 5
    assert len(flights) == 2
    for topic, payload, _, _ in positions:
        record = json.loads(payload.decode("utf-8"))
        assert payload == body(record), "Gövde ensure_ascii=False, tek satır olmalı"
        assert record in POSITIONS
        assert topic == f"{ROOT}/positions/{record['Key']}"
    for topic, payload, _, _ in flights:
        record = json.loads(payload.decode("utf-8"))
        assert payload == body(record)
        assert topic == f"{ROOT}/flights/{record['_id']}"
    assert "TC-ŞĞÜ".encode() in positions[0][1]


def test_from_oncesindeki_konum_yayinlanmaz_ama_temizlenir(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    bbbb = [m for m in result.messages if m[0] == f"{ROOT}/positions/bbbb0001"]
    assert bbbb == [(f"{ROOT}/positions/bbbb0001", b"", 0, True)]


def test_konum_yoksa_tek_saat_ve_bitti_yazilir(run, small_input):
    result = run(["--in", str(small_input), "--from", "11:00", "--no-wait"])

    assert result.code == 0, result.err
    assert [m for m in result.topics("positions") if m[1]] == []
    tail = decoded(result.messages[-2:])
    assert tail == decoded(
        [clock_msg(epoch(11, 0)), (f"{ROOT}/status", body({"state": "bitti"}), 1, True)]
    )


def test_root_verilince_tum_topicler_onun_altindadir(run, small_input):
    result = run(
        ["--in", str(small_input), "--from", "10:00", "--no-wait", "--root", "x/y"]
    )

    assert result.code == 0, result.err
    assert result.messages
    assert all(m[0].startswith("x/y/") for m in result.messages)
    assert result.broker.connect_calls[0][2][0] == "x/y/status"


def test_stdout_konum_ve_saat_mesajlarini_topic_govde_olarak_basar(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    assert result.code == 0, result.err
    printed = [
        m
        for m in result.messages
        if (m[0].startswith(f"{ROOT}/positions/") and m[1]) or m[0] == f"{ROOT}/clock"
    ]
    assert len(printed) == 9
    expected = [
        f"{topic} {payload.decode('utf-8')}" for topic, payload, _, _ in printed
    ]
    assert result.out.splitlines() == expected
    assert "TC-ŞĞÜ" in result.out, "Gövde ensure_ascii=False basılmalı"


def test_yayinlanamayan_mesaj_stdouta_basilmaz(run, small_input):
    # Yayın sırası: 3 temizlik, durum, 2 uçuş, ilk konum (6. sıra) başarısız olur.
    result = run(
        ["--in", str(small_input), "--from", "10:00", "--no-wait"], fail_publish_at=6
    )

    assert result.code == 1
    assert result.err.startswith("Hata: "), result.err
    assert result.out == ""


def test_ozet_stderrde_tek_satirdir(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    assert result.err.splitlines() == [
        "yayınlanan=5 ilk=2026-10-20T10:00:00+03:00 son=2026-10-20T10:01:30+03:00"
    ]


# --- Referans veri ------------------------------------------------------------


def test_referansta_tk2345_son_konumu_1622dir(run):
    before = REFERENCE.read_bytes()
    result = run(["--in", str(REFERENCE), "--from", "16:00", "--no-wait"])

    assert result.code == 0, result.err
    data = json.loads(before)
    tk = [m for m in result.messages if m[0] == f"{ROOT}/positions/{TK2345_KEY}"]
    assert tk[0][1] == b"", "Önce retained temizlenmeli"
    last = json.loads(tk[-1][1])
    assert last["Flight"] == "TK2345"
    assert last["LastUpdate"] == TK2345_LAST
    expected = [p for p in data["positions"] if p["LastUpdate"] >= epoch(16, 0)]
    published = [m for m in result.topics("positions") if m[1]]
    assert len(published) == len(expected)
    assert len(result.topics("flights")) == len(data["flights"])
    assert REFERENCE.read_bytes() == before, "Girdi yalnızca okunmalı"


# --- Belirlenimcilik ve bekleme -----------------------------------------------


def test_bekleme_icerigi_ve_sirayi_degistirmez(run, small_input):
    args = ["--in", str(small_input), "--from", "10:00"]
    waited = run(args)
    fast = run([*args, "--no-wait"])

    assert waited.code == fast.code == 0
    assert waited.messages == fast.messages


def test_hiz_yalnizca_saat_mesajinin_speed_alanini_degistirir(run, small_input):
    args = ["--in", str(small_input), "--from", "10:00", "--no-wait"]
    slow = decoded(run([*args, "--speed", "60"]).messages)
    fast = decoded(run([*args, "--speed", "1.5"]).messages)

    clocks = [i for i, m in enumerate(slow) if m[0] == f"{ROOT}/clock"]
    assert len(clocks) == 4
    for i in clocks:
        assert slow[i][1]["speed"] == 60
        assert fast[i][1]["speed"] == 1.5
        fast[i][1]["speed"] = 60
    assert slow == fast


def test_adim_ani_baslangictan_hesaplanir_kayma_birikmez(run, small_input):
    # Başlangıç, adım 0'ın başladığı andır (temizlik, durum ve uçuş yayınlarından sonra;
    # bunlar simüle saati kaydırmaz). Her yayın 0.01 sn sürse de adım i'nin ilk yayını
    # başlangıç + (adım − from) / speed anındadır; bekleme süreleri toplansaydı yayın
    # maliyeti her adımda birikirdi.
    clock = FakeTime(publish_cost=0.01)
    result = run(
        ["--in", str(small_input), "--from", "10:00", "--speed", "60"], clock=clock
    )

    assert result.code == 0, result.err
    clock_times = [
        t
        for m, t in zip(result.messages, result.broker.times, strict=True)
        if m[0] == f"{ROOT}/clock"
    ]
    # 3 temizlik + durum + 2 uçuş 0.06'da biter: başlangıç = 0.06.
    # Adım 0 hemen: 1 konum + saat (0.07). Adım 1 0.56'da: 3 konum + saat;
    # adım 2 1.06'da: yalnız saat; adım 3 1.56'da: konum + saat.
    assert clock_times == pytest.approx([0.07, 0.59, 1.06, 1.57])
    assert result.clock.sleeps == pytest.approx([0.48, 0.46, 0.49])


def test_interval_adimlari_sabit_gercek_saniyeyle_ayirir(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--interval", "2"])

    assert result.code == 0, result.err
    assert result.clock.sleeps == pytest.approx([2.0, 2.0, 2.0])


def test_interval_saat_mesajina_turetilen_hizi_yazar(run, small_input):
    args = ["--in", str(small_input), "--from", "10:00", "--no-wait"]
    by_interval = decoded(run([*args, "--interval", "2"]).messages)
    by_speed = decoded(run([*args, "--speed", "15"]).messages)

    clocks = [m for m in by_interval if m[0] == f"{ROOT}/clock"]
    assert len(clocks) == 4
    assert all(m[1]["speed"] == 15 for m in clocks)
    assert by_interval == by_speed


def test_no_wait_hic_beklemez(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    assert result.code == 0, result.err
    assert result.clock.sleeps == []


def test_ctrl_c_de_bitti_yazilir_ve_baglanti_kapanir(run, small_input):
    clock = FakeTime(interrupt_on_sleep=1)
    result = run(["--in", str(small_input), "--from", "10:00"], clock=clock)

    assert result.code == 130
    assert decoded(result.messages[-1:]) == decoded(
        [(f"{ROOT}/status", body({"state": "bitti"}), 1, True)]
    )
    assert result.broker.disconnected


# --- Broker adresi --------------------------------------------------------------


def test_broker_varsayilani_yerel_1883(run, small_input):
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    assert result.broker.connect_calls[0][:2] == ("127.0.0.1", 1883)


def test_broker_ortamdan_okunur(run, small_input, monkeypatch):
    monkeypatch.setenv("COPILOT_MQTT_URL", "mqtt://host.docker.internal:2883")
    result = run(["--in", str(small_input), "--from", "10:00", "--no-wait"])

    assert result.broker.connect_calls[0][:2] == ("host.docker.internal", 2883)


def test_broker_argumani_ortami_ezer(run, small_input, monkeypatch):
    monkeypatch.setenv("COPILOT_MQTT_URL", "mqtt://host.docker.internal:2883")
    args = ["--in", str(small_input), "--from", "10:00", "--no-wait"]
    result = run([*args, "--broker", "mqtt://10.0.0.5:1884"])

    assert result.broker.connect_calls[0][:2] == ("10.0.0.5", 1884)


# --- Hatalar ------------------------------------------------------------------


def assert_failed(result) -> None:
    assert result.code == 1
    assert result.err.startswith("Hata: "), result.err
    assert result.broker.connect_calls == [], "Hatalı girdide broker'a bağlanılmamalı"
    assert result.messages == []
    assert result.out == "", "Hata durumunda stdout boş kalmalı"


@pytest.mark.parametrize(
    "extra",
    [
        ["--interval", "0"],
        ["--interval", "-2"],
        ["--interval", "abc"],
        ["--interval", "2", "--speed", "60"],
        ["--from", "25:00"],
        ["--from", "9:00"],
        ["--speed", "0"],
        ["--speed", "-1"],
        ["--speed", "nan"],
        ["--speed", "abc"],
        ["--broker", "http://127.0.0.1:1883"],
        ["--broker", "mqtt://127.0.0.1:port"],
    ],
)
def test_gecersiz_argumanda_baglanilmaz(run, small_input, extra):
    args = ["--in", str(small_input), "--from", "10:00", "--no-wait"]
    result = run([*args, *extra])

    assert_failed(result)


def test_in_yoksa_hata(run):
    assert_failed(run(["--from", "10:00"]))


def test_dosya_yoksa_hata(run, tmp_path):
    assert_failed(run(["--in", str(tmp_path / "yok.json"), "--from", "10:00"]))


def test_json_degilse_hata(run, tmp_path):
    path = write_input(tmp_path, "{bozuk")
    assert_failed(run(["--in", str(path), "--from", "10:00"]))


def without(record: dict, key: str) -> dict:
    return {k: v for k, v in record.items() if k != key}


@pytest.mark.parametrize(
    "data",
    [
        {"meta": {}, "flights": FLIGHTS, "positions": POSITIONS},
        {"meta": {"date": "2026-13-40"}, "flights": FLIGHTS, "positions": POSITIONS},
        {"meta": {"date": DAY}, "flights": FLIGHTS},
        {"meta": {"date": DAY}, "positions": POSITIONS},
        {
            "meta": {"date": DAY},
            "flights": FLIGHTS,
            "positions": [*POSITIONS, without(POSITIONS[1], "Key")],
        },
        {
            "meta": {"date": DAY},
            "flights": FLIGHTS,
            "positions": [*POSITIONS, without(POSITIONS[1], "LastUpdate")],
        },
        {
            "meta": {"date": DAY},
            "flights": FLIGHTS,
            "positions": [*POSITIONS, {**POSITIONS[1], "LastUpdate": "10:00"}],
        },
        {
            "meta": {"date": DAY},
            "flights": FLIGHTS,
            "positions": [*POSITIONS, {**POSITIONS[1], "Key": "a/b"}],
        },
        {
            "meta": {"date": DAY},
            "flights": [*FLIGHTS, {"flight_number": "TK9"}],
            "positions": POSITIONS,
        },
    ],
    ids=[
        "meta-date-yok",
        "meta-date-gecersiz",
        "flights-yok",
        "positions-yok",
        "key-yok",
        "lastupdate-yok",
        "lastupdate-tamsayi-degil",
        "key-topic-ayiraci",
        "ucus-id-yok",
    ],
)
def test_gecersiz_girdide_baglanilmaz(run, tmp_path, data):
    path = write_input(tmp_path, data)
    assert_failed(run(["--in", str(path), "--from", "10:00", "--no-wait"]))


def test_baglanamazsa_hata_ve_yayin_yok(run, small_input):
    result = run(
        ["--in", str(small_input), "--from", "10:00", "--no-wait"],
        fail=ConnectionRefusedError(10061, "refused"),
    )

    assert result.code == 1
    assert result.err.startswith("Hata: "), result.err
    assert len(result.broker.connect_calls) == 1
    assert result.messages == []
