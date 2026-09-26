# Token Saver for LiteLLM

RTK compression, tool-output dedupe, and Caveman/Ponytail prompt styling,
running **inside the LiteLLM gateway** as a pre-call hook. This is a complete
replacement for the separate 9Router/OmniRoute hop that used to sit in front
of LiteLLM.

One hop, one place to operate, native provider clients end-to-end.

```
Client ──► LiteLLM :4000 ──► Provider (Anthropic / OpenAI / Gemini / OpenRouter)
              │
              ├─ async_pre_call_hook  (rtk_saver, this repo)
              │    1. RTK      — shrink oversized tool_result blobs (12 filters)
              │    2. Dedupe   — collapse repeated identical tool outputs
              │    3. Inject   — append Caveman/Ponytail style instruction
              │    4. Account  — write one metrics record per completed call
              └─ provider receives a request built by LiteLLM's own SDKs
```

Verified against the real 9Router JavaScript: **13/13 reference cases are
byte-identical** (`tools/parity/parity_check.py`), and 151 unit tests pass.

Further reading: architecture and operations docs live in [`docs/`](docs/README.md);
sanitized agent configs in [`harness-examples/`](harness-examples/README.md).

---

## 1. Repository layout

```
rtk_saver/                  ← the product: imported by LiteLLM at runtime
├── callback.py             # TokenSaverLogger (CustomLogger): pre-call hook,
│                           #   config resolution, metrics accounting
├── inject.py               # system-prompt injection per wire format
│                           #   (OpenAI messages / Anthropic input+system)
├── README.md               # ported-vs-custom file map (9Router vs LiteLLM)
├── compress.py             # ─┐ facade re-exports (backward-compat shims):
├── constants.py            #  │ legacy import paths kept working, so tests,
├── prompts.py              #  │ parity tools and config.yaml need no changes
├── filters/                # ─┘
└── port_9router/           # ← the 9Router port: pure deterministic logic
    ├── compress.py         # RTK engine: filter autodetect + dedupe_tools
    ├── constants.py        # filter caps & tunables (mirror Rust/JS defaults)
    ├── prompts.py          # Caveman & Ponytail prompt texts (ported 1:1)
    └── filters/            # 12 RTK filters, byte-parity ported from JS
        ├── git_diff.py  git_log.py  git_status.py  grep.py
        ├── find.py      ls.py       tree.py         build_output.py
        └── dedup_log.py smart_truncate.py  read_numbered.py  search_list.py

tests/                      # 151 tests: filters, behaviour, hook, compress
docs/                       # architecture, gateway-vs-Agent.md, MCP guides
harness-examples/           # sanitized Claude Code / OpenCode / Cline configs
tools/                      # operator tooling & marketplace integration
├── litellm_marketplace.py  # Claude Code plugin & LiteLLM MCP sync CLI
├── analytics/              # reporting & ROI
│   ├── savings_report.py   # aggregate savings from metrics JSONL
│   └── savings_by_key.py   # per-virtual-key savings from the dashboard API
├── testing/                # on-the-wire E2E rig
│   ├── capture_server.py   # mock provider that logs every request body
│   ├── send_test_traffic.py# fires ON/OFF traffic through the gateway
│   └── verify_capture.py   # asserts compression ran, nothing leaked
├── parity/                 # 9Router byte-parity harness
│   ├── parity_check.py     # python-vs-JS comparison
│   ├── js_reference.mjs    # runs the real 9Router JS filters in node
│   └── dump_samples.py     # generates parity sample corpus
└── legacy/                 # superseded shell wrappers (kept for reference)

docker-compose.tokensaver.yml   # gateway + postgres, bind-mounts rtk_saver/
config.yaml                     # models, callback registration, fallbacks
provision_teams.sh              # teams + budgeted virtual keys
.env                            # master/salt keys + provider keys (mode 600)
```


### How `rtk_saver` is wired into LiteLLM (three lines, no patching)

1. **Importable** — compose sets `PYTHONPATH: /app` and bind-mounts the
   package read-only: `./rtk_saver:/app/rtk_saver:ro`. Editing files in this
   repo changes the running gateway after `docker compose ... restart litellm`
   (no rebuild, no image fork).
2. **Registered** — `config.yaml`:
   ```yaml
   litellm_settings:
     callbacks: rtk_saver.callback.proxy_handler_instance
   ```
3. **Configured per key** — LiteLLM passes the virtual key's `metadata` to
   the hook; the hook reads the token saver config from metadata in this
   priority order:
   - **Nested** (API/programmatic): `metadata.token_saver = {enabled, caveman, ...}`
   - **Flat `ts_*`** (dashboard-friendly): `metadata.ts_enabled`, `metadata.ts_caveman`, ...
   - **Plain** (manual edits): `metadata.enabled`, `metadata.caveman`, ...
   - **Legacy**: `metadata.token_saver_enabled`
     Precedence: code defaults ← `TOKEN_SAVER_DEFAULT_CONFIG` env ←
     key metadata ← per-request metadata.

### How `tools/` fit

`tools/` is **operator tooling and client integration** — nothing there runs inside
the gateway. Scripts are grouped by purpose (see `tools/README.md`):

- `litellm_marketplace.py` (CLI alias: `litellm-marketplace` / `litellm-mcp`): discovers
  LiteLLM Claude Code plugins and LiteLLM MCP servers, configuring them across
  Cline, OpenCode, and Claude Code.
- `analytics/savings_report.py`: reads the raw JSONL metrics the hook writes inside the container.
- `analytics/savings_by_key.py`: reads the daily-spend rollup the admin UI renders from
  `GET /user/daily/activity` (per virtual key, priced at the served model's input rate).
- `testing/capture_server.py` + `testing/send_test_traffic.py` + `testing/verify_capture.py`:
  self-contained E2E rig proving on the wire what the hook does without provider keys.
- `parity/parity_check.py` + `parity/js_reference.mjs` + `parity/dump_samples.py`:
  verify Python RTK filters are byte-identical to the original 9Router JavaScript.
- `legacy/`: superseded shell wrappers, kept only for reference.


### The request path in code

`callback.py::apply_token_saver()` runs in this exact order (matching
9Router):

1. **RTK compress** — `compress_messages()` walks every tool-result shape
   (OpenAI string/array tool messages, Anthropic `tool_result` blocks, OpenAI
   Responses `function_call_output`), autodetects the blob type from the
   first 1 KB, and applies one of 12 filters. Blobs under `min_bytes`
   (default 500) are skipped; error traces (`is_error: true`) are preserved
   verbatim.
2. **Dedupe** — `dedupe_tools()` scans `role: tool|function` messages and
   replaces older copies of identical payloads (≥ `min_bytes`) with a one-line
   stub pointing at the newest copy. Returns `{replaced, bytes}` so savings
   are counted.
3. **Inject** — `build_system_additions()` composes the Caveman/Ponytail text
   and `inject_system_prompt()` appends it per wire format (OpenAI
   `messages`, Anthropic `input`+`system`, or messages-style system blocks).
   The internal marker is stripped before send.
4. **Account** — the wire size is measured before and after everything, and
   one JSONL record (bytes, filters hit, key alias, provider-reported token
   usage) is appended when the call completes successfully.

The hook is **fail-open**: any internal error logs and passes the request
through unmodified. It never rewrites `anthropic-beta`, never drops unknown
body fields, and never touches response headers — the three behaviours that
made providers reject the old separate gateway.

---

## 2. Quick start

```bash
# 1. Secrets: master/salt keys are already set; add provider keys you use.
$EDITOR .env        # ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY

# 2. Up (reuses the existing litellm_postgres_data volume — no data loss).
cd /home/mr/project/litellm
docker compose -f docker-compose.tokensaver.yml up -d
sleep 25            # first boot migrates the DB; readiness is the truth:

# 3. Verify
curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  http://localhost:4000/health/readiness
# → {"status":"healthy","db":"connected"}

# 4. Watch the hook fire
docker compose -f docker-compose.tokensaver.yml logs -f litellm | grep TokenSaver
```

Gateway URL is `http://localhost:4000`; examples below assume
`LITELLM_MASTER_KEY` (and optionally `LITELLM_URL=http://localhost:4000`)
are exported from `.env`.

## 3. Models available

Defined in `config.yaml`: `claude-sonnet`, `claude-haiku` (Anthropic),
`gpt-4o` (OpenAI), `gemini-pro` (Google), `or-deepseek` and `or-free`
(OpenRouter; `or-free` costs nothing), plus `mock-capture` (**test-only** —
points at the local capture server; remove the block for production).
Fallbacks: `claude-sonnet→claude-haiku`, `gpt-4o→or-deepseek`.

## 4. Turning the token saver on

### Per virtual key (recommended)

Metadata can be stored in two formats. The **flat `ts_*` format** is
dashboard-friendly (each field visible/editable in the UI). The **nested
format** is more compact for API/programmatic use. Both work; the callback
recognises all of them.

**Flat format** (recommended for dashboard visibility):

```bash
curl -X POST $LITELLM_URL/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{
    "key_alias": "backend-prod",
    "metadata": {
      "ts_enabled": true, "ts_caveman": "lite", "ts_ponytail": "off",
      "ts_rtk": true, "ts_dedupe_tools": true, "ts_min_bytes": 500,
      "ts_note": "Full savings: RTK + dedupe + Caveman-lite"}}'
```

**Nested format** (compact, for API/programmatic use):

```bash
curl -X POST $LITELLM_URL/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{
    "key_alias": "backend-prod",
    "metadata": {"token_saver": {
      "enabled": true, "caveman": "lite", "ponytail": "off",
      "rtk": true, "dedupe_tools": true, "min_bytes": 500}}}'
```

Profile presets worth using:

| Profile        | Metadata                                             | When to use                                                                                           |
| -------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Content**    | `ts_rtk=true, ts_dedupe_tools=true, ts_caveman=off`  | Content/prose work. Compression only — no style injection, output sounds natural.                     |
| **Programmer** | `ts_rtk=true, ts_dedupe_tools=true, ts_caveman=lite` | Long multi-turn agentic/coding sessions where compression gains outweigh the ~1.7 KB injected prompt. |
| **Disabled**   | `ts_enabled=false`                                   | Baseline/A-B comparison and style-sensitive work.                                                     |

These presets are pre-provisioned by `provision_teams.sh` as two teams
(`content` and `programmer`), each with prod and dev keys.

### Gateway-wide default (opt-out rollout)

Uncomment in `docker-compose.tokensaver.yml`, then `up -d`:

```yaml
TOKEN_SAVER_DEFAULT_CONFIG: '{"enabled":true,"caveman":"lite","rtk":true}'
```

### All knobs

| Field          | Values                                                            | Meaning                                         |
| -------------- | ----------------------------------------------------------------- | ----------------------------------------------- |
| `enabled`      | `true` / `false`                                                  | Master switch for this key                      |
| `caveman`      | `off` `lite` `full` `ultra` `wenyan-lite` `wenyan` `wenyan-ultra` | Style instruction appended to the system prompt |
| `ponytail`     | `off` `lite` `full` `ultra`                                       | Second style layer (composable)                 |
| `rtk`          | `true` / `false`                                                  | Tool-blob compression (12 filters)              |
| `dedupe_tools` | `true` / `false`                                                  | Collapse repeated tool outputs                  |
| `min_bytes`    | int (default `500`)                                               | Blobs smaller than this are never touched       |

Per-request A/B override, regardless of key config:

```json
{
  "model": "...",
  "messages": ["…"],
  "metadata": { "token_saver_bypass": true }
}
```

> Keep `caveman`/`ponytail` **off** for code review and precision-critical
> work: they change output style, and their ~1.7 KB prompt can outweigh the
> compression on small single-turn tasks (measured here: +13% tokens on a
> small task with `lite`, −43% with rtk-only).

## 5. Teams & budgets

```bash
export LITELLM_MASTER_KEY=$(grep LITELLM_MASTER_KEY .env | cut -d= -f2)
export LITELLM_URL=http://localhost:4000
./provision_teams.sh
```

Creates two teams with monthly USD budgets, model allowlists, and prod/dev
virtual keys per team:

| Team         | Budget   | Models                            | Token saver                     |
| ------------ | -------- | --------------------------------- | ------------------------------- |
| `content`    | $150/30d | claude-haiku, gemini-pro, or-free | RTK + dedupe only (caveman off) |
| `programmer` | $400/30d | claude-sonnet, gpt-4o             | RTK + dedupe + caveman-lite     |

Keys created: `content-prod`, `content-dev`, `programmer-prod`,
`programmer-dev`. Metadata is stored as flat `ts_*` keys so profiles are
visible and editable in the dashboard. Edit the `TEAMS=` array in the script
to match your org. Clients only ever hold virtual keys — provider keys stay
in `.env` on the gateway host.

## 6. Monitoring: how much did it save?

**1. Live per-request log:**

```bash
docker compose -f docker-compose.tokensaver.yml logs -f litellm | grep TokenSaver
# [RTK] saved 29841B / 30000B (99.5%) via [dedup-log] hits=3 prompt=lite
# [TokenSaver] dedupe=1 net saved 1237B
# [TokenSaver] dedupe=1 net cost 525B (injection > compression) prompt=lite
```

**2. Aggregate savings report** — every completed call appends one record to
`/app/token_saver_metrics.jsonl` inside the container (bytes, filters hit,
key alias, provider-reported token usage). Summarize:

```bash
docker exec litellm-litellm-1 cat /app/token_saver_metrics.jsonl \
  | python3 tools/analytics/savings_report.py -
```

```
  calls deduped          : 5 (5 stubs, 2,430 B removed)
  rtk blob bytes         : 13,308 → 13,308  (saved 0, 0.0%)

  net on the wire (2 calls) — what actually left the gateway:
    before               : 5,744 B
    after                : 5,032 B
    net saved            : 712 B  (12.4%)  ≈ ~178 tokens (heuristic)

  measured usage (on 5 calls with usage data):
    prompt tokens        : 3,748
  per key:
    content-prod    1 calls      1,237 B saved
    programmer-prod 4 calls       -525 B saved
```

Three numbers, three meanings:

- **rtk blob bytes** — what the RTK filters alone removed from tool payloads.
- **net on the wire** — the honest bottom line: RTK + dedupe **minus the
  injected prompt**. Negative on small single-turn tasks; strongly positive
  on long tool-heavy sessions. This is the number to optimize.
- **measured usage** — provider-reported tokens; the money number.
  Money saved ≈ (prompt tokens OFF − prompt tokens ON) × price/token.

Bytes are exact; `≈tokens` is bytes ÷ 4; usage is measured.

**2b. Savings per virtual key** — same numbers the dashboard's Savings tab
renders, aggregated across keys (the dashboard shows one key at a time):

```bash
export LITELLM_MASTER_KEY=sk-...            # from .env
python3 tools/analytics/savings_by_key.py --days 7    # or --start YYYY-MM-DD --end YYYY-MM-DD
```

```
Token Saver — savings per virtual key (2026-09-17 → 2026-09-23, UTC)

  KEY ALIAS                KEY HASH       CALLS  TOKENS SAVED    USD SAVED  TOKENS/CALL
  savings-verify           d390a23dc4f…       3        34,218       0.0428       11,406

  TOTAL                                       3        34,218       0.0428
```

It reads `GET /user/daily/activity` (open-source endpoint, what the admin
UI calls) — **not** `/key/spend/report`, which needs an Enterprise licence.
Rows where compression saved nothing are hidden; pass `--include-zero` to
list every key with traffic. USD is `$0` for models LiteLLM has no input
price for (OpenRouter `:free`); the token count is always real.

**3. On-the-wire E2E proof** (no provider keys needed):

```bash
python3 tools/testing/capture_server.py 18081 &      # mock provider, logs every body
#  ensure the mock-capture block in config.yaml (marked "test only"), then:
docker compose -f docker-compose.tokensaver.yml up -d && sleep 25
TS_KEY_ON=<on-key> TS_KEY_OFF=<off-key> python3 tools/testing/send_test_traffic.py
python3 tools/testing/verify_capture.py              # asserts on captured bodies
```

`testing/verify_capture.py` checks: compression ran on ON calls, OFF calls passed
intact, the injection marker appears exactly on ON calls, and no internal
bookkeeping (`token_saver_stats`) leaks toward the provider. Measured on
this stack: **547 prompt_tokens ON vs 7,859 OFF — a 93% reduction** on a
compression-heavy payload.

**4. Real-world A/B against a real provider** (as done with OpenRouter
`:free`): send one identical payload through an OFF key and an ON key, then
compare `usage.prompt_tokens` in the two responses — the provider itself
reports the saving. Note: for both sides to appear in the metrics file, use
two _enabled_ keys with different profiles (e.g. `content-prod` vs
`programmer-prod`); a fully disabled key bypasses the hook and writes no
record.

## 7. Tests & parity

```bash
python3 -m venv /tmp/tsvenv && /tmp/tsvenv/bin/pip install pyyaml pytest
/tmp/tsvenv/bin/python -m pytest tests/ -q          # 151 passed

# Byte-parity vs the real 9Router JS (needs node + the JS sources):
node tools/parity/js_reference.mjs > /tmp/js_out.json
/tmp/tsvenv/bin/python tools/parity/parity_check.py /tmp/js_out.json
# → byte-identical: 13 / differing: 0 / detect mismatch: 0
```

## 8. Operations runbook

```bash
# Restart after editing config.yaml or any rtk_saver/*.py (bind-mount, no rebuild)
docker compose -f docker-compose.tokensaver.yml restart litellm

# Update the gateway image
docker compose -f docker-compose.tokensaver.yml pull litellm
docker compose -f docker-compose.tokensaver.yml up -d

# Metrics live inside the container FS — archive before recreating:
docker exec litellm-litellm-1 cat /app/token_saver_metrics.jsonl > metrics-backup.jsonl
# Inspect state
docker exec litellm-litellm-1 ls /app/rtk_saver       # the hook package
docker exec litellm-litellm-1 ls /app/rtk_saver/port_9router  # 9Router port
docker exec litellm-db-1 psql -U litellm -d litellm   # keys / teams / spend DB
```

Key rotation: edit `LITELLM_MASTER_KEY` in `.env`, then `up -d`. Virtual keys
remain valid — they are hashed with `LITELLM_SALT_KEY`; rotate that only if
all existing virtual keys must die.

Common failures:

| Symptom                                    | Meaning / fix                                                                                                      |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `readiness` HTTP 000, connection refused   | Gateway still booting (DB migration ≈ 20–30 s on first start). Wait and retry.                                     |
| `401` on `/v1/models`                      | Wrong/missing bearer — use `LITELLM_MASTER_KEY` from `.env`.                                                       |
| `[TokenSaver] metrics write error` in logs | Container FS issue. Calls still succeed (fail-open); metrics for them are lost.                                    |
| `or-free` returns 429 / times out          | Free-tier queueing upstream. Retry, or use a paid alias.                                                           |
| Savings negative in report                 | Expected on small single-turn tasks with `caveman` on — switch that key to the content profile (`ts_caveman=off`). |

## 9. Marketplace & MCP discovery (`litellm-marketplace` / `litellm-mcp`)

LiteLLM hosts Claude Code plugin marketplaces (at `/claude-code/marketplace.json`)
and proxies MCP servers (at `GET /v1/mcp/server`).

`tools/litellm_marketplace.py` (accessible as `litellm-marketplace` or `litellm-mcp` via `~/.local/bin`)
bridges plugins and MCP servers to agents that lack native marketplace discovery
(**Cline CLI**, **OpenCode**, and **Claude Code**).

### Features

- **Plugins & Skills sync**: Fetches plugin git repos from marketplace and extracts `SKILL.md` into:
  - Cline: `~/.cline/skills/<name>/SKILL.md`
  - OpenCode: `~/.config/opencode/skills/<name>/SKILL.md`
  - Claude Code: `~/.claude/skills/<name>/SKILL.md`
- **MCP Server Discovery & Multi-Agent Configuration**:
  - Automatically queries `GET /v1/mcp/server` using `LITELLM_MASTER_KEY` / `.env`.
  - Configures endpoints proxied at `http://<proxy>/<server_name>/mcp` with `Bearer <token>`.
  - Atomically writes target format per agent:
    - **Cline**: `~/.cline/data/settings/cline_mcp_settings.json` (`streamableHttp`)
    - **OpenCode**: `~/.config/opencode/opencode.jsonc` (`remote`, JSONC comment-safe)
    - **Claude Code**: `~/.claude.json` (`http`)
- **State & Manifest**: Tracks installed versions, git caches, and active agent targets in `~/.litellm-marketplace/manifest.json` for clean, safe removal.

### Structural docs

- [`docs/README.md`](docs/README.md) — index of architecture/comparison/MCP guides.
- [`rtk_saver/README.md`](rtk_saver/README.md) — which files are 9Router ports vs LiteLLM-custom.
- [`tools/README.md`](tools/README.md) — tool categorization (analytics / testing / parity / legacy).
- [`harness-examples/README.md`](harness-examples/README.md) — sanitized Claude Code / OpenCode / Cline configs.

### Common Commands

```bash
# Doctor: verify proxy reachability, marketplace endpoint, and agent directories
litellm-marketplace doctor

# --- Claude Code Plugins / Skills ---
litellm-marketplace list                   # list available marketplace plugins
litellm-marketplace install <plugin>       # install plugin skills to all agents
litellm-marketplace update [plugin]        # update installed plugin(s)
litellm-marketplace remove <plugin>        # cleanly uninstall plugin skills

# --- LiteLLM Hosted MCP Servers (using litellm-mcp shorthand) ---
litellm-mcp list                           # discover available servers & agent status
litellm-mcp install deepwiki               # configure deepwiki across cline, opencode, claude
litellm-mcp install postgresql --agent cline # configure postgresql only for cline
litellm-mcp remove <server>                # remove server from configs and manifest
litellm-mcp sync                           # sync all discovered MCP servers to agents
```
