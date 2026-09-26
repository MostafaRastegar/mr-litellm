#!/usr/bin/env python3
"""Send test traffic through the proxy to exercise the token saver.

Prerequisites (see README "Monitoring" section):
  * capture server running:  python3 tools/capture_server.py 18081 &
  * mock-capture model in config.yaml and gateway restarted
  * three virtual keys with token_saver metadata, exported as:
      TS_KEY_ON    (token_saver enabled, caveman=lite)
      TS_KEY_OFF   (token_saver disabled)

Each call carries 3 identical ~10KB tool outputs. With the saver on, RTK's
dedup-log filter shrinks them; with it off, they pass through intact. The
mock provider reports prompt_tokens proportional to received bytes, so the
printed numbers directly show the measured saving.
"""
import json
import os
import sys
import urllib.request

KEYS = [
    (os.getenv("TS_KEY_ON", ""), "ts-on  "),
    (os.getenv("TS_KEY_OFF", ""), "ts-off "),
]


def main() -> int:
    missing = [tag for key, tag in KEYS if not key]
    if missing:
        print("export TS_KEY_ON / TS_KEY_OFF first (see script docstring)")
        return 2
    url = os.getenv("TS_URL", "http://localhost:4000/v1/chat/completions")
    rc = 0
    for key, tag in KEYS:
        msgs = [{"role": "user", "content": "run build"}]
        for i in range(3):
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": f"t{i}",
                    "content": "ERROR spam trace line 42\n" * 400,
                }
            )
        body = json.dumps(
            {"model": "mock-capture", "messages": msgs, "max_tokens": 5}
        ).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
            },
        )
        try:
            r = urllib.request.urlopen(req, timeout=30)
            u = json.load(r)["usage"]
            print(
                f"{tag}: HTTP {r.status}  provider-reported prompt_tokens = "
                f"{u['prompt_tokens']}"
            )
        except Exception as e:  # noqa: BLE001
            print(tag, "->", e)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
