# Testing Scripts

This folder contains scripts used to simulate traffic, spin up local proxy targets, and verify that token-saving metrics are logged correctly.

- `capture_server.py` — a lightweight local HTTP echo server to capture outbound payload sizes before and after compression.
- `send_test_traffic.py` — sends structured mock tool outputs (git diffs, logs, grep results) through the LiteLLM proxy to test filters.
- `verify_capture.py` — parses the output of `capture_server.py` to compute and validate compression ratios against baseline expectations.

Usage:
```bash
# Start local echo server
python3 tools/testing/capture_server.py

# Send test payloads
python3 tools/testing/send_test_traffic.py --count 100

# Validate results
python3 tools/testing/verify_capture.py output.json
```
