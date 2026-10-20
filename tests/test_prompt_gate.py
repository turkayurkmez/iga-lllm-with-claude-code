"""prompt-gate.ps1 hook'unun ön filtre davranışı. API çağrısı yapmaz."""

import json
import subprocess
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "prompt-gate.ps1"


def run_gate(stdin: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(GATE)],
        input=stdin,
        capture_output=True,
        timeout=30,
        check=False,
    )


def as_payload(prompt: str) -> bytes:
    return json.dumps({"prompt": prompt}, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("prompt", ["/clear", "/prompt-netlestir x", "  /clear"])
def test_slash_komutu_baglam_eklemez(prompt: str) -> None:
    result = run_gate(as_payload(prompt))
    assert result.returncode == 0
    assert result.stdout.strip() == b""


@pytest.mark.parametrize(
    "prompt",
    ["evet", "Hayır.", "  tamam  ", "B", "2", "onaylıyorum", "HAYIR", "devam et!"],
)
def test_onay_kalibi_baglam_eklemez(prompt: str) -> None:
    result = run_gate(as_payload(prompt))
    assert result.returncode == 0
    assert result.stdout.strip() == b""


@pytest.mark.parametrize("prompt", ["", "   \n"])
def test_bos_prompt_baglam_eklemez(prompt: str) -> None:
    result = run_gate(as_payload(prompt))
    assert result.returncode == 0
    assert result.stdout.strip() == b""


@pytest.mark.parametrize(
    "prompt",
    ["M2 için tool ekle", "Uygun, Bölüm 2'ye geç", "evet, ama önce testleri yaz"],
)
def test_gorev_promptu_baglam_ekler(prompt: str) -> None:
    result = run_gate(as_payload(prompt))
    assert result.returncode == 0
    output = json.loads(result.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    assert "prompt-netlestir" in output["additionalContext"]


@pytest.mark.parametrize("stdin", [b"{bozuk", b"", b'{"baska": 1}'])
def test_bozuk_girdi_engellemez(stdin: bytes) -> None:
    result = run_gate(stdin)
    assert result.returncode == 0
    assert result.stdout.strip() == b""
