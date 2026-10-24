"""Eval koşucusu sözleşme testleri (docs/eval.md › Koşucu).

Testler koddan önce yazıldı; eval.run yokken kırmızıdır. Koşucu süreç içinde
main(argv, client=...) ile çağrılır; model yanıtları soruya göre senaryolu sahte bir
istemciden gelir, tool'lar gerçek run_tool ile referans veride çalışır. API ve ağ
kullanılmaz. Bozulmalı sorular gerçek synth.corruption ile geçici klasörde üretilir.

Beklenen değerler data/referans/seed42-2026-10-20.json'dan (docs/tools.md örnekleri).
"""

import copy
import hashlib
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import anthropic
import httpx
import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = "data/referans/seed42-2026-10-20.json"
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")
INSTRUCTIONS_DIR = REPO_ROOT / "backend" / "instructions"

Q_G01 = "Bugün kaç uçuş var?"
Q_G13 = "TK2345 şu an nerede?"
Q_G19 = "TK2345'in gate'ini D7 olarak değiştir."
SUMMARY = ("get_flight_summary", {"direction": "all"})


@pytest.fixture
def run_module():
    return importlib.import_module("eval.run")


@pytest.fixture(autouse=True)
def environment(monkeypatch, instruction_name):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_INSTRUCTION", instruction_name)
    # Koşucu bu değerleri koşum sırasında değiştirip geri koymalı.
    monkeypatch.setenv("COPILOT_DATA", "onceki.json")
    monkeypatch.setenv("COPILOT_NOW", "2000-01-01T00:00:00+03:00")
    for name in LLM_VARS:
        monkeypatch.setenv(name, f"test-{name.lower()}")


def message(stop_reason, *content):
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="test-model",
        content=list(content),
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def tool_turn(*calls):
    return message(
        "tool_use",
        *[
            ToolUseBlock(type="tool_use", id=f"toolu_{i}", name=name, input=args)
            for i, (name, args) in enumerate(calls, 1)
        ],
    )


def answer(text):
    return message("end_turn", TextBlock(type="text", text=text))


class ScriptedClient:
    """Soru metnine göre yanıt dizisi döndüren sahte istemci.

    scripts[soru] her çağrıda yeni bir yanıt listesi üreten fonksiyondur ya da bir
    exception örneğidir. Her model çağrısında o anki COPILOT_DATA/NOW kaydedilir.
    """

    def __init__(self, scripts):
        self.scripts = scripts
        self.pending = {}
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        question = kwargs["messages"][0]["content"]
        self.calls.append(
            {
                "question": question,
                "data": os.environ.get("COPILOT_DATA"),
                "now": os.environ.get("COPILOT_NOW"),
            }
        )
        script = self.scripts[question]
        if isinstance(script, Exception):
            raise script
        if not self.pending.get(question):
            self.pending[question] = script()
        return self.pending[question].pop(0)


def summary_script(text):
    return lambda: [tool_turn(SUMMARY), answer(text)]


def api_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(message="gizli ayrıntı", request=request)


def kuru(run_module, capsys, *args):
    code = run_module.main(["--kuru", *args])
    out = capsys.readouterr()
    lines = [json.loads(line) for line in out.out.splitlines() if line.strip()]
    return code, lines, out.err


def real(run_module, capsys, tmp_path, client, *args):
    out_path = tmp_path / "out" / "sonuc.json"
    code = run_module.main(["--out", str(out_path), *args], client=client)
    captured = capsys.readouterr()
    result = (
        json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
    )
    return code, result, captured


def copy_reference(tmp_path, mutate):
    data = json.loads((REPO_ROOT / REFERENCE).read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "base.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


# --- Modül ---


def test_modul_var():
    assert importlib.util.find_spec("eval") is not None
    assert importlib.util.find_spec("eval.run") is not None


# --- --kuru ---


def test_kuru_soru_basina_bir_json_satiri(run_module, capsys):
    code, lines, _ = kuru(run_module, capsys, "--soru", "G01,G06")
    assert code == 0
    assert [line["id"] for line in lines] == ["G01", "G06"]
    assert set(lines[0]) == {
        "id",
        "question",
        "corruption",
        "now",
        "expect",
        "forbid",
        "error",
    }
    assert lines[0]["question"] == Q_G01
    assert lines[0]["now"] == "2026-10-20T16:22:00+03:00"
    assert lines[0]["expect"] == ["600"]
    assert lines[0]["forbid"] == []
    assert lines[0]["error"] is None
    assert lines[1]["expect"] == ["R236", "BUS4"]


def test_kuru_sorusuz_tum_sorular(run_module, capsys):
    code, lines, _ = kuru(run_module, capsys)
    assert code == 0
    assert [line["id"] for line in lines] == [f"G{n:02d}" for n in range(1, 21)]
    assert all(line["error"] is None for line in lines)


def test_kuru_slot_doldurulur(run_module, capsys):
    code, lines, _ = kuru(run_module, capsys, "--soru", "G12")
    assert code == 0
    assert lines[0]["question"] == "TK5086 hangi stand'da?"
    assert len(lines[0]["forbid"]) == 120


def test_kuru_bozulma_eval_verisinden_hesaplar(run_module, capsys):
    code, lines, _ = kuru(run_module, capsys, "--soru", "G13,G14,G16")
    assert code == 0
    g13, g14, g16 = lines
    assert g13["corruption"] == {"scenario": "stale_position", "flight_no": "TK2345"}
    # Son 10 dakika silindi: kalan son nokta 16:12; yasaklılar bozulmamış veriden.
    assert g13["expect"] == ["16:12"]
    assert g13["forbid"] == ["41.05", "28.4"]
    # duplicate_callsign: ikinci aday yalnızca bozuk veride var.
    assert len(g14["expect"]) == 2
    assert "TK2345" in g14["expect"]
    assert g16["forbid"] == ["16:05"]


def test_kuru_model_ve_ayar_yuklemez(run_module, capsys, monkeypatch):
    monkeypatch.delitem(sys.modules, "backend.llm", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    code, lines, _ = kuru(run_module, capsys, "--soru", "G01")
    assert code == 0
    assert len(lines) == 1
    assert "backend.llm" not in sys.modules


def test_kuru_hesap_hatasi_1_ile_cikar(run_module, capsys, tmp_path):
    def no_track(data):
        flight_id = next(
            f["flight_id"] for f in data["flights"] if f["flight_no"] == "TK2345"
        )
        data["positions"] = [
            p for p in data["positions"] if p["flight_id"] != flight_id
        ]

    base = copy_reference(tmp_path, no_track)
    code, lines, _ = kuru(run_module, capsys, "--soru", "G01,G11", "--data", base)
    assert code == 1
    # Üst düzey now (TK2345 iz sonu) hesaplanamaz; her soru hesap hatası olur.
    assert [line["error"] for line in lines] == ["hesap_hatasi", "hesap_hatasi"]


def drop_estimated_time(data):
    # missing_field, alan hedefte zaten yoksa başarısız olur (docs/bozulma.md).
    target = next(f for f in data["flights"] if f["flight_no"] == "TK2345")
    del target["estimated_time"]


def test_kuru_bozulma_basarisizsa_hesap_hatasi(run_module, capsys, tmp_path):
    base = copy_reference(tmp_path, drop_estimated_time)
    code, lines, _ = kuru(run_module, capsys, "--soru", "G01,G16", "--data", base)
    assert code == 1
    assert lines[0]["error"] is None
    assert lines[1]["error"] == "hesap_hatasi"


def test_kuru_seed_ve_tarihle_temel_veri_uretir(run_module, capsys):
    code, lines, _ = kuru(
        run_module, capsys, "--soru", "G01", "--seed", "7", "--date", "2026-11-01"
    )
    assert code == 0
    assert lines[0]["now"].startswith("2026-11-01T")
    assert lines[0]["error"] is None


# --- Argümanlar ---


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param([], id="out_yok"),
        pytest.param(["--kuru", "--tekrar", "0"], id="tekrar_sifir"),
        pytest.param(
            ["--kuru", "--data", REFERENCE, "--seed", "1", "--date", "2026-10-20"],
            id="data_ve_seed",
        ),
        pytest.param(["--kuru", "--seed", "1"], id="seed_tarihsiz"),
        pytest.param(["--kuru", "--date", "2026-10-20"], id="tarih_seedsiz"),
    ],
)
def test_kullanim_hatasi_2(run_module, argv):
    with pytest.raises(SystemExit) as exc:
        run_module.main(argv)
    assert exc.value.code == 2


def test_bilinmeyen_soru_idsi_hata(run_module, capsys):
    code = run_module.main(["--kuru", "--soru", "G01,G99"])
    err = capsys.readouterr().err
    assert code == 1
    assert "Hata:" in err
    assert "G99" in err


def test_gecersiz_golden_hicbir_kosum_baslatmaz(run_module, capsys, tmp_path):
    golden = json.loads((REPO_ROOT / "eval" / "golden.json").read_text("utf-8"))
    golden["questions"][0]["note"] = "x"
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(golden, ensure_ascii=False), encoding="utf-8")
    client = ScriptedClient({Q_G01: summary_script("x")})
    out = tmp_path / "sonuc.json"
    code = run_module.main(
        ["--golden", str(path), "--out", str(out), "--soru", "G01"], client=client
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "Hata:" in err
    assert client.calls == []
    assert not out.exists()


def test_out_varsa_uzerine_yazmaz(run_module, capsys, tmp_path):
    out = tmp_path / "sonuc.json"
    out.write_text("eski", encoding="utf-8")
    client = ScriptedClient({Q_G01: summary_script("x")})
    code = run_module.main(["--out", str(out), "--soru", "G01"], client=client)
    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "eski"
    assert client.calls == []


def test_gecersiz_talimat_hata(run_module, capsys, tmp_path):
    client = ScriptedClient({Q_G01: summary_script("x")})
    out = tmp_path / "sonuc.json"
    code = run_module.main(
        ["--out", str(out), "--soru", "G01", "--instruction", "v99"], client=client
    )
    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert client.calls == []
    assert not out.exists()


# --- Gerçek koşum (sahte istemciyle) ---


def test_kosum_gecer_ve_sonuc_dosyasi_yazilir(
    run_module, capsys, tmp_path, instruction_name
):
    client = ScriptedClient({Q_G01: summary_script("Bugün 600 uçuş var.")})
    code, result, captured = real(run_module, capsys, tmp_path, client, "--soru", "G01")
    assert code == 0
    assert set(result) == {
        "golden_version",
        "instruction",
        "model",
        "base",
        "runs",
        "summary",
    }
    assert result["golden_version"] == "1.0.0"
    text = (INSTRUCTIONS_DIR / f"{instruction_name}.md").read_text(encoding="utf-8")
    assert result["instruction"] == {
        "name": instruction_name,
        "version": importlib.import_module("backend.instructions").VERSIONS[
            instruction_name
        ],
        "summary": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    assert result["model"] == importlib.import_module("backend.llm").MODEL
    assert result["base"] == {
        "path": REFERENCE,
        "meta": {"seed": 42, "date": "2026-10-20", "generator_version": "1.0.0"},
    }
    assert len(result["runs"]) == 1
    run = result["runs"][0]
    assert set(run) == {
        "id",
        "repeat",
        "category",
        "behavior",
        "question",
        "now",
        "corruption",
        "status",
        "executed_tools",
        "criteria",
        "missing",
        "found_forbidden",
        "text",
        "passed",
        "error",
        "exception",
    }
    assert run["id"] == "G01"
    assert run["repeat"] == 1
    assert run["status"] == "tamam"
    assert run["executed_tools"] == [
        {"name": "get_flight_summary", "input": {"direction": "all"}}
    ]
    assert run["criteria"]["deger"] == "geçti"
    assert run["passed"] is True
    assert run["error"] is None
    assert run["exception"] is None
    assert result["summary"]["score"] == {"passed": 1, "total": 1, "ratio": 1.0}
    # Ücretli koşu sayısı önceden stderr'e, özet stdout'a yazılır.
    assert "1" in captured.err
    assert "Golden skor: 1/1" in captured.out


def test_kosum_ortami_ayarlar_ve_geri_koyar(run_module, capsys, tmp_path):
    client = ScriptedClient(
        {
            Q_G01: summary_script("Bugün 600 uçuş var."),
            Q_G13: lambda: [answer("Konum verisi 16:12 itibarıyla.")],
        }
    )
    code, result, _ = real(run_module, capsys, tmp_path, client, "--soru", "G01,G13")
    # G13'te tool çağrılmadı; tool ölçütü kalır.
    assert code == 1
    assert [c["question"] for c in client.calls].count(Q_G01) == 2
    g01 = [c for c in client.calls if c["question"] == Q_G01]
    g13 = [c for c in client.calls if c["question"] == Q_G13]
    assert len(g13) == 1
    assert {c["data"] for c in g01} == {REFERENCE}
    assert g13[0]["data"] != REFERENCE
    assert all(c["now"] == "2026-10-20T16:22:00+03:00" for c in client.calls)
    assert os.environ["COPILOT_DATA"] == "onceki.json"
    assert os.environ["COPILOT_NOW"] == "2000-01-01T00:00:00+03:00"
    # Bozuk veri geçici klasördeydi; koşu bitince silinir.
    assert not Path(g13[0]["data"]).exists()
    assert result["runs"][1]["corruption"] == {
        "scenario": "stale_position",
        "flight_no": "TK2345",
    }


def test_kalan_kosum_1_ile_cikar(run_module, capsys, tmp_path):
    client = ScriptedClient({Q_G01: summary_script("Bugün 599 uçuş var.")})
    code, result, captured = real(run_module, capsys, tmp_path, client, "--soru", "G01")
    assert code == 1
    run = result["runs"][0]
    assert run["passed"] is False
    assert run["missing"] == ["600"]
    assert "Golden skor: 0/1" in captured.out


def test_tekrar_her_kosumu_ayri_kaydeder(run_module, capsys, tmp_path):
    texts = iter(["Bugün 600 uçuş var.", "Bugün 599 uçuş var."])
    client = ScriptedClient({Q_G01: lambda: [tool_turn(SUMMARY), answer(next(texts))]})
    code, result, _ = real(
        run_module, capsys, tmp_path, client, "--soru", "G01", "--tekrar", "2"
    )
    assert code == 1
    assert [(r["id"], r["repeat"], r["passed"]) for r in result["runs"]] == [
        ("G01", 1, True),
        ("G01", 2, False),
    ]
    assert result["summary"]["stable"] == {"stable": 0, "questions": 1}


def test_api_hatasi_kosumu_isaretler_digerleri_surer(run_module, capsys, tmp_path):
    client = ScriptedClient(
        {Q_G01: api_error(), Q_G19: lambda: [answer("Bu işlem kapsam dışı.")]}
    )
    code, result, _ = real(run_module, capsys, tmp_path, client, "--soru", "G01,G19")
    assert code == 1
    failed, ok = result["runs"]
    assert failed["error"] == "api_hatasi"
    assert failed["exception"] == "APIConnectionError"
    assert failed["passed"] is False
    assert failed["criteria"] == {}
    assert "gizli ayrıntı" not in json.dumps(result, ensure_ascii=False)
    assert ok["passed"] is True
    assert result["summary"]["score"] == {"passed": 1, "total": 2, "ratio": 0.5}


def test_hesap_hatasi_modeli_cagirmaz(run_module, capsys, tmp_path):
    base = copy_reference(tmp_path, drop_estimated_time)
    client = ScriptedClient({"TK2345'in tahmini kalkış saati ne?": list})
    code, result, _ = real(
        run_module, capsys, tmp_path, client, "--soru", "G16", "--data", base
    )
    assert code == 1
    assert client.calls == []
    assert result["runs"][0]["error"] == "hesap_hatasi"
    assert result["runs"][0]["passed"] is False


def test_zarflar_sonuca_girmez(run_module, capsys, tmp_path):
    client = ScriptedClient({Q_G01: summary_script("Bugün 600 uçuş var.")})
    _, result, _ = real(run_module, capsys, tmp_path, client, "--soru", "G01")
    assert "envelope" not in json.dumps(result)
    assert "turns" not in result["runs"][0]


def test_sonuc_utf8_ve_ensure_ascii_false(run_module, capsys, tmp_path):
    client = ScriptedClient({Q_G01: summary_script("Bugün 600 uçuş var.")})
    real(run_module, capsys, tmp_path, client, "--soru", "G01")
    raw = (tmp_path / "out" / "sonuc.json").read_text(encoding="utf-8")
    assert "Bugün" in raw
    assert "\\u" not in raw


def test_sahte_istemci_kopyasi_degismez():
    # Yardımcı kendi kendini sınar: her yeni koşum taze yanıt listesi alır.
    client = ScriptedClient({Q_G01: summary_script("a")})
    first = client.create(messages=[{"content": Q_G01}])
    second = client.create(messages=[{"content": Q_G01}])
    third = client.create(messages=[{"content": Q_G01}])
    assert first.stop_reason == "tool_use"
    assert second.stop_reason == "end_turn"
    assert third.stop_reason == "tool_use"
    assert copy.deepcopy(client.calls)[0]["question"] == Q_G01
