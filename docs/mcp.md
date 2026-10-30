# MCP sunucusu

Uçuş tool'larını MCP (stdio) üzerinden Claude Desktop ve Claude Code gibi yerel
istemcilere açar. Kod `mcp_server/server.py`, testleri `tests/test_mcp_server.py`
(API'siz).

## Açılan tool'lar

`get_flight_details`, `get_flight_summary`, `resolve_flight_identity`. Ad, açıklama ve
girdi şeması `backend/tools/contracts/*.json`'dan olduğu gibi gelir; MCP için ayrı
tanım yoktur. `search_documents` (ücretli gömme) ve harita tool'ları açılmaz; adıyla
çağrılırsa `isError: true` ve "Bilinmeyen tool" döner.

## Sonuç biçimi

Tool'un `run_tool` zarfı (`docs/zarf.md`) değiştirilmeden, `ensure_ascii=False` JSON
olarak tek `text` bloğunda döner. `isError` yalnızca `SCHEMA_VALIDATION_FAILED`'da
true'dur (agent döngüsüyle aynı kural); `NOT_FOUND`, `AMBIGUOUS_ENTITY` gibi kodlar
zarf içinde okunur, istemci bunları hata saymaz.

## Çalıştırma

Repo kökünden (stdio; elle çalıştırınca istemci bekler, Ctrl+C ile çık):

```powershell
.\.venv\Scripts\python.exe -m mcp_server
```

Tool'lar veriyi `COPILOT_DATA`'dan okur. MCP sunucusu `.env`'yi yüklemez (`backend.llm`
import edilmez), bu yüzden değişkenler istemci yapılandırmasında `env` ile verilir.
`COPILOT_NOW` doluysa sabit an kullanılır.

### Claude Desktop

`%APPDATA%\Claude\claude_desktop_config.json` içine ekle, Claude Desktop'u tamamen
kapatıp aç (yollar mutlak olmalı):

```json
{
  "mcpServers": {
    "aocc-copilot": {
      "command": "C:\\Users\\turka\\source\\repos\\Kurumsal\\IGA\\2026\\LLM - Claude\\AOCC-Copilot\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server"],
      "cwd": "C:\\Users\\turka\\source\\repos\\Kurumsal\\IGA\\2026\\LLM - Claude\\AOCC-Copilot",
      "env": {
        "COPILOT_DATA": "data/referans/seed42-2026-10-20.json",
        "COPILOT_NOW": "2026-10-20T16:22:00+03:00"
      }
    }
  }
}
```

`cwd` desteklenmezse `COPILOT_DATA`'yı mutlak yol yap.

### Claude Code

```powershell
claude mcp add aocc-copilot -e COPILOT_DATA=data/referans/seed42-2026-10-20.json -e COPILOT_NOW=2026-10-20T16:22:00+03:00 -- .\.venv\Scripts\python.exe -m mcp_server
```

## Sınırlar

- Yalnızca stdio. ChatGPT gibi uzak istemciler HTTP ister; streamable HTTP taşıması
  ayrı iştir.
- stdout protokole ayrılmıştır; sunucu koduna `print` konmaz, log stderr'e gider.
