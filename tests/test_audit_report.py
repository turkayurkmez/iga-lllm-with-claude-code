"""scripts/audit_report.py sözleşme testleri (docs/audit.md › Okuma scripti).

Testler koddan önce yazıldı; script gelene kadar kırmızıdır. Kayıtlar her testin geçici
audit klasörüne (tests/conftest.py › audit_dir) elle yazılır; model ve API yoktur.
Script süreç içinde main(argv) ile çağrılır, çıktı capsys ile okunur.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "audit_report.py"
SOURCE = "data/referans/seed42-2026-10-20.json"
LONG_ANSWER = "Bugün 600 uçuş var; " + "ayrıntı " * 20 + "SONKELIME"


def load_script():
    assert SCRIPT.is_file(), "scripts/audit_report.py yok"
    spec = importlib.util.spec_from_file_location("audit_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def run(capsys):
    """Script'i argümanlarla çalıştırır; (çıkış kodu, stdout, stderr) döner."""
    script = load_script()

    def call(*args: str) -> tuple[int, str, str]:
        code = script.main(list(args))
        out, err = capsys.readouterr()
        return code, out, err

    return call


def audit_id(n: int) -> str:
    return f"{n:x}".rjust(8, "a") + "0" * 24


def question(
    n: int,
    ts: str,
    text: str,
    *,
    status: str = "tamam",
    answer: str | None = "Cevap.",
    reason: str | None = None,
    tool_calls: list | None = None,
    chips: list | None = None,
    disconnected: bool = False,
) -> dict:
    return {
        "type": "question",
        "audit_id": audit_id(n),
        "ts": ts,
        "question": text,
        "status": status,
        "reason": reason,
        "answer": answer,
        "model": "test-model",
        "instruction": {"name": "v1", "version": "1.0.0", "summary": "f" * 64},
        "turns": None if status == "model_error" else 1,
        "tool_calls": tool_calls or [],
        "chips": chips or [],
        "client_disconnected": disconnected,
    }


def feedback(n: int, ts: str) -> dict:
    return {"type": "feedback", "audit_id": audit_id(n), "ts": ts, "rating": "down"}


@pytest.fixture
def write(audit_dir):
    """Satırları ts'lerinin günündeki dosyaya, verilen sırayla ekler."""

    def append(*records: dict) -> None:
        audit_dir.mkdir(parents=True, exist_ok=True)
        for record in records:
            path = audit_dir / f"{record['ts'][:10]}.jsonl"
            with path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return append


def short(n: int) -> str:
    return audit_id(n)[:8]


def order_of(out: str, numbers: list[int]) -> list[int]:
    """Çıktıda geçen kısa kimliklerin sırası; geçmeyenler dahil edilmez."""
    found = [(out.find(short(n)), n) for n in numbers if short(n) in out]
    return [n for _, n in sorted(found)]


def ts(day: int, hour: int, minute: int = 0) -> str:
    return f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00+03:00"


# --- Parametresiz: son 5 soru ----------------------------------------------------


def test_parametresiz_son_bes_soru_olumsuzlar_once(run, write):
    # 7 soru, iki gün. En yeni 5'i: 3..7. Olumsuz: 2 (5'in dışında), 4 ve 6.
    write(
        question(1, ts(20, 9), "Soru bir"),
        question(2, ts(20, 10), "Soru iki"),
        question(3, ts(20, 11), "Soru üç"),
        question(4, ts(20, 12), "Soru dört"),
        feedback(4, ts(20, 12, 5)),
        feedback(2, ts(20, 13)),
        question(5, ts(21, 8), "Soru beş"),
        question(6, ts(21, 9), "Soru altı"),
        question(7, ts(21, 10), "Soru yedi"),
        feedback(6, ts(21, 11)),
    )

    code, out, err = run()

    assert code == 0
    assert err == ""
    assert order_of(out, list(range(1, 8))) == [6, 4, 7, 5, 3]
    assert "Soru bir" not in out
    assert "Soru iki" not in out


def test_ozet_satiri_alanlari(run, write):
    write(question(1, ts(20, 16, 22), "Bugün kaç uçuş var?"), feedback(1, ts(20, 17)))

    code, out, _ = run()

    assert code == 0
    lines = [line for line in out.splitlines() if short(1) in line]
    assert len(lines) == 1
    line = lines[0]
    for part in ("2026-10-20", "16:22", "tamam", "[olumsuz]", "Bugün kaç uçuş var?"):
        assert part in line
    assert "Cevap." in out


def test_olumsuz_olmayan_soruda_isaret_yok(run, write):
    write(question(1, ts(20, 9), "Soru"))

    _, out, _ = run()

    assert short(1) in out
    assert "[olumsuz]" not in out


def test_uzun_cevap_ozette_kisaltilir_null_cevap_belirtilir(run, write):
    write(
        question(1, ts(20, 9), "Uzun", answer=LONG_ANSWER),
        question(
            2,
            ts(20, 10),
            "Hatalı",
            status="model_error",
            answer=None,
            reason="Yanıt üretilirken bir hata oluştu.",
        ),
    )

    _, out, _ = run()

    assert LONG_ANSWER[:80] in out
    assert "SONKELIME" not in out
    assert LONG_ANSWER[:80] + "…" in out
    assert "(cevap yok)" in out


def test_ertesi_gun_verilen_geri_bildirim_de_sayilir(run, write):
    write(question(1, ts(20, 23), "Gece sorusu"), feedback(1, ts(21, 0, 5)))

    _, out, _ = run()

    line = next(line for line in out.splitlines() if short(1) in line)
    assert "[olumsuz]" in line


def test_eslesmeyen_geri_bildirim_gosterilmez(run, write):
    write(question(1, ts(20, 9), "Soru"), feedback(99, ts(20, 10)))

    code, out, _ = run()

    assert code == 0
    assert short(99) not in out
    assert "[olumsuz]" not in out


def test_bos_klasorde_kayit_yok(run, audit_dir):
    audit_dir.mkdir()

    code, out, err = run()

    assert (code, out.strip(), err) == (0, "Kayıt yok.", "")


def test_klasor_yoksa_hata(run, audit_dir):
    assert not audit_dir.exists()

    code, out, err = run()

    assert code == 1
    assert out == ""
    assert err.startswith("Hata: ")


# --- --id: yolculuk ----------------------------------------------------------------


JOURNEY_CALLS = [
    {
        "turn": 1,
        "name": "get_flight_summary",
        "input": {"direction": "all"},
        "executed": True,
        "source": SOURCE,
        "as_of": "2026-10-20T16:22:00+03:00",
        "stale": False,
        "tool_version": "1.0.0",
        "author": "tool",
        "error_code": None,
    },
    {
        "turn": 2,
        "name": "resolve_flight_identity",
        "input": {"query": "ZZ9999"},
        "executed": True,
        "source": SOURCE,
        "as_of": "2026-10-20T16:22:00+03:00",
        "stale": False,
        "tool_version": "1.0.0",
        "author": "tool",
        "error_code": "NOT_FOUND",
    },
]
JOURNEY_CHIPS = [
    {
        "tool": "get_flight_summary",
        "source": SOURCE,
        "as_of": "2026-10-20T16:22:00+03:00",
        "stale": False,
        "error_code": None,
    }
]


def test_yolculuk_tum_asamalari_gosterir(run, write):
    write(
        question(
            1,
            ts(20, 16, 22),
            "Bugün kaç uçuş var?",
            answer=LONG_ANSWER,
            tool_calls=JOURNEY_CALLS,
            chips=JOURNEY_CHIPS,
        ),
        feedback(1, ts(20, 16, 30)),
        feedback(1, ts(21, 8)),
    )

    code, out, err = run("--id", audit_id(1))

    assert code == 0
    assert err == ""
    for part in (
        audit_id(1),
        ts(20, 16, 22),
        "Bugün kaç uçuş var?",
        "v1",
        "1.0.0",
        "test-model",
        "get_flight_summary",
        '"direction": "all"',
        "resolve_flight_identity",
        "NOT_FOUND",
        SOURCE,
        "2026-10-20T16:22:00+03:00",
        "tamam",
        LONG_ANSWER,  # yolculukta cevap kısaltılmaz
        ts(20, 16, 30),
        ts(21, 8),
    ):
        assert part in out, part
    # Akış sırası: soru → tool çağrıları → cevap → geri bildirim.
    positions = [
        out.index("Bugün kaç uçuş var?"),
        out.index("get_flight_summary"),
        out.index("resolve_flight_identity"),
        out.index("SONKELIME"),
        out.index(ts(20, 16, 30)),
    ]
    assert positions == sorted(positions)


def test_yolculukta_geri_bildirim_yoksa_belirtilir(run, write):
    write(question(1, ts(20, 9), "Soru"))

    code, out, _ = run("--id", audit_id(1))

    assert code == 0
    assert "Geri bildirim yok." in out


def test_yolculukta_istemci_kesmesi_ve_hata_nedeni(run, write):
    reason = "Tur sınırına (8) ulaşıldı."
    write(
        question(1, ts(20, 9), "Kesik", disconnected=True),
        question(
            2,
            ts(20, 10),
            "Sınır",
            status="iterasyon_siniri",
            answer=None,
            reason=reason,
        ),
    )

    _, cut, _ = run("--id", audit_id(1))
    _, limit, _ = run("--id", audit_id(2))

    assert "kesti" in cut
    assert "kesti" not in limit
    assert "iterasyon_siniri" in limit
    assert reason in limit
    assert "(cevap yok)" in limit


def test_benzersiz_onek_ile_bulunur(run, write):
    write(question(1, ts(20, 9), "Önekli soru"))

    code, out, _ = run("--id", audit_id(1)[:6])

    assert code == 0
    assert audit_id(1) in out
    assert "Önekli soru" in out


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("aaaaa", id="5_karakter"),
        pytest.param("zzzzzz", id="hex_degil"),
        pytest.param("bbbbbbbb", id="bulunamadi"),
    ],
)
def test_gecersiz_ya_da_bulunmayan_kimlik_hata(run, write, value):
    write(question(1, ts(20, 9), "Soru"))

    code, out, err = run("--id", value)

    assert code == 1
    assert out == ""
    assert err.startswith("Hata: ")


def test_belirsiz_onek_adaylari_listeler(run, write):
    first = "abcdef" + "1" * 26
    second = "abcdef" + "2" * 26
    write(
        question(1, ts(20, 9), "Bir") | {"audit_id": first},
        question(2, ts(20, 10), "İki") | {"audit_id": second},
    )

    code, out, err = run("--id", "abcdef")

    assert code == 1
    assert out == ""
    assert err.startswith("Hata: ")
    assert first in err
    assert second in err


# --- --tarih -----------------------------------------------------------------------


def test_tarih_o_gunun_sorulari_olumsuzlar_once(run, write):
    write(
        question(1, ts(19, 9), "Önceki gün"),
        question(2, ts(20, 8), "Sabah", answer="Sabah cevabı."),
        question(3, ts(20, 9), "Öğle", answer="Öğle cevabı."),
        question(4, ts(20, 10), "Akşam", answer="Akşam cevabı."),
        question(5, ts(20, 11), "Gece", answer="Gece cevabı."),
        feedback(2, ts(20, 12)),
        feedback(4, ts(21, 7)),
        question(6, ts(21, 9), "Sonraki gün"),
    )

    code, out, err = run("--tarih", "2026-10-20")

    assert code == 0
    assert err == ""
    assert order_of(out, list(range(1, 7))) == [4, 2, 5, 3]
    for part in ("Sabah", "Sabah cevabı.", "Akşam cevabı.", ts(20, 12), ts(21, 7)):
        assert part in out, part
    assert "Önceki gün" not in out
    assert "Sonraki gün" not in out
    # Her soru için sıra: soru → cevap → geri bildirim.
    block = out[out.index(short(4)) : out.index(short(2))]
    assert block.index("Akşam") < block.index("Akşam cevabı.") < block.index(ts(21, 7))


def test_tarihte_kayit_yoksa_kayit_yok(run, write):
    write(question(1, ts(20, 9), "Soru"))

    code, out, err = run("--tarih", "2026-10-25")

    assert (code, out.strip(), err) == (0, "Kayıt yok.", "")


@pytest.mark.parametrize("value", ["20-10-2026", "2026-13-01", "dün"])
def test_gecersiz_tarih_hata(run, write, value):
    write(question(1, ts(20, 9), "Soru"))

    code, out, err = run("--tarih", value)

    assert code == 1
    assert out == ""
    assert err.startswith("Hata: ")


def test_id_ve_tarih_birlikte_verilemez(run, write):
    write(question(1, ts(20, 9), "Soru"))

    with pytest.raises(SystemExit) as exc:
        run("--id", audit_id(1), "--tarih", "2026-10-20")

    assert exc.value.code == 2


# --- Okuma kuralları ---------------------------------------------------------------


def test_bozuk_satir_atlanir_ve_uyarilir(run, write, audit_dir):
    write(question(1, ts(20, 9), "Sağlam bir"))
    path = audit_dir / "2026-10-20.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as file:
        file.write("{bozuk json\n")
    write(question(2, ts(20, 10), "Sağlam iki"))

    code, out, err = run()

    assert code == 0
    assert "Sağlam bir" in out
    assert "Sağlam iki" in out
    assert err.strip() == f"Uyarı: {path}:2 okunamadı."


def test_script_kayitlari_degistirmez(run, write, audit_dir):
    write(
        question(1, ts(20, 9), "Soru"),
        feedback(1, ts(20, 10)),
        question(2, ts(21, 9), "İkinci"),
    )
    before = {p.name: p.read_bytes() for p in audit_dir.iterdir()}

    run()
    run("--id", audit_id(1))
    run("--tarih", "2026-10-20")

    assert {p.name: p.read_bytes() for p in audit_dir.iterdir()} == before
