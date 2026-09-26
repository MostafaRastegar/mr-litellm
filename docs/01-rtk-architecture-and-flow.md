# RTK Token Saver Architecture & Request Lifecycle in LiteLLM

This document serves as the technical and architectural reference for understanding the mechanics, request flow, and configuration of the Token Saver (RTK) system inside the LiteLLM proxy.

---

## 1. Problem Statement & Solution Background (Why We Deprecated 9Router)

In agentic coding sessions, the vast majority of input tokens are consumed by heavy tool outputs (e.g., `git diff`, `git log`, test suite logs, `grep` searches, and directory trees) along with verbose model pleasantries and filler text.

Previously, a separate network hop and service called **9Router** handled this compression. However, 9Router introduced:
- An extra Single Point of Failure (SPOF) and network latency.
- Reliance on rewriting request bodies which stripped standard headers (such as `anthropic-beta`).
- Fragmented logging, making it difficult to aggregate cost and savings metrics.

**Current Solution:**
The RTK Token Saver is implemented **natively and in-process** inside LiteLLM as a `CustomLogger` plugin. There are no extra hops or sidecar servers. Requests are routed straight through LiteLLM's native SDK clients to upstream providers (Anthropic, OpenAI, Gemini, OpenRouter) without modified wire formats.

---

## 2. Request Lifecycle Flow in LiteLLM

When any client (such as Cline, OpenCode, Claude Code, or custom scripts) makes a request to port `4000`, the following sequence executes in milliseconds:

```
[Client: IDE / Agent / CLI Script]
             │
             ▼
      LiteLLM Gateway (:4000)
             │
             ▼
    ┌─────────────────────────────────────────────────────────────┐
    │              rtk_saver.callback (Pre-Call Hook)             │
    │                                                             │
    │  1. RTK Compress:                                           │
    │     - Sniffs the first 1KB of tool output to detect format  │
    │     - Applies the matching filter out of 12 deterministic    │
    │       filters                                               │
    │     - Skips blobs < 500 bytes or unmatched raw logs         │
    │                                                             │
    │  2. Tool Deduplication:                                     │
    │     - Compares tool outputs against previous conversation   │
    │       history                                               │
    │     - Replaces repeated historical blobs with a one-line    │
    │       reference stub                                        │
    │                                                             │
    │  3. Prompt Styling (Caveman / Ponytail):                    │
    │     - Appends succinctness instructions to the system prompt│
    │     - Handles OpenAI messages / Anthropic / Gemini schemas  │
    │                                                             │
    │  4. Accounting & Metrics:                                   │
    │     - Measures before/after byte counts                     │
    │     - Prepares compression_savings metadata for dashboard   │
    └─────────────────────────────────────────────────────────────┘
             │
             ▼
     Dispatch to Upstream Provider (Native SDK Call)
             │
             ▼
    ┌─────────────────────────────────────────────────────────────┐
    │            rtk_saver.callback (Success Event Hook)          │
    │                                                             │
    │  - Appends record to /app/token_saver_metrics.jsonl         │
    │  - Prices saved tokens based on model rate cards            │
    │  - Updates the dashboard daily-spend rollup DB table        │
    └─────────────────────────────────────────────────────────────┘
             │
             ▼
[Final response returned to client]
```

### Fail-Open Design:
If the request body is malformed, or if any filter encounters an unexpected edge-case or exception, the system never blocks the request (`fail-open`). The exception is logged for observability, and the unmodified raw payload is forwarded to the provider to guarantee 100% gateway availability.


---

## 3. The 12 RTK Compression Filters

The RTK filters reside under `rtk_saver/port_9router/filters/` and are implemented deterministically with strict 1:1 byte-level parity against the 9Router upstream reference:

1. **`git_diff`:** Compresses git diffs, strips redundant context lines, and focuses on modified hunks.
2. **`git_log`:** Summarizes git histories and drops verbose commit metadata.
3. **`git_status`:** Collapses file statuses (Modified/Untracked) into single, readable rows.
4. **`grep`:** Merges adjacent match lines and deduplicates identical results.
5. **`find`:** Abbreviates filesystem search output and prunes root paths.
6. **`ls`:** Reformats directory listings into a compact, human-readable format.
7. **`tree`:** Shrinks large directory trees by summarizing and hiding low-signal subtrees.
8. **`build_output`:** Cleans up noisy compilation/download progress lines, retaining only errors and final exit codes.
9. **`dedup_log`:** Collapses consecutive repeated log messages into `[repeated X times]` counters.
10. **`smart_truncate`:** Truncates massive text blobs intelligently while preserving critical headers and footers.
11. **`read_numbered`:** Optimizes output of numbered source files to reduce sequential line overhead.
12. **`search_list`:** Compresses search-list and filtered output arrays.

> **Key Insight:** RTK filters never inject or append any extra words or instructions; they strictly operate as byte-reducing, syntax-aware compressors for tool outputs.

---

## 4. Prompt Styling & Injection (Caveman & Ponytail)

The prompt injection module is responsible for modifying model styling and output behaviors to ensure responses are reduced in verbosity and complexity, dramatically cutting down expensive output tokens.

### Prompt Injection Metrics:

| Style / Level | Characters | Words | Lines | Est. Input Tokens | Purpose & Behavior |
|---|---|---|---|---|---|
| **Caveman lite** | 1,736 | 256 | 1 line | **~430 tokens** | Removes greetings, introductory sentences, and filler; direct, technical structure |
| **Caveman full** | 1,834 | 265 | 1 line | **~450 tokens** | Strips prepositions and commands telegraphic short responses for fast coding |
| **Caveman ultra** | 1,678 | 246 | 1 line | **~420 tokens** | Extreme verbal compactness (maximum output savings) |
| **Ponytail lite** | 1,561 | 253 | 1 line | **~390 tokens** | Provides the requested code, but suggests one-line dependency-free alternatives |
| **Ponytail full** | 1,567 | 251 | 1 line | **~390 tokens** | Mandates standard library usage, preventing unnecessary abstractions or classes |
| **Ponytail ultra** | 1,611 | 259 | 1 line | **~400 tokens** | Eliminates boilerplate aggressively (strict YAGNI) |

### Token Synergy & Economic Justification:
- Enabling both styles simultaneously (e.g., `caveman: lite` + `ponytail: lite`) adds **approximately 820 tokens** to the system prompt.
- In a typical 10-turn coding session:
  - **Input overhead cost:** Negligible (input token rates are very cheap compared to output tokens).
  - **Model output savings:** Hundreds of lines of boilerplate, redundant code explanations, and chat filler are eliminated, yielding **several thousands of output tokens** in dollar savings per session.
- **Flexible Controls:** For teams handling copywriting, translation, or textual analysis, styling prompts are fully disabled (`ts_caveman=off`, `ts_ponytail=off`), preserving 100% natural tone while still running RTK output compression and deduplication.




---

## 5. Configuration Guide

### A) Setting Metadata on Virtual Keys (Recommended):
The recommended approach is setting token-saver behaviors directly in the virtual key metadata:

```bash
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{
    "key_alias": "backend-team-dev",
    "metadata": {
      "ts_enabled": true,
      "ts_rtk": true,
      "ts_dedupe_tools": true,
      "ts_caveman": "lite",
      "ts_ponytail": "off",
      "ts_min_bytes": 500
    }}'
```

### B) Predefined Profiles:
1. **Programmer Profile (Agentic Coding & Agents):**
   `ts_rtk=true, ts_dedupe_tools=true, ts_caveman=lite`
   Maximum savings in long agentic coding sessions.
2. **Content Profile (Copywriting, Translation, Text Analysis):**
   `ts_rtk=true, ts_dedupe_tools=true, ts_caveman=off, ts_ponytail=off`
   Compresses tool outputs while leaving the model's natural tone completely untouched.
3. **Disabled Profile (A/B Testing & Comparison):**
   `ts_enabled=false`
   Disables the hook entirely for direct comparison of baseline quality and token usage.

---

## 6. Monitoring & ROI (Savings Reporting)

### 1. Live server console logs:
```bash
docker compose -f docker-compose.tokensaver.yml logs -f litellm | grep TokenSaver
# Example output:
# [RTK] saved 29841B / 30000B (99.5%) via [dedup-log] hits=3 prompt=lite
# [TokenSaver] dedupe=1 net saved 1237B
```

### 2. Aggregated report from the local metrics log:
```bash
docker exec litellm-litellm-1 cat /app/token_saver_metrics.jsonl | python3 tools/analytics/savings_report.py -
```

### 3. Official dashboard report per virtual key (Dollar estimate):
```bash
export LITELLM_MASTER_KEY=sk-...
python3 tools/analytics/savings_by_key.py --days 7
```
This command queries LiteLLM's database directly to calculate the dollar savings based on model rates.

