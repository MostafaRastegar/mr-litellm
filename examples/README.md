# Example Client Configurations

These are sanitized examples of the agent configuration files used to connect
Claude Code, OpenCode, and Cline to the LiteLLM gateway in this project.

**All secrets have been replaced with placeholders:**

| Placeholder | Replace with |
|---|---|
| `sk-YOUR_LITELLM_VIRTUAL_KEY` | A virtual key generated via `POST /key/generate` (with `token_saver` metadata if desired) |
| `sk-YOUR_LITELLM_MASTER_KEY` | The `LITELLM_MASTER_KEY` from `.env` (used only for MCP endpoints) |

## Files and install locations

| Example file | Installs to |
|---|---|
| `claude-code/settings.json` | `~/.claude/settings.json` |
| `claude-code/.claude.json (mcpServers excerpt)` | `~/.claude.json` — merge only the `mcpServers` block |
| `opencode/opencode.jsonc` | `~/.config/opencode/opencode.jsonc` |
| `cline/cline_mcp_settings.json` | `~/.cline/data/settings/cline_mcp_settings.json` |

## How the pieces fit together

- **Model traffic** flows through the LiteLLM gateway at `http://localhost:4000`
  (`/v1` for OpenAI-compatible clients, Anthropic-compatible env vars for Claude Code).
  The RTK token saver hook (`rtk_saver.callback`) compresses tool outputs in-process.
- **MCP servers** (e.g. `deepwiki`, `postgresql`) are hosted by LiteLLM itself at
  `http://localhost:4000/<server>/mcp` and authenticate with the master key.
- **Skills / plugins** are installed from the built-in marketplace at
  `http://localhost:4000/claude-code/marketplace.json` using the
  `litellm-marketplace` CLI.

## Quick setup

```bash
# 1. Start the stack
docker compose -f docker-compose.tokensaver.yml up -d

# 2. Create a virtual key (per-team / per-agent)
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{
    "key_alias": "my-agent",
    "metadata": {"token_saver": {"enabled": true, "caveman": "lite", "rtk": true}}
  }'

# 3. Copy the example for your editor and replace the placeholders
# 4. Verify connectivity
litellm-marketplace doctor
litellm-mcp list
```
