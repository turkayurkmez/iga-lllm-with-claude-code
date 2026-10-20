"""Bozulma komutu sözleşme testleri (docs/bozulma.md).

Testler komuttan önce yazıldı; synth/corruption.py yokken kırmızıdır. Komut yazılırken bu
testler gevşetilmez.

Her senaryoda beklenen çıktı testte girdiden kurulur ve çıktı dosyasıyla byte byte
karşılaştırılır; böylece "yalnızca şu değişir" kuralı, kayıt sırası ve yazım biçimi birlikte
sınanır.
"""

import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SEED = 42
DATE = "2026-10-20"
DEFAULT_FLIGHT_NO = "TK2345"
DEFAULT_FIELD = "flights.estimated_time"
SCENARIOS = (
    "stale_position",
    "duplicate_callsign",
    "missing_field",
    "undefined_flight",
)
STALE_WINDOW = timedelta(minutes=10)


def run_module(module: str, args: list[str], hash_seed: str = "0"):
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def serialize(data: dict) -> bytes:
    """Üreteçle aynı yazım biçimi (docs/bozulma.md › Belirlenimcilik)."""
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> dict:
    path = tmp_path_factory.mktemp("kaynak") / f"{SEED}-{DATE}.json"
    result = run_module(
        "synth.generator", ["--seed", str(SEED), "--date", DATE, "--out", str(path)]
    )
    assert result.returncode == 0, f"Üreteç başarısız oldu:\n{result.stderr}"
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    # Ön koşul: üreteç çıktısı bu biçimle yazılmış; beklenen çıktılar da öyle kurulur.
    assert raw == serialize(data)
    return {"path": path, "bytes": raw, "data": data}


@pytest.fixture
def data(source) -> dict:
    """Testin değiştirebileceği bağımsız kopya."""
    return copy.deepcopy(source["data"])


def out_path(tmp_path: Path, name: str = "cikti.json") -> Path:
    # Var olmayan iç içe klasör: komutun klasörü kendisinin oluşturması beklenir.
    return tmp_path / "yok" / "alt" / name


def corrupt(
    input_path: Path, out: Path, scenario: str, *extra: str, hash_seed: str = "0"
):
    args = ["--in", str(input_path), "--scenario", scenario, "--out", str(out), *extra]
    return run_module("synth.corruption", args, hash_seed=hash_seed)


def assert_ok(result) -> None:
    assert result.returncode == 0, f"Komut başarısız oldu:\n{result.stderr}"


def assert_failed(result, out: Path) -> None:
    assert result.returncode != 0, f"Hata bekleniyordu:\n{result.stdout}"
    assert result.stderr.strip(), "stderr'de neden yazmalı"
    assert not out.exists(), "Hata durumunda çıktı dosyası yazılmamalı"


def flight_by_no(data: dict, flight_no: str) -> dict:
    matches = [f for f in data["flights"] if f["flight_no"] == flight_no]
    assert len(matches) == 1, flight_no
    return matches[0]


def movement_type(data: dict, flight_id: str) -> str:
    return next(m for m in data["movements"] if m["flight_id"] == flight_id)[
        "movement_type"
    ]


def first_active_flight_no(data: dict, kind: str, exclude: str) -> str:
    """flight_id sırasına göre, iptal edilmemiş ilk `kind` hareketinin sefer no'su."""
    for flight in sorted(data["flights"], key=lambda f: f["flight_id"]):
        if flight["cancelled"] or flight["flight_no"] == exclude:
            continue
        if movement_type(data, flight["flight_id"]) == kind:
            return flight["flight_no"]
    raise AssertionError(f"{kind} bulunamadı")


def write_input(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "girdi.json"
    path.write_bytes(serialize(data))
    return path


# ───────── Beklenen çıktıyı kuran yardımcılar ─────────


def expect_stale_position(data: dict, flight_no: str) -> int:
    flight_id = flight_by_no(data, flight_no)["flight_id"]
    track = [p for p in data["positions"] if p["flight_id"] == flight_id]
    last = max(datetime.fromisoformat(p["ts"]) for p in track)
    cutoff = last - STALE_WINDOW
    before = len(data["positions"])
    data["positions"] = [
        p
        for p in data["positions"]
        if p["flight_id"] != flight_id or datetime.fromisoformat(p["ts"]) <= cutoff
    ]
    return before - len(data["positions"])


def expect_duplicate_callsign(data: dict, flight_no: str) -> int:
    target = flight_by_no(data, flight_no)
    candidates = [
        f
        for f in data["flights"]
        if f["flight_id"] != target["flight_id"]
        and not f["cancelled"]
        and movement_type(data, f["flight_id"]) == "DEPARTURE"
    ]
    other = min(candidates, key=lambda f: f["flight_id"])
    other["callsign"] = target["callsign"]
    return 1


def expect_missing_field(data: dict, flight_no: str, field: str) -> int:
    table, name = field.split(".")
    flight_id = flight_by_no(data, flight_no)["flight_id"]
    record = next(r for r in data[table] if r["flight_id"] == flight_id)
    del record[name]
    return 1


def expect_undefined_flight(data: dict, flight_no: str) -> int:
    flight_id = flight_by_no(data, flight_no)["flight_id"]
    data["flights"] = [f for f in data["flights"] if f["flight_id"] != flight_id]
    return 1


def expect(data: dict, scenario: str, flight_no: str = DEFAULT_FLIGHT_NO) -> int:
    if scenario == "stale_position":
        return expect_stale_position(data, flight_no)
    if scenario == "duplicate_callsign":
        return expect_duplicate_callsign(data, flight_no)
    if scenario == "missing_field":
        return expect_missing_field(data, flight_no, DEFAULT_FIELD)
    return expect_undefined_flight(data, flight_no)


# ───────── Senaryolar: çıktı birebir beklenen ─────────


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_varsayilan_hedefte_cikti_yalnizca_sozlesmedeki_farki_tasir(
    source, data, tmp_path, scenario
):
    out = out_path(tmp_path)

    assert_ok(corrupt(source["path"], out, scenario))

    expect(data, scenario)
    assert out.read_bytes() == serialize(data)


def test_stale_position_izde_ilk_21_nokta_kalir(source, tmp_path):
    out = out_path(tmp_path)

    assert_ok(corrupt(source["path"], out, "stale_position"))

    result = json.loads(out.read_text(encoding="utf-8"))
    flight_id = flight_by_no(result, DEFAULT_FLIGHT_NO)["flight_id"]
    original = [p for p in source["data"]["positions"] if p["flight_id"] == flight_id]
    remaining = [p for p in result["positions"] if p["flight_id"] == flight_id]
    assert remaining == original[:21]


def test_stale_position_baska_hedefte_de_calisir(source, data, tmp_path):
    flight_no = first_active_flight_no(data, "ARRIVAL", exclude=DEFAULT_FLIGHT_NO)
    out = out_path(tmp_path)

    assert_ok(corrupt(source["path"], out, "stale_position", "--flight-no", flight_no))

    expect_stale_position(data, flight_no)
    assert out.read_bytes() == serialize(data)


def test_duplicate_callsign_ile_iki_ucus_eslesir(source, tmp_path):
    out = out_path(tmp_path)

    assert_ok(corrupt(source["path"], out, "duplicate_callsign"))

    result = json.loads(out.read_text(encoding="utf-8"))
    callsign = flight_by_no(source["data"], DEFAULT_FLIGHT_NO)["callsign"]
    matches = [f for f in result["flights"] if f["callsign"] == callsign]
    assert len(matches) == 2
    assert len({f["flight_no"] for f in matches}) == 2


def test_duplicate_callsign_hedef_arrival_iken_de_ilk_departure_a_kopyalar(
    source, data, tmp_path
):
    flight_no = "TK2344"
    assert movement_type(data, flight_by_no(data, flight_no)["flight_id"]) == "ARRIVAL"
    out = out_path(tmp_path)

    assert_ok(
        corrupt(source["path"], out, "duplicate_callsign", "--flight-no", flight_no)
    )

    expect_duplicate_callsign(data, flight_no)
    assert out.read_bytes() == serialize(data)


@pytest.mark.parametrize(
    "field",
    [
        "flights.estimated_time",
        "flights.callsign",
        "movements.stand_code",
        "movements.actual_block_time",
        "delays.delay_minutes",
    ],
)
def test_missing_field_verilen_alanin_anahtarini_kaldirir(
    source, data, tmp_path, field
):
    out = out_path(tmp_path)

    assert_ok(corrupt(source["path"], out, "missing_field", "--field", field))

    expect_missing_field(data, DEFAULT_FLIGHT_NO, field)
    assert out.read_bytes() == serialize(data)


def test_undefined_flight_yetim_kayitlari_birakir(source, tmp_path):
    out = out_path(tmp_path)

    assert_ok(corrupt(source["path"], out, "undefined_flight"))

    result = json.loads(out.read_text(encoding="utf-8"))
    flight_id = flight_by_no(source["data"], DEFAULT_FLIGHT_NO)["flight_id"]
    assert all(f["flight_no"] != DEFAULT_FLIGHT_NO for f in result["flights"])
    assert any(m["flight_id"] == flight_id for m in result["movements"])
    assert any(p["flight_id"] == flight_id for p in result["positions"])
    assert any(d["flight_id"] == flight_id for d in result["delays"])


# ───────── Girdi, belirlenimcilik, özet ─────────


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_girdi_dosyasi_degismez(source, tmp_path, scenario):
    assert_ok(corrupt(source["path"], out_path(tmp_path), scenario))

    assert source["path"].read_bytes() == source["bytes"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_ayni_girdi_ve_arguman_ayri_sureclerde_birebir_ayni_cikti(
    source, tmp_path, scenario
):
    first = out_path(tmp_path, "a.json")
    second = out_path(tmp_path, "b.json")

    assert_ok(corrupt(source["path"], first, scenario, hash_seed="0"))
    assert_ok(corrupt(source["path"], second, scenario, hash_seed="1"))

    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_ozet_satiri_senaryo_hedef_ve_etkilenen_sayiyi_icerir(
    source, data, tmp_path, scenario
):
    result = corrupt(source["path"], out_path(tmp_path), scenario)
    assert_ok(result)

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"Tek satır özet bekleniyordu:\n{result.stdout}"
    line = lines[0]
    target = flight_by_no(data, DEFAULT_FLIGHT_NO)
    affected = expect(data, scenario)
    assert scenario in line
    assert target["flight_id"] in line
    assert DEFAULT_FLIGHT_NO in line
    assert re.search(rf"(?<![\w-]){affected}(?![\w-])", line), (
        f"Etkilenen sayı yok: {line}"
    )


def test_zincirleme_cikti_yeniden_girdi_olur(source, data, tmp_path):
    first = out_path(tmp_path, "a.json")
    second = out_path(tmp_path, "b.json")

    assert_ok(corrupt(source["path"], first, "stale_position"))
    assert_ok(corrupt(first, second, "missing_field"))

    expect_stale_position(data, DEFAULT_FLIGHT_NO)
    expect_missing_field(data, DEFAULT_FLIGHT_NO, DEFAULT_FIELD)
    assert second.read_bytes() == serialize(data)


# ───────── Hata durumları ─────────


def test_hedef_bulunamazsa_hata(source, tmp_path):
    out = out_path(tmp_path)

    assert_failed(
        corrupt(source["path"], out, "stale_position", "--flight-no", "ZZ9999"), out
    )


def test_hedef_birden_fazla_eslesirse_hata(data, tmp_path):
    other = next(f for f in data["flights"] if f["flight_no"] != DEFAULT_FLIGHT_NO)
    other["flight_no"] = DEFAULT_FLIGHT_NO
    input_path = write_input(tmp_path, data)
    out = out_path(tmp_path)

    assert_failed(corrupt(input_path, out, "undefined_flight"), out)


def test_stale_position_iptal_edilmis_hedefte_hata(source, tmp_path):
    cancelled = next(f for f in source["data"]["flights"] if f["cancelled"])
    out = out_path(tmp_path)

    result = corrupt(
        source["path"], out, "stale_position", "--flight-no", cancelled["flight_no"]
    )

    assert_failed(result, out)


def test_duplicate_callsign_uygun_ikinci_departure_yoksa_hata(data, tmp_path):
    target_id = flight_by_no(data, DEFAULT_FLIGHT_NO)["flight_id"]
    for flight in data["flights"]:
        if flight["flight_id"] != target_id and movement_type(
            data, flight["flight_id"]
        ) == ("DEPARTURE"):
            flight["cancelled"] = True
    input_path = write_input(tmp_path, data)
    out = out_path(tmp_path)

    assert_failed(corrupt(input_path, out, "duplicate_callsign"), out)


@pytest.mark.parametrize(
    ("field", "flight_no"),
    [
        ("flights", DEFAULT_FLIGHT_NO),  # biçim yanlış
        ("flights.estimated_time.x", DEFAULT_FLIGHT_NO),  # biçim yanlış
        ("positions.ts", DEFAULT_FLIGHT_NO),  # izin verilmeyen tablo
        ("aircraft.type_icao", DEFAULT_FLIGHT_NO),  # izin verilmeyen tablo
        ("flights.yok", DEFAULT_FLIGHT_NO),  # tabloda olmayan alan
        ("delays.delay_minutes", "TK2344"),  # hedefin gecikme kaydı yok
        ("flights.flight_id", DEFAULT_FLIGHT_NO),  # anahtar alan
        ("movements.flight_id", DEFAULT_FLIGHT_NO),  # anahtar alan
    ],
)
def test_missing_field_gecersiz_alanda_hata(source, tmp_path, field, flight_no):
    out = out_path(tmp_path)

    result = corrupt(
        source["path"], out, "missing_field", "--field", field, "--flight-no", flight_no
    )

    assert_failed(result, out)


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s != "missing_field"])
def test_field_baska_senaryoyla_verilirse_hata(source, tmp_path, scenario):
    out = out_path(tmp_path)

    assert_failed(corrupt(source["path"], out, scenario, "--field", DEFAULT_FIELD), out)


def test_bilinmeyen_senaryoda_hata(source, tmp_path):
    out = out_path(tmp_path)

    assert_failed(corrupt(source["path"], out, "yok"), out)


def test_out_girdiyle_ayni_yolsa_hata_ve_girdi_degismez(source, data, tmp_path):
    input_path = write_input(tmp_path, data)
    before = input_path.read_bytes()

    result = corrupt(input_path, input_path, "undefined_flight")

    assert result.returncode != 0
    assert result.stderr.strip()
    assert input_path.read_bytes() == before
