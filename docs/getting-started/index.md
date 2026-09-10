---
icon: lucide/plug
---

# Connect

The server is hosted on Hugging Face. Run yourself, it speaks two transports: **stdio** (the
default, for a client that launches the process) and **streamable HTTP** (for a client that
connects to a URL).

## The hosted server

`https://riksarkivet-kansallisarkisto-mcp.hf.space/mcp` — streamable HTTP, no key, no sign-up.

```bash
claude mcp add --transport http kansallisarkisto https://riksarkivet-kansallisarkisto-mcp.hf.space/mcp
```

For claude.ai, add a custom connector with the same URL. The Space sleeps after 48 hours
without traffic; the first request wakes it, so a client that times out once will usually
connect on the second try.

## Running it yourself

A self-run server needs LanceDB tables to search. See [Local Install](local.md) for building
them; without them the server still starts, and every tool call answers with a clear
missing-table message.

### Claude Code — stdio, from a clone

```bash
claude mcp add kansallisarkisto -- uv run kansallisarkisto-mcp
```

Run it from the repository root, or add `--cwd /path/to/kansallisarkisto-mcp`, so the server
resolves `data/` next to the project.

### Claude Code — streamable HTTP

```bash
KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp   # in one shell
claude mcp add --transport http kansallisarkisto http://localhost:8000/mcp
```

### Claude Desktop / Cursor / Windsurf

Add it as a stdio server invoking `uv run kansallisarkisto-mcp` with the repository as the
working directory, or as a streamable-HTTP server pointed at `http://localhost:8000/mcp`.

### MCP Inspector

```bash
make inspect
```

## Verifying the connection

A self-run server logs its table status at boot, to stderr:

```
INFO ...server: LanceDB at /home/you/kansallisarkisto-mcp/data — tables: df, voudintilit
```

If it says `has no 'df' table` or `has no 'voudintilit' table`, the URI is resolving somewhere
without that table — check `KA_LANCEDB_URI` and the working directory. Over HTTP, `/ready`
answers the same question: 200 once both tables can be searched, 503 with the reason until
then.
