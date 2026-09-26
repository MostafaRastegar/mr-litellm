# Developer Tooling & Scripts (`tools/`)

This directory contains utility scripts, agent management CLIs, test harnesses, and reporting scripts, organized by their functional purpose.

---

## 1. Directory Structure

- **Root (`tools/`)**: Primary CLI tools.
  - `litellm_marketplace.py` — Multi-purpose CLI client (installed as `litellm-marketplace` and `litellm-mcp`) for installing Claude Code skills onto Cline/OpenCode and connecting to hosted MCP servers.
- **`analytics/`**: ROI reporting and financial metrics.
  - `savings_report.py` — Analyzes local `/app/token_saver_metrics.jsonl` logs to calculate byte/token savings.
  - `savings_by_key.py` — Queries LiteLLM's database to report dollar savings broken down per virtual key.
- **`testing/`**: Mock servers and traffic generators for validating filters and metrics.
  - `capture_server.py` — Local mock HTTP server to capture outbound traffic from LiteLLM.
  - `send_test_traffic.py` — Sends heavy mock payloads through the proxy to test hook behaviors.
  - `verify_capture.py` — Validates captured traffic against correctness rules.
- **`parity/`**: Byte-for-byte parity tests against original 9Router reference code.
  - `dump_samples.py` — Generates canonical text samples for comparison.
  - `js_reference.mjs` — Runs legacy JS 9Router filters to produce a baseline.
  - `parity_check.py` — Compares our Python filter output byte-by-byte against the JS baseline.
- **`legacy/`**: Deprecated shell scripts (superseded by `litellm_marketplace.py`).
  - `sync_cline_skills.sh`
  - `sync_opencode_skills.sh`

---

## 2. Usage by Role

### A) Daily Usage & Agent Management (Developers & End-Users)
The `litellm_marketplace.py` tool is globally available as `litellm-marketplace` and `litellm-mcp`:
```bash
# Check environment & agent health
litellm-marketplace doctor

# Manage skills & plugins
litellm-marketplace list
litellm-marketplace install <plugin_name>
litellm-marketplace remove <plugin_name>

# Manage & register corporate MCP tools
litellm-mcp list
litellm-mcp install deepwiki
litellm-mcp sync
```

### B) Financial Monitoring & Reporting (DevOps & Admins)
To observe the effectiveness of the compression hook:
```bash
# Detailed byte & filter breakdown from local server logs:
docker exec litellm-litellm-1 cat /app/token_saver_metrics.jsonl | python3 tools/analytics/savings_report.py -

# Official dollar-savings report based on model pricing from the dashboard:
export LITELLM_MASTER_KEY=sk-...
python3 tools/analytics/savings_by_key.py --days 7
```

### C) 9Router Parity Testing & Verification (Engineers)
If you modify filters and want to verify strict behavioral parity against 9Router:
```bash
python3 tools/parity/dump_samples.py /tmp/parity_samples.json
node tools/parity/js_reference.mjs > /tmp/js_out.json
python3 tools/parity/parity_check.py /tmp/js_out.json
```
Also, for live traffic simulation of the hook:
```bash
# Start local capture server
python3 tools/testing/capture_server.py 18081 &

# Send test payloads
TS_KEY_ON=<on-key> TS_KEY_OFF=<off-key> python3 tools/testing/send_test_traffic.py

# Validate results
python3 tools/testing/verify_capture.py
```
