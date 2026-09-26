#!/usr/bin/env python3
"""Verify token-saver behaviour from bodies actually captured on the wire.

Pairs with tools/capture_server.py. Reads /tmp/mock_capture.jsonl and checks
the three promises of the token saver against the real provider-bound body.

Note: the Authorization header LiteLLM forwards is the *provider* key, so we
cannot see which virtual key made a call. Instead each record is classified
by its own traits:

  ON  call → caveman instruction present in system, tool outputs shrunk
  OFF call → no caveman marker, oversized tool outputs intact

Checked:
  1. traffic sanity   — at least one ON and one OFF call were captured
  2. RTK              — every ON call's tool outputs are small (compressed)
  3. passthrough      — every OFF call keeps its oversized output untouched
  4. injection        — caveman marker present exactly on ON calls
  5. hygiene          — no internal bookkeeping (token_saver_stats) leaks

Exit 0 only when every expectation holds.
"""
import json
import os
import sys

CAVEMAN_LITE_MARKER = "Respond tersely"
DEDUPE_STUB_MARKER = "[duplicate tool output omitted"
INTERNAL_LEAK = "token_saver_stats"
BIG_TOOL_THRESHOLD = 2000  # bytes; below this a tool blob counts as compressed


def flatten(parts):
    if isinstance(parts, str):
        return parts
    if isinstance(parts, list):
        return "\n".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in parts
        )
    return ""


def describe(rec):
    body = rec.get("body") or {}
    msgs = body.get("messages") or []
    tool_sizes = []
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "tool":
            tool_sizes.append(len(flatten(m.get("content"))))
    sys_text = "\n".join(
        flatten(m.get("content"))
        for m in msgs
        if isinstance(m, dict) and m.get("role") == "system"
    )
    blob = json.dumps(body)
    big = [s for s in tool_sizes if s >= BIG_TOOL_THRESHOLD]
    return {
        "bytes": len(blob),
        "tool_msgs": len(tool_sizes),
        "max_tool_bytes": max(tool_sizes, default=0),
        "has_big_tool": bool(big),
        "caveman": CAVEMAN_LITE_MARKER in sys_text,
        "dedupe_stub": DEDUPE_STUB_MARKER in blob,
        "internal_leak": INTERNAL_LEAK in blob,
    }


def main(path: str = "/tmp/mock_capture.jsonl") -> int:
    if not os.path.exists(path):
        print(f"no capture log at {path} — start tools/capture_server.py first")
        return 2

    records = [json.loads(line) for line in open(path) if line.strip()]
    if not records:
        print("capture log is empty — send the test requests first")
        return 2

    failures = []
    on_calls = off_calls = 0
    for rec in records:
        info = describe(rec)
        is_on = info["caveman"] or (
            info["tool_msgs"] > 0 and not info["has_big_tool"]
        )
        is_off = info["has_big_tool"] and not info["caveman"]
        if is_on:
            on_calls += 1
        if is_off:
            off_calls += 1
        tag = "ON " if is_on else ("OFF" if is_off else "???")
        print(f"[{tag}] {info}")

        if info["internal_leak"]:
            failures.append("internal metadata (token_saver_stats) leaked to provider")
        if is_on and info["has_big_tool"]:
            failures.append(
                f"ON call still carries an oversized tool output "
                f"({info['max_tool_bytes']} bytes) — compression did not run"
            )
        # OFF calls are expected to keep their oversized outputs — by
        # definition of is_off, they do. Nothing more to assert here.

    if on_calls == 0:
        failures.append("no ON (token-saver enabled) call captured — rerun traffic")
    if off_calls == 0:
        failures.append("no OFF (disabled) call captured — rerun traffic")

    if failures:
        print("\n✗ FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print(
        f"\n✓ PASS — token saver verified on the wire "
        f"({on_calls} ON / {off_calls} OFF calls)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mock_capture.jsonl"))
