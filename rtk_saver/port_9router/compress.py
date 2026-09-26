"""RTK core: compress tool_result content in LLM request bodies.

Port of 9Router open-sse/rtk/index.js — compressMessages / compressKiroFormat /
compressText / formatRtkLog.
"""

from typing import Any, Optional

from .constants import MIN_COMPRESS_SIZE, RAW_CAP
from .filters import auto_detect_filter, safe_apply


def compress_text(text: str, stats: dict, shape: str) -> str:
    bytes_in = len(text)
    stats["bytes_before"] += bytes_in

    if bytes_in < MIN_COMPRESS_SIZE or bytes_in > RAW_CAP:
        stats["bytes_after"] += bytes_in
        return text

    fn = auto_detect_filter(text)
    if fn is None:
        stats["bytes_after"] += bytes_in
        return text

    out = safe_apply(fn, text)

    # Safety: never return empty, never grow the input
    if not out or len(out) == 0 or len(out) >= bytes_in:
        stats["bytes_after"] += bytes_in
        return text

    stats["bytes_after"] += len(out)
    stats["hits"].append(
        {
            "shape": shape,
            "filter": getattr(fn, "filter_name", None) or getattr(fn, "__name__", "?"),
            "saved": bytes_in - len(out),
        }
    )
    return out


def _compress_kiro_format(body: dict) -> Optional[dict]:
    stats = {"bytes_before": 0, "bytes_after": 0, "hits": []}
    try:
        state = body.get("conversationState") or {}
        all_messages = list(state.get("history") or [])
        if state.get("currentMessage"):
            all_messages.append(state["currentMessage"])

        for msg in all_messages:
            tool_results = (
                (msg or {}).get("userInputMessage", {})
                .get("userInputMessageContext", {})
                .get("toolResults")
            )
            if not isinstance(tool_results, list):
                continue
            for tr in tool_results:
                if (tr or {}).get("status") == "error":
                    continue
                content = (tr or {}).get("content")
                if not isinstance(content, list):
                    continue
                for idx, part in enumerate(content):
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        content[idx]["text"] = compress_text(
                            part["text"], stats, "kiro-tool-result"
                        )
    except Exception as exc:  # noqa: BLE001
        print(f"[RTK] compressKiroFormat error: {exc}", flush=True)
        return None
    return stats


def compress_messages(body: dict, enabled: bool = True) -> Optional[dict]:
    """Compress tool_result content in-place. Returns stats or None."""
    if not enabled or not body:
        return None

    # Kiro format: conversationState.history + conversationState.currentMessage
    if body.get("conversationState"):
        return _compress_kiro_format(body)

    items = None
    if isinstance(body.get("messages"), list):
        items = body["messages"]
    elif isinstance(body.get("input"), list):
        items = body["input"]
    if items is None:
        return None

    stats = {"bytes_before": 0, "bytes_after": 0, "hits": []}
    try:
        for msg in items:
            if not isinstance(msg, dict):
                continue

            # Shape 4: OpenAI Responses — {type:"function_call_output", output: str|[...]}
            if msg.get("type") == "function_call_output":
                output = msg.get("output")
                if isinstance(output, str):
                    msg["output"] = compress_text(
                        output, stats, "openai-responses-string"
                    )
                elif isinstance(output, list):
                    for part in output:
                        if (
                            isinstance(part, dict)
                            and part.get("type") == "input_text"
                            and isinstance(part.get("text"), str)
                        ):
                            part["text"] = compress_text(
                                part["text"], stats, "openai-responses-array"
                            )
                continue

            # Shape 1: OpenAI tool message — {role:"tool", content: "string"}
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                msg["content"] = compress_text(msg["content"], stats, "openai-tool")
                continue

            content = msg.get("content")
            if not isinstance(content, list):
                continue

            # Shape 1b: OpenAI tool message — content:[{type:"text", text:"..."}]
            if msg.get("role") == "tool":
                for part in content:
                    if (
                        isinstance(part, dict)
                        and part.get("type") == "text"
                        and isinstance(part.get("text"), str)
                    ):
                        part["text"] = compress_text(
                            part["text"], stats, "openai-tool-array"
                        )
                continue

            # Shape 2/3: blocks array with tool_result entries
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                if block.get("is_error") is True:
                    continue  # preserve error traces

                block_content = block.get("content")
                if isinstance(block_content, str):
                    block["content"] = compress_text(
                        block_content, stats, "claude-string"
                    )
                elif isinstance(block_content, list):
                    for part in block_content:
                        if (
                            isinstance(part, dict)
                            and part.get("type") == "text"
                            and isinstance(part.get("text"), str)
                        ):
                            part["text"] = compress_text(
                                part["text"], stats, "claude-array"
                            )
    except Exception as exc:  # noqa: BLE001
        print(f"[RTK] compressMessages error: {exc}", flush=True)
        return None

    return stats


def format_rtk_log(stats: Optional[dict]) -> Optional[str]:
    """Format a log line from RTK stats."""
    if not stats or not stats.get("hits"):
        return None
    saved = stats["bytes_before"] - stats["bytes_after"]
    pct = f"{saved / stats['bytes_before'] * 100:.1f}" if stats["bytes_before"] else "0"
    filters = ",".join(sorted({h["filter"] for h in stats["hits"]}))
    return (
        f"[RTK] saved {saved}B / {stats['bytes_before']}B ({pct}%) "
        f"via [{filters}] hits={len(stats['hits'])}"
    )


def dedupe_tools(items: list[Any]) -> int:
    """Collapse identical repeated tool outputs in long conversations.

    Port of RTK's dedupeTools: scans role "tool"/"function" messages; when the
    exact same payload repeats, replaces the older copies with a stub. Keeps the
    most recent occurrence intact.
    """
    seen: dict[str, list[int]] = {}
    for idx, msg in enumerate(items):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") not in ("tool", "function"):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            key = content
        elif isinstance(content, list):
            key = "\x00".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            )
        else:
            continue
        if len(key) < MIN_COMPRESS_SIZE:
            continue
        seen.setdefault(key, []).append(idx)

    replaced = 0
    saved = 0
    for positions in seen.values():
        if len(positions) < 2:
            continue
        stub = f"[duplicate tool output omitted — see message #{positions[-1]}]"
        for idx in positions[:-1]:  # keep the newest
            msg = items[idx]
            if isinstance(msg.get("content"), str):
                saved += len(msg["content"]) - len(stub)
                msg["content"] = stub
            else:
                saved += (
                    sum(
                        len(p.get("text", ""))
                        for p in msg["content"]
                        if isinstance(p, dict) and isinstance(p.get("text"), str)
                    )
                    - len(stub)
                )
                msg["content"] = [{"type": "text", "text": stub}]
            replaced += 1
    return {"replaced": replaced, "bytes": max(saved, 0)}
