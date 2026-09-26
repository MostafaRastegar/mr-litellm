"""Differential parity check: our Python port vs 9Router's original JS filters.

Usage:
    python tools/dump_samples.py /tmp/rtk_src/parity_samples.json
    node tools/js_reference.mjs > /tmp/js_out.json
    python tools/parity_check.py /tmp/js_out.json

A differing sample is not automatically a bug — it must be inspected to decide
whether the port or the upstream JS is at fault.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rtk_saver.filters import auto_detect_filter, resolve_filter  # noqa: E402
from tools.dump_samples import SAMPLES  # noqa: E402


def main(js_path: str = "/tmp/js_out.json") -> int:
    if not os.path.exists(js_path):
        print(f"missing JS reference output: {js_path}")
        print("run: node tools/js_reference.mjs > /tmp/js_out.json")
        return 2

    with open(js_path) as fh:
        js = json.load(fh)

    identical = 0
    differing = []
    filter_mismatch = []

    for name, text in SAMPLES.items():
        ref = js.get(name)
        if ref is None:
            continue

        py_fn = auto_detect_filter(text)
        py_filter = getattr(py_fn, "filter_name", None) if py_fn else None

        if py_filter != ref["filter"]:
            filter_mismatch.append((name, ref["filter"], py_filter))

        # Force the JS-selected filter to separate "detect differs" from
        # "filter implementation differs".
        js_filter_name = ref["filter"]
        forced_fn = resolve_filter(js_filter_name) if js_filter_name else None
        forced_out = forced_fn(text) if forced_fn else text

        if forced_out == ref["output"]:
            identical += 1
        else:
            differing.append(
                {
                    "name": name,
                    "filter": js_filter_name,
                    "js_len": len(ref["output"]),
                    "py_len": len(forced_out),
                    "js_head": ref["output"][:160],
                    "py_head": forced_out[:160],
                }
            )

    print(f"samples compared : {len(SAMPLES)}")
    print(f"byte-identical   : {identical}")
    print(f"differing output : {len(differing)}")
    print(f"detect mismatch  : {len(filter_mismatch)}")

    if filter_mismatch:
        print("\n-- detect mismatches (js -> py) --")
        for name, jsf, pyf in filter_mismatch:
            print(f"  {name}: {jsf} -> {pyf}")

    if differing:
        print("\n-- differing outputs --")
        for d in differing:
            print(f"\n  [{d['name']}] filter={d['filter']}")
            print(f"    js ({d['js_len']}B): {d['js_head']!r}")
            print(f"    py ({d['py_len']}B): {d['py_head']!r}")

    return 0 if not differing and not filter_mismatch else 1


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "/tmp/js_out.json"
    sys.exit(main(arg))
