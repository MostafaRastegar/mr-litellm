#!/usr/bin/env python3
"""Capture server — stands in for an LLM provider during token-saver testing.

Listens locally and logs every POSTed body to a JSONL file, so you can verify
exactly what LiteLLM (token saver included) put on the wire toward a provider.
Works with a throwaway `mock-capture` model in config.yaml:

    - model_name: mock-capture
      litellm_params:
        model: openai/mock-capture
        api_base: http://172.21.0.1:18081/v1     # docker bridge gateway
        api_key: mock-key

Run:   python tools/capture_server.py [port]      (default 18081)
Log:   /tmp/mock_capture.jsonl  (one JSON record per request: path/headers/body)
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG_PATH = "/tmp/mock_capture.jsonl"


class CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = {"_unparseable": raw[:2000]}
        with open(LOG_PATH, "a") as fh:
            fh.write(
                json.dumps(
                    {"path": self.path, "headers": dict(self.headers), "body": body}
                )
                + "\n"
            )
        # Report usage proportional to what actually arrived: the token saver
        # shrinks provider-bound prompts, so the mock's token count reflects
        # the post-compression size (~4 bytes per token, like most tokenizers
        # on repetitive log text).
        prompt_tokens = max(1, len(raw) // 4)
        resp = json.dumps(
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 0,
                "model": "mock-capture",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "mock-ok"},
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": 1,
                    "total_tokens": prompt_tokens + 1,
                },
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp.encode())
        self.wfile.flush()

    def do_GET(self):  # health probes etc.
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # keep test output quiet
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18081
    print(f"capture server on 0.0.0.0:{port} → {LOG_PATH}", flush=True)
    HTTPServer(("0.0.0.0", port), CaptureHandler).serve_forever()
