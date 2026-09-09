---
icon: lucide/plug
---

# Connect

The server speaks two transports: **stdio** (the default, for a client that launches the
process) and **streamable HTTP** (for a client that connects to a URL).

Both need a LanceDB table to search. See [Local Install](local.md) for building one; without
it the server still starts, and every tool call answers with a clear missing-table message.

## Claude Code — stdio, from a clone

```bash
claude mcp add kansallisarkisto -- uv run kansallisarkisto-mcp
```

Run it from the repository root, or add `--cwd /path/to/kansallisarkisto-mcp`, so the server
resolves `data/` next to the project.

## Claude Code — streamable HTTP

```bash
KA_MCP_TRANSPORT=http uv run kansallisarkisto-mcp   # in one shell
claude mcp add --transport http kansallisarkisto http://localhost:8000/mcp
```

## Claude Desktop / Cursor / Windsurf

Add it as a stdio server invoking `uv run kansallisarkisto-mcp` with the repository as the
working directory, or as a streamable-HTTP server pointed at `http://localhost:8000/mcp`.

## MCP Inspector

```bash
make inspect
```

## Verifying the connection

The server logs its table status at boot, to stderr:

```
INFO ...server: LanceDB at /home/you/kansallisarkisto-mcp/data — tables: df
```

If it says `has no 'df' table`, the URI is resolving somewhere without data — check
`KA_LANCEDB_URI` and the working directory.
