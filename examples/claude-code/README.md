# Claude Code MCP servers (`~/.claude.json`)

The `mcpServers` block lives at the top level of `~/.claude.json`. Only that
block is shown here; the rest of the file (history, projects, machine state)
is local and should not be copied.

`mcpServers.json`:
```json
{
  "mcpServers": {
    "deepwiki": {
      "type": "http",
      "url": "http://localhost:4000/deepwiki/mcp",
      "headers": {
        "Authorization": "Bearer sk-YOUR_LITELLM_MASTER_KEY"
      }
    },
    "postgresql": {
      "type": "http",
      "url": "http://localhost:4000/postgresql/mcp",
      "headers": {
        "Authorization": "Bearer sk-YOUR_LITELLM_MASTER_KEY"
      }
    }
  }
}
```

Notes:
- Claude Code uses `"type": "http"` for hosted MCP endpoints (Cline uses
  `streamableHttp`, OpenCode uses `remote`).
- Model configuration lives separately in `settings.json` (see `../claude-code/settings.json`).
