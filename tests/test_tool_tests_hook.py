"""tool-tests.ps1 hook'unun davranışı. API çağrısı yapmaz.

Hook'un koşturduğu test hedefi TOOL_HOOK_TEST_TARGET ile tmp'deki küçük bir yeşil ya
da kırmızı test dosyasına çevrilir; tests/test_tools.py burada koşmaz.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "tool-tests.ps1"
TOOL_FILE = REPO_ROOT / "backend" / "tools" / "get_flight_summary.py"


@pytest.fixture
def targets(tmp_path) -> dict[str, Path]:
    green = tmp_path / "test_yesil.py"
    green.write_text("def test_yesil():\n    assert True\n", encoding="utf-8")
    red = tmp_path / "test_kirmizi.py"
    red.write_text("def test_kirmizi():\n    assert 1 == 2\n", encoding="utf-8")
    return {"green": green, "red": red}


def run_hook(stdin: bytes, target: Path) -> subprocess.CompletedProcess[bytes]:
    assert HOOK.exists(), ".claude/hooks/tool-tests.ps1 yok"
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "TOOL_HOOK_TEST_TARGET": str(target),
    }
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HOOK)],
        input=stdin,
        capture_output=True,
        timeout=120,
        check=False,
        env=env,
    )


def edit_payload(path: str) -> bytes:
    payload = {"tool_name": "Edit", "tool_input": {"file_path": path}}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("stdin", [b"", b"{bozuk", b"[]", b'{"tool_input": {}}'])
def test_bozuk_ya_da_yolsuz_girdide_sessiz_cikar(stdin, targets):
    result = run_hook(stdin, targets["red"])
    assert result.returncode == 0
    assert result.stdout.strip() == b""
    assert result.stderr.strip() == b""


@pytest.mark.parametrize(
    "path",
    [
        str(REPO_ROOT / "backend" / "main.py"),
        str(REPO_ROOT / "tests" / "test_tools.py"),
        str(REPO_ROOT / "backend" / "tools_eski" / "x.py"),
        str(REPO_ROOT / "docs" / "tools.md"),
    ],
)
def test_tool_disi_dosyada_test_kosmaz(path, targets):
    # Hedef kırmızı olduğu için test koşsaydı çıkış 2 olurdu.
    result = run_hook(edit_payload(path), targets["red"])
    assert result.returncode == 0
    assert result.stdout.strip() == b""
    assert result.stderr.strip() == b""


@pytest.mark.parametrize(
    "path",
    [
        str(TOOL_FILE),
        str(TOOL_FILE).replace("\\", "/"),
        str(TOOL_FILE).upper(),
        str(REPO_ROOT / "backend" / "tools" / "contracts" / "get_flight_details.json"),
        str(REPO_ROOT / "backend" / "tools" / "__init__.py"),
    ],
)
def test_tool_dosyasinda_yesilse_sessiz_cikar(path, targets):
    result = run_hook(edit_payload(path), targets["green"])
    assert result.returncode == 0
    assert result.stdout.strip() == b""
    assert result.stderr.strip() == b""


def test_tool_dosyasinda_kirmiziysa_claudea_bildirir(targets):
    result = run_hook(edit_payload(str(TOOL_FILE)), targets["red"])
    assert result.returncode == 2
    message = result.stderr.decode("utf-8")
    assert "test_kirmizi" in message
    assert "failed" in message
    assert result.stdout.strip() == b""


def test_tool_response_yolu_da_kullanilir(targets):
    payload = {"tool_name": "Write", "tool_response": {"filePath": str(TOOL_FILE)}}
    stdin = json.dumps(payload).encode("utf-8")
    assert run_hook(stdin, targets["red"]).returncode == 2


def test_test_hedefi_yoksa_bildirir(tmp_path):
    result = run_hook(edit_payload(str(TOOL_FILE)), tmp_path / "test_yok.py")
    assert result.returncode == 2
    assert result.stderr.strip() != b""
