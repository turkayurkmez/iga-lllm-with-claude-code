"""AOCC Copilot uçuş tool'larını MCP (stdio) üzerinden açar (docs/mcp.md).

Tool tanımları `backend.tools.tool_definitions()`'tan, sonuçlar `run_tool`'dan gelir;
zarf (docs/zarf.md) değiştirilmeden JSON metni olarak döner. Bu modül `backend.llm`'i
import etmez, yani API anahtarı gerekmez. stdout MCP protokolüne ayrılmıştır; log yalnızca
stderr'e yazılır.
"""

import asyncio
import json
import logging

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from backend.tools import run_tool, tool_definitions

# Dışarıya açılan tool'lar; search_documents (ücretli gömme) ve harita tool'ları yok.
EXPOSED_TOOLS = (
    "get_flight_details",
    "get_flight_summary",
    "resolve_flight_identity",
)

SERVER_NAME = "aocc-copilot"

logger = logging.getLogger(__name__)


def exposed_tools() -> list[types.Tool]:
    """Kontrattan gelen tanımların açılan alt kümesi, EXPOSED_TOOLS sırasıyla."""
    by_name = {d["name"]: d for d in tool_definitions()}
    return [
        types.Tool(
            name=name,
            description=by_name[name]["description"],
            inputSchema=by_name[name]["input_schema"],
        )
        for name in EXPOSED_TOOLS
    ]


def _error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], isError=True
    )


def call(name: str, arguments: dict | None) -> types.CallToolResult:
    """Tool'u çalıştırır; zarfın tamamı metin olarak döner.

    `isError` yalnızca SCHEMA_VALIDATION_FAILED'da true (agent döngüsüyle aynı kural,
    bkz. experiments/function_calling/loop_envelope.py).
    """
    if name not in EXPOSED_TOOLS:
        return _error_result(f"Bilinmeyen tool: {name}")
    envelope = run_tool(name, arguments or {})
    error = envelope.get("error")
    is_error = bool(error) and error.get("code") == "SCHEMA_VALIDATION_FAILED"
    text = json.dumps(envelope, ensure_ascii=False)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], isError=is_error
    )


def build_server() -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return exposed_tools()

    # Argümanı run_tool doğrular; MCP katmanı ikinci kez doğrulamaz, böylece şema
    # hatası da zarf olarak (author=layer) döner.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
        return await asyncio.to_thread(call, name, arguments)

    return server


async def serve() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
