# Internal Architecture of `rtk_saver`

This guide clearly delineates the architectural boundaries, files ported from **9Router**, and the components custom-built for the **LiteLLM Gateway**.

---

## 1. File Categorization & Origin (Port vs Custom)

| File | Category | Origin | Description & Role |
|---|---|---|---|
| `port_9router/filters/*.py` (12 files) | **9Router Port** | `open-sse/rtk/filters/*` & Rust `rtk/src/cmds/*` | Python implementation of the 12 compression filters with strict 1:1 byte parity |
| `port_9router/constants.py` | **9Router Port** | `open-sse/rtk/constants.js` & Rust limits | Volume caps, detection window sizes, and filter limitations |
| `port_9router/prompts.py` | **9Router Port** | `cavemanPrompts.js` & `ponytailPrompt.js` | Style compression prompts for different Caveman and Ponytail levels |
| `port_9router/compress.py` | **9Router Port** | `open-sse/rtk/index.js` | Text compression functions, filter detection, and message traversal |
| `callback.py` | **LiteLLM Custom** | Proprietary development | Direct connection to LiteLLM lifecycle via `CustomLogger` |
| `inject.py` | **LiteLLM Custom** | Proprietary development | Polymorphic prompt injection matching various input schemas |

---

## 2. Ported Sections from 9Router (Core RTK Port)

In the previous project (9Router), tool output compression was handled by JavaScript and Rust cores. To eliminate the network hop and separate process, this logic was ported directly to modern Python:

### A) The 12 Filters (`port_9router/filters/`):
All filters are implemented deterministically and independently without third-party libraries:
- `git_diff.py`: Compresses git diffs based on hunks.
- `git_log.py`: Compresses commit logs up to the allowed 200-line limit.
- `git_status.py`: Compact summary of Modified and Untracked files.
- `grep.py` and `find.py`: Merges results and removes redundant root paths.
- `ls.py` and `tree.py`: Compact formatting of directory structures, hiding noise (`node_modules`, `.git`).
- `build_output.py`: Cleans up tedious compilation and package download messages.
- `dedup_log.py`: Compresses consecutive repeated logs with a `[repeated X times]` label.
- `smart_truncate.py`: Two-way smart truncation of texts over 10MB.
- `read_numbered.py` and `search_list.py`: Processes numbered source files and search lists.

### B) Styler Prompts (`port_9router/prompts.py`):
Styling text is derived from the reference repositories `caveman` and `ponytail`, which curb filler words and useless coding boilerplate.

### C) Text Engine (`port_9router/compress.py`):
The `compress_text` function checks the first 1KB (`DETECT_WINDOW`), automatically detects the appropriate filter, and applies it safely via `safe_apply`.

---

## 3. LiteLLM-Specific Customizations (Gateway-Specific Logic)

These components are designed exclusively for the LiteLLM proxy core:

### A) Hook & Callback (`callback.py`):
- Inherits from base class `litellm.integrations.custom_logger.CustomLogger`.
- Implements `async_pre_call_hook`:
  - Extracts configuration from virtual key metadata (`user_api_key_dict.metadata`).
  - Applies compression to `tool_result` blocks (in both OpenAI and Anthropic formats).
  - Deduplicates historical tool outputs from prior conversation turns.
  - Applies style prompt injection (if enabled).
  - **Fail-Open Design:** On any Exception, errors are logged but the user request is never canceled.
- Implements `async_log_success_event`:
  - Records saved byte details to `/app/token_saver_metrics.jsonl`.
  - Updates LiteLLM's aggregate database table for financial dashboard display (`_update_daily_savings`).

### B) Polymorphic Injection System (`inject.py`):
In 9Router, headers and bodies were converted to an internal format and rewritten, causing some beta headers (`anthropic-beta`) to be dropped. In the current LiteLLM implementation:
- The user's outgoing format remains completely untouched.
- The body structure (OpenAI Messages, Anthropic Messages, Gemini Content) is identified, and the prompt is simply appended (`append`) to the existing system message.

