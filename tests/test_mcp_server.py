"""MCP sunucusu sözleşme testleri (docs/mcp.md). API'siz ve ağsız.

Birim testler `mcp_server.server`'ın işlevlerini, uçtan uca test gerçek stdio alt
sürecini MCP istemcisiyle sürer.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_server import server
from mcp_server.server import EXPOSED_TOOLS, call, exposed_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = REPO_ROOT / "backend" / "tools" / "contracts"
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
TK2345_ID = "FL-20261020-0270"


@pytest.fixture(autouse=True)
def tool_env(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)


def envelope_of(result) -> dict:
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    return json.loads(result.content[0].text)


def test_yalnizca_uc_ucus_tool_u_acilir():
    assert EXPOSED_TOOLS == (
        "get_flight_details",
        "get_flight_summary",
        "resolve_flight_identity",
    )
    assert [t.name for t in exposed_tools()] == list(EXPOSED_TOOLS)


def test_tanimlar_kontratla_birebir():
    tools = exposed_tools()
    assert len(tools) == 3
    for tool in tools:
        contract = json.loads((CONTRACTS / f"{tool.name}.json").read_text("utf-8"))
        assert tool.description == contract["description"]
        assert tool.inputSchema == contract["input_schema"]


def test_resolve_zarfi_degistirilmeden_doner():
    result = call("resolve_flight_identity", {"query": "TK2345"})
    envelope = envelope_of(result)
    assert result.isError is False
    assert envelope["error"] is None
    assert envelope["value"]["flight_id"] == TK2345_ID
    assert envelope["tool_version"] == "1.0.0"


def test_bulunamayan_kimlik_hata_degil_zarf_hatasi():
    result = call("resolve_flight_identity", {"query": "ZZ9999"})
    envelope = envelope_of(result)
    assert envelope["error"]["code"] == "NOT_FOUND"
    assert result.isError is False


def test_sema_hatasi_is_error_ve_katman_zarfi():
    result = call("resolve_flight_identity", {"query": "   "})
    envelope = envelope_of(result)
    assert result.isError is True
    assert envelope["error"]["code"] == "SCHEMA_VALIDATION_FAILED"
    assert envelope["author"] == "layer"


def test_disaridaki_tool_cagrilmaz(monkeypatch):
    def fail(*_args):
        raise AssertionError("run_tool çağrılmamalıydı")

    monkeypatch.setattr(server, "run_tool", fail)
    for name in ("search_documents", "focus_map_object", "yok_tool"):
        result = call(name, {})
        assert result.isError is True
        assert name in result.content[0].text


def test_turkce_karakterler_utf8_kalir():
    result = call("resolve_flight_identity", {"query": "ZZ9999"})
    assert "\\u" not in result.content[0].text


async def stdio_session():
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server"],
        cwd=str(REPO_ROOT),
        env={"COPILOT_DATA": REFERENCE, "COPILOT_NOW": NOW},
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        resolved = await session.call_tool(
            "resolve_flight_identity", {"query": "TK2345"}
        )
        return listed, resolved


def test_stdio_uctan_uca():
    listed, resolved = asyncio.run(asyncio.wait_for(stdio_session(), timeout=60))
    names = [t.name for t in listed.tools]
    assert names == list(EXPOSED_TOOLS)
    assert resolved.isError is False
    envelope = json.loads(resolved.content[0].text)
    assert envelope["value"]["flight_id"] == TK2345_ID
