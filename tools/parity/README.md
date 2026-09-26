# Parity Scripts

This folder contains scripts used to verify that the Python port in `rtk_saver/port_9router/` maintains strict 1:1 behavioral parity against the original 9Router (JS / Rust) implementations.

- `dump_samples.py` — generates a suite of canonical tool-output test cases (git diffs, logs, file listings, truncated blobs).
- `js_reference.mjs` — runs the original 9Router JavaScript implementation against the generated samples to produce a reference baseline.
- `parity_check.py` — runs the Python RTK filters against the exact same samples and compares byte-for-byte output against `js_reference.mjs` results.

Usage:
```bash
# 1. Generate fixtures
python3 tools/parity/dump_samples.py samples/

# 2. Produce JS reference output
node tools/parity/js_reference.mjs samples/ > js_out.json

# 3. Compare against Python implementation
python3 tools/parity/parity_check.py js_out.json
```
