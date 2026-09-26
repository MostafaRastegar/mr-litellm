#!/usr/bin/env python3
"""Aggregate token-saver savings from the proxy's metrics JSONL.

Records are written by rtk_saver.callback on every completed call that had
compression activity. Each line looks like:

    {"ts": "...", "call_id": "...", "key_alias": "backend-prod", "model": "...",
     "rtk": {"bytes_before": 4100, "bytes_after": 310, "hits": [...]},
     "dedupe_replaced": 2, "prompt": "lite/off",
     "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}}

Usage:
    python tools/savings_report.py /app/token_saver_metrics.jsonl
    docker exec litellm-litellm-1 cat /app/token_saver_metrics.jsonl \
        | python3 tools/savings_report.py -

The report answers exactly "how much did we save": raw bytes removed from
provider-bound prompts, dedupe stubs applied, plus the real provider token
usage for those calls (captured from each response), and per-filter / per-key
breakdowns. The token estimate for byte savings is heuristic (4 bytes/token);
the usage numbers are measured, not estimated.
"""
import json
import sys
from collections import Counter, defaultdict


def load(path: str):
    if path == "-":
        return [json.loads(line) for line in sys.stdin if line.strip()]
    try:
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        print(f"no metrics file at {path}")
        print("records appear there after compressed calls complete successfully")
        return []


def main(path: str = "/app/token_saver_metrics.jsonl") -> int:
    recs = load(path)
    if not recs:
        print("no records yet — nothing to report")
        return 0

    before = after = 0
    rtk_calls = dedupe_calls = dedupe_stubs = 0
    dedupe_bytes = 0
    wire_calls = 0
    wire_before_total = wire_after_total = 0
    filters: Counter = Counter()
    per_key: dict = defaultdict(lambda: {"calls": 0, "saved": 0})
    prompt_tokens = completion_tokens = total_tokens = 0
    usage_seen = 0

    for r in recs:
        rtk = r.get("rtk") or {}
        b, a = rtk.get("bytes_before", 0), rtk.get("bytes_after", 0)
        if b:
            rtk_calls += 1
            before += b
            after += a
            for h in rtk.get("hits", []):
                filters[h.get("filter", "?")] += 1
        d = r.get("dedupe_replaced", 0)
        if d:
            dedupe_calls += 1
            dedupe_stubs += d
            dedupe_bytes += r.get("dedupe_bytes", 0) or 0
        wb, wa = r.get("wire_before", 0) or 0, r.get("wire_after", 0) or 0
        if wb:
            wire_calls += 1
            wire_before_total += wb
            wire_after_total += wa
        key = r.get("key_alias") or "(unknown key)"
        per_key[key]["calls"] += 1
        per_key[key]["saved"] += (wb - wa) if wb else (b - a)
        usage = r.get("usage") or {}
        if usage.get("total_tokens"):
            usage_seen += 1
            prompt_tokens += usage.get("prompt_tokens", 0) or 0
            completion_tokens += usage.get("completion_tokens", 0) or 0
            total_tokens += usage.get("total_tokens", 0) or 0

    saved = before - after
    pct = (saved / before * 100) if before else 0.0
    net = wire_before_total - wire_after_total
    net_pct = (net / wire_before_total * 100) if wire_before_total else 0.0

    print("Token Saver — savings report")
    print(f"  records                : {len(recs)}")
    print(f"  calls compressed (RTK) : {rtk_calls}")
    print(
        f"  calls deduped          : {dedupe_calls}"
        f" ({dedupe_stubs} stubs, {dedupe_bytes:,} B removed)"
    )
    print()
    print(f"  rtk blob bytes         : {before:,} → {after:,}"
          f"  (saved {saved:,}, {pct:.1f}%)")
    if wire_calls:
        print()
        print(f"  net on the wire ({wire_calls} calls) — what actually left the gateway:")
        print(f"    before               : {wire_before_total:,} B")
        print(f"    after                : {wire_after_total:,} B")
        if net >= 0:
            print(
                f"    net saved            : {net:,} B  ({net_pct:.1f}%)"
                f"  ≈ ~{net // 4:,} tokens (heuristic)"
            )
        else:
            print(
                f"    net COST             : {abs(net):,} B  ({abs(net_pct):.1f}%)"
                f"  — injected prompt outweighed compression"
            )
    if usage_seen:
        print()
        print(f"  measured usage (on {usage_seen} calls with usage data):")
        print(f"    prompt tokens        : {prompt_tokens:,}")
        print(f"    completion tokens    : {completion_tokens:,}")
        print(f"    total tokens         : {total_tokens:,}")
    if filters:
        print()
        print("  per filter:")
        for name, n in filters.most_common():
            print(f"    {name:<18} {n:>4}")
    print()
    print("  per key:")
    for key, v in sorted(per_key.items(), key=lambda kv: -kv[1]["saved"]):
        print(f"    {key:<24} {v['calls']:>4} calls  {v['saved']:>10,} B saved")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/app/token_saver_metrics.jsonl"))
