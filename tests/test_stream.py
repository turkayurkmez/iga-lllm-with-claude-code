"""Akış komutu sözleşme testleri (docs/bozulma.md › Akış).

Testler komuttan önce yazıldı; synth/stream.py yokken hepsi kırmızıdır (hata testleri de
modülün var olmasını ön koşul sayar). Komut yazılırken bu testler gevşetilmez.

stdout byte olarak okunur ve beklenen byte'larla birebir karşılaştırılır.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SEED = 42
DATE = "2026-10-20"
TARGET_FLIGHT_NO = "TK2345"

# Bekleme toleransları (sn): erken yazım neredeyse hiç kabul edilmez; geç yazımda süreç ve
# boru gecikmesine pay bırakılır.
EARLY_TOLERANCE = 0.05
LATE_TOLERANCE = 0.5


def env(hash_seed: str = "0") -> dict:
    return {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONIOENCODING": "utf-8"}


def run_module(
    module: str, args: list[str], hash_seed: str = "0", timeout: float = 120
):
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        check=False,
        cwd=REPO_ROOT,
        env=env(hash_seed),
        capture_output=True,
        timeout=timeout,
    )


def stream(input_path: Path, *args: str, hash_seed: str = "0", timeout: float = 120):
    return run_module(
        "synth.stream",
        ["--in", str(input_path), *args],
        hash_seed=hash_seed,
        timeout=timeout,
    )


def stderr_text(result) -> str:
    return result.stderr.decode("utf-8", errors="replace")


def assert_ok(result) -> None:
    assert result.returncode == 0, f"Komut başarısız oldu:\n{stderr_text(result)}"


def assert_failed(result) -> None:
    # Ön koşul: modül var; aksi halde "modül yok" hatası bu testi yanlış nedenle geçirir.
    assert importlib.util.find_spec("synth.stream") is not None, (
        "synth.stream modülü yok"
    )
    assert result.returncode != 0, "Hata bekleniyordu"
    assert result.stdout == b"", "Hata durumunda stdout'a hiç satır yazılmamalı"
    assert stderr_text(result).strip(), "stderr'de neden yazmalı"


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def from_time(day: str, hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}:00+03:00")


def line(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")


def expected_stream(positions: list[dict], start: datetime) -> bytes:
    selected = [p for p in positions if parse_ts(p["ts"]) >= start]
    selected.sort(key=lambda p: (parse_ts(p["ts"]), p["flight_id"]))
    return b"".join(line(p) for p in selected)


def position(flight_id: str, ts: str, **extra) -> dict:
    record = {
        "flight_id": flight_id,
        "ts": ts,
        "lat": 41.26,
        "lon": 28.74,
        "heading_deg": 90.0,
        "speed_kt": 15.0,
        "phase": "TAXI_IN",
    }
    record.update(extra)
    return record


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def small_input(tmp_path: Path, positions: list[dict], day: str = DATE) -> Path:
    return write_json(
        tmp_path / "girdi.json", {"meta": {"date": day}, "positions": positions}
    )


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> dict:
    path = tmp_path_factory.mktemp("kaynak") / f"{SEED}-{DATE}.json"
    result = run_module(
        "synth.generator", ["--seed", str(SEED), "--date", DATE, "--out", str(path)]
    )
    assert result.returncode == 0, f"Üreteç başarısız oldu:\n{stderr_text(result)}"
    return {"path": path, "data": json.loads(path.read_text(encoding="utf-8"))}


def corrupted(source: dict, tmp_path: Path, scenario: str) -> dict:
    out = tmp_path / f"{scenario}.json"
    result = run_module(
        "synth.corruption",
        ["--in", str(source["path"]), "--scenario", scenario, "--out", str(out)],
    )
    assert result.returncode == 0, f"Bozulma başarısız oldu:\n{stderr_text(result)}"
    return {"path": out, "data": json.loads(out.read_text(encoding="utf-8"))}


def target_id(data: dict) -> str:
    # undefined_flight çıktısında hedef flights'ta yoktur; kimlik kaynak veriden alınır.
    return next(f for f in data["flights"] if f["flight_no"] == TARGET_FLIGHT_NO)[
        "flight_id"
    ]


# ───────── Çıktı: seçim, sıra, biçim ─────────


@pytest.mark.parametrize("hhmm", ["00:00", "13:00", "16:12"])
def test_from_sonrasi_konumlar_ts_ve_flight_id_sirasinda_yayinlanir(source, hhmm):
    result = stream(source["path"], "--from", hhmm, "--no-wait")

    assert_ok(result)
    expected = expected_stream(source["data"]["positions"], from_time(DATE, hhmm))
    assert expected, "Ön koşul: bu saatten sonra konum olmalı"
    assert result.stdout == expected


def test_ts_metin_olarak_degil_zaman_olarak_karsilastirilir(tmp_path):
    positions = [
        position("FL-B", "2026-10-20T08:00:00+00:00"),  # 11:00 +03
        position("FL-A", "2026-10-20T10:30:00+03:00"),
        position("FL-C", "2026-10-20T06:59:00+00:00"),  # 09:59 +03, from'dan önce
        position("FL-D", "2026-10-20T07:00:00+00:00"),  # 10:00 +03, from'a eşit
        position("FL-Z", "2026-10-20T07:30:00+00:00"),  # 10:30 +03, FL-A ile aynı an
    ]
    input_path = small_input(tmp_path, positions)

    result = stream(input_path, "--from", "10:00", "--no-wait")

    assert_ok(result)
    order = [json.loads(raw)["flight_id"] for raw in result.stdout.splitlines()]
    assert order == ["FL-D", "FL-A", "FL-Z", "FL-B"]


def test_ayni_ts_de_flight_id_sirasi_girdi_sirasindan_bagimsizdir(tmp_path):
    ts = "2026-10-20T12:00:00+03:00"
    positions = [position(flight_id, ts) for flight_id in ("FL-3", "FL-1", "FL-2")]
    input_path = small_input(tmp_path, positions)

    result = stream(input_path, "--from", "12:00", "--no-wait")

    assert_ok(result)
    assert result.stdout == b"".join(
        line(position(f, ts)) for f in ("FL-1", "FL-2", "FL-3")
    )


def test_kayit_girdideki_haliyle_alan_sirasi_ve_utf8_korunarak_yazilir(tmp_path):
    record = {
        "phase": "YAKLAŞMA",
        "ts": "2026-10-20T12:00:00+03:00",
        "flight_id": "FL-Ç",
        "lat": 41.262,
        "not": "ığüşöç",
    }
    input_path = small_input(tmp_path, [record])

    result = stream(input_path, "--from", "12:00", "--no-wait")

    assert_ok(result)
    assert result.stdout == line(record)
    assert b"\r\n" not in result.stdout


def test_from_sonrasi_kayit_yoksa_bos_akis_ve_sifir_ozet(tmp_path):
    input_path = small_input(tmp_path, [position("FL-A", "2026-10-20T11:59:30+03:00")])

    result = stream(input_path, "--from", "12:00", "--no-wait")

    assert_ok(result)
    assert result.stdout == b""
    summary = [s for s in stderr_text(result).splitlines() if s.strip()]
    assert len(summary) == 1, stderr_text(result)
    assert re.search(r"(?<![\w:.-])0(?![\w:.-])", summary[0]), summary[0]


def test_ozet_stderr_de_tek_satir_sayi_ilk_ve_son_ts(source):
    start = from_time(DATE, "13:00")
    selected = sorted(
        (p for p in source["data"]["positions"] if parse_ts(p["ts"]) >= start),
        key=lambda p: (parse_ts(p["ts"]), p["flight_id"]),
    )

    result = stream(source["path"], "--from", "13:00", "--no-wait")

    assert_ok(result)
    summary = [s for s in stderr_text(result).splitlines() if s.strip()]
    assert len(summary) == 1, stderr_text(result)
    assert re.search(rf"(?<![\w:.-]){len(selected)}(?![\w:.-])", summary[0]), summary[0]
    assert selected[0]["ts"] in summary[0]
    assert selected[-1]["ts"] in summary[0]


# ───────── Belirlenimcilik ve bekleme ─────────


def test_ayri_sureclerde_farkli_hash_seed_ile_ayni_cikti(source):
    first = stream(source["path"], "--from", "06:00", "--no-wait", hash_seed="0")
    second = stream(source["path"], "--from", "06:00", "--no-wait", hash_seed="1")

    assert_ok(first)
    assert_ok(second)
    assert first.stdout == second.stdout


def test_speed_ve_no_wait_ciktiyi_degistirmez(tmp_path):
    positions = [
        position("FL-A", "2026-10-20T12:00:00+03:00"),
        position("FL-B", "2026-10-20T12:00:30+03:00"),
        position("FL-A", "2026-10-20T12:01:00+03:00"),
    ]
    input_path = small_input(tmp_path, positions)

    outputs = [
        stream(input_path, "--from", "12:00", "--no-wait"),
        stream(input_path, "--from", "12:00", "--speed", "600"),
        stream(input_path, "--from", "12:00", "--speed", "1200.5", "--no-wait"),
        stream(input_path, "--from", "12:00"),  # varsayılan hız 60: ~1 sn
    ]

    for result in outputs:
        assert_ok(result)
    assert len({r.stdout for r in outputs}) == 1
    assert outputs[0].stdout == expected_stream(positions, from_time(DATE, "12:00"))


def test_no_wait_hic_beklemez(tmp_path):
    # Hız 1'de bu akış bir saat sürerdi.
    positions = [
        position("FL-A", "2026-10-20T12:00:00+03:00"),
        position("FL-A", "2026-10-20T13:00:00+03:00"),
    ]
    input_path = small_input(tmp_path, positions)

    result = stream(
        input_path, "--from", "12:00", "--speed", "1", "--no-wait", timeout=15
    )

    assert_ok(result)
    assert len(result.stdout.splitlines()) == 2


def test_gruplar_from_dan_itibaren_ts_farki_bolu_speed_aninda_yazilir(tmp_path):
    # speed 60: simüle 30 sn = gerçek 0,5 sn.
    positions = [
        position("FL-A", "2026-10-20T12:00:30+03:00"),  # 0,5 sn
        position("FL-B", "2026-10-20T12:01:00+03:00"),  # 1,0 sn
        position("FL-C", "2026-10-20T12:01:00+03:00"),  # 1,0 sn, aynı grup
        position("FL-D", "2026-10-20T12:02:00+03:00"),  # 2,0 sn
    ]
    expected_offsets = {"FL-A": 0.5, "FL-B": 1.0, "FL-C": 1.0, "FL-D": 2.0}
    input_path = small_input(tmp_path, positions)

    started = time.perf_counter()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "synth.stream",
            "--in",
            str(input_path),
            "--from",
            "12:00",
        ],
        cwd=REPO_ROOT,
        env=env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    arrivals = {}
    try:
        for raw in iter(process.stdout.readline, b""):
            arrivals[json.loads(raw)["flight_id"]] = time.perf_counter() - started
        process.wait(timeout=30)
    finally:
        process.kill()
        process.stdout.close()
        process.stderr.close()

    assert process.returncode == 0
    assert list(arrivals) == ["FL-A", "FL-B", "FL-C", "FL-D"]
    # Alt sınır mutlak: süreç başlatma yalnızca gecikme ekler, hiçbir grup erken gelemez.
    for flight_id, offset in expected_offsets.items():
        assert arrivals[flight_id] >= offset - EARLY_TOLERANCE, (flight_id, arrivals)
    # Üst sınır ilk gruba göre: süreç başlatma süresi farkta sadeleşir.
    for flight_id, offset in expected_offsets.items():
        relative = arrivals[flight_id] - arrivals["FL-A"]
        assert relative <= offset - expected_offsets["FL-A"] + LATE_TOLERANCE, (
            flight_id,
            arrivals,
        )


# ───────── Bozulmuş girdi ─────────


def test_stale_position_ciktisinda_hedefin_izi_10_dakika_erken_biter(source, tmp_path):
    stale = corrupted(source, tmp_path, "stale_position")
    flight_id = target_id(source["data"])
    original = [p for p in source["data"]["positions"] if p["flight_id"] == flight_id]

    result = stream(stale["path"], "--from", "00:00", "--no-wait")

    assert_ok(result)
    assert result.stdout == expected_stream(
        stale["data"]["positions"], from_time(DATE, "00:00")
    )
    streamed = [json.loads(raw) for raw in result.stdout.splitlines()]
    track = [p for p in streamed if p["flight_id"] == flight_id]
    assert len(track) == 21
    last = parse_ts(original[-1]["ts"])
    assert parse_ts(track[-1]["ts"]) == last - timedelta(minutes=10)


def test_undefined_flight_ciktisindaki_yetim_konumlar_da_akitilir(source, tmp_path):
    undefined = corrupted(source, tmp_path, "undefined_flight")
    flight_id = target_id(source["data"])
    assert all(f["flight_id"] != flight_id for f in undefined["data"]["flights"])

    result = stream(undefined["path"], "--from", "00:00", "--no-wait")

    assert_ok(result)
    streamed = [json.loads(raw) for raw in result.stdout.splitlines()]
    assert sum(p["flight_id"] == flight_id for p in streamed) == 41


# ───────── Hata durumları ─────────


def test_girdi_okunamiyorsa_hata(tmp_path):
    assert_failed(stream(tmp_path / "yok.json", "--from", "12:00", "--no-wait"))


def test_girdi_gecerli_json_degilse_hata(tmp_path):
    input_path = tmp_path / "bozuk.json"
    input_path.write_text("{", encoding="utf-8")

    assert_failed(stream(input_path, "--from", "12:00", "--no-wait"))


@pytest.mark.parametrize(
    "data",
    [
        {"positions": []},  # meta yok
        {"meta": {}, "positions": []},  # meta.date yok
        {"meta": {"date": "2026/10/20"}, "positions": []},
        {"meta": {"date": "20-10-2026"}, "positions": []},
        {"meta": {"date": 20261020}, "positions": []},
    ],
)
def test_meta_date_yok_ya_da_bicimi_yanlissa_hata(tmp_path, data):
    input_path = write_json(tmp_path / "girdi.json", data)

    assert_failed(stream(input_path, "--from", "12:00", "--no-wait"))


@pytest.mark.parametrize(
    "hhmm", ["24:00", "25:00", "12:60", "9:05", "1200", "12:00:00", "ab:cd"]
)
def test_from_gecersizse_hata(tmp_path, hhmm):
    input_path = small_input(tmp_path, [position("FL-A", "2026-10-20T12:00:00+03:00")])

    assert_failed(stream(input_path, "--from", hhmm, "--no-wait"))


def test_from_verilmezse_hata(tmp_path):
    input_path = small_input(tmp_path, [position("FL-A", "2026-10-20T12:00:00+03:00")])

    assert_failed(stream(input_path, "--no-wait"))


# nan sayı gibi ayrıştırılır ama 0'dan büyük değildir.
@pytest.mark.parametrize("speed", ["0", "-1", "-0.5", "abc", "nan"])
def test_speed_gecersizse_hata(tmp_path, speed):
    input_path = small_input(tmp_path, [position("FL-A", "2026-10-20T12:00:00+03:00")])

    assert_failed(stream(input_path, "--from", "12:00", "--speed", speed))
