#!/usr/bin/env python3
"""Per-virtual-key savings, read straight from the LiteLLM dashboard API.

`savings_report.py` answers "how much did we save" from the metrics JSONL the
hook writes locally. This tool answers the other question operators ask —
"which virtual key saved what" — from the same numbers the LiteLLM dashboard
renders, i.e. the daily-spend rollup the proxy itself maintains.

Why the dashboard's numbers and not the JSONL: LiteLLM prices the tokens
compression removed at the served model's input rate and rolls them up per UTC
day per key, so this view is the authoritative one, it survives the container
being recreated (the JSONL lives on the container filesystem), and it works for
keys whose traffic never landed in a local JSONL.

Where the data comes from:

    GET /user/daily/activity            (paginated, per-day)
        -> results[].breakdown.api_keys[<api_key_hash>] = {
               "metrics":  {compression_saved_tokens, compression_savings_spend, ...},
               "metadata": {key_alias, team_id, user_id, user_email},
           }

The activity endpoint is what the admin UI calls, and it is available on the
open-source proxy. The per-key ``/key/spend/report`` and
``/global/spend/report`` endpoints require a LiteLLM Enterprise licence, which
is why this tool deliberately uses neither.

Usage:
    export LITELLM_MASTER_KEY=sk-...          # or pass --api-key
    python tools/savings_by_key.py                        # last 7 days (incl. today, UTC)
    python tools/savings_by_key.py --days 30
    python tools/savings_by_key.py --start 2026-09-01 --end 2026-09-23
    python tools/savings_by_key.py --include-zero         # keep keys with no savings
    python tools/savings_by_key.py --json                 # machine-readable output

Point it elsewhere with LITELLM_PROXY_URL (default http://localhost:4000).

Exit codes: 0 on success (including "no rows"), 1 on a transport/auth error.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

DEFAULT_PROXY_URL = "http://localhost:4000"
ACTIVITY_PATH = "/user/daily/activity"
PAGE_SIZE = 100


def _iso_day(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def _resolve_window(args: argparse.Namespace) -> tuple[str, str]:
    """Start/end dates for the query. Defaults to the last 7 UTC days, today included."""
    if args.start and args.end:
        return args.start, args.end
    today = datetime.now(timezone.utc).date()
    end = today if not args.end else datetime.strptime(args.end, "%Y-%m-%d").date()
    start = (
        datetime.strptime(args.start, "%Y-%m-%d").date()
        if args.start
        else end - timedelta(days=args.days - 1)
    )
    return _iso_day(start), _iso_day(end)


def _fetch_activity(base_url: str, api_key: str, start: str, end: str) -> list[dict]:
    """Every daily bucket in the window, following the endpoint's pagination."""
    results: list[dict] = []
    page = 1
    while True:
        query = (
            f"start_date={start}&end_date={end}&page={page}"
            f"&page_size={PAGE_SIZE}&include_current_utc_day=true"
        )
        url = f"{base_url.rstrip('/')}{ACTIVITY_PATH}?{query}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SystemExit(f"HTTP {exc.code} from {url}\n{detail}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"cannot reach {url}: {exc.reason}") from exc

        results.extend(payload.get("results") or [])

        meta = payload.get("metadata") or {}
        if not meta.get("has_more"):
            return results
        page += 1


def _collect_per_key(results: list[dict]) -> dict[str, dict]:
    """Fold every (day, api_key) bucket into one row per key.

    ``breakdown.api_keys`` carries the per-key rollup for that day, so the
    totals here are the sum of the daily per-key numbers — never a sum of the
    per-model rows, which would double count.
    """
    per_key: dict[str, dict] = {}
    for day in results:
        breakdown = day.get("breakdown") or {}
        for key_hash, entry in (breakdown.get("api_keys") or {}).items():
            metrics = entry.get("metrics") or {}
            metadata = entry.get("metadata") or {}
            row = per_key.setdefault(
                key_hash or "(no key)",
                {
                    "key_hash": key_hash,
                    "key_alias": metadata.get("key_alias") or "(no alias)",
                    "team_id": metadata.get("team_id"),
                    "user_email": metadata.get("user_email"),
                    "tokens_saved": 0,
                    "usd_saved": 0.0,
                    "api_requests": 0,
                    "days": set(),
                },
            )
            row["tokens_saved"] += int(metrics.get("compression_saved_tokens") or 0)
            row["usd_saved"] += float(metrics.get("compression_savings_spend") or 0.0)
            row["api_requests"] += int(metrics.get("api_requests") or 0)
            row["days"].add(day.get("date"))
    return per_key


def _short(value: str | None, width: int) -> str:
    if not value:
        return "-"
    return value if len(value) <= width else value[: width - 1] + "…"


def _print_table(rows: list[dict], start: str, end: str, show_zero: bool) -> None:
    if not rows:
        print(f"no savings recorded between {start} and {end}")
        print("(keys with token_saver enabled write a record per compressed call)")
        return

    shown = rows if show_zero else [r for r in rows if r["tokens_saved"] > 0]
    if not shown:
        print(f"no per-key savings between {start} and {end}")
        print(f"{len(rows)} key(s) had traffic in the window but none saved tokens.")
        return

    alias_w, hash_w = 24, 12
    print(f"Token Saver — savings per virtual key ({start} → {end}, UTC)")
    print()
    print(
        f"  {'KEY ALIAS':<{alias_w}} {'KEY HASH':<{hash_w}}"
        f" {'CALLS':>7} {'TOKENS SAVED':>13} {'USD SAVED':>12} {'TOKENS/CALL':>12}"
    )
    for row in shown:
        calls = row["api_requests"]
        per_call = row["tokens_saved"] // calls if calls else 0
        print(
            f"  {_short(row['key_alias'], alias_w):<{alias_w}}"
            f" {_short(row['key_hash'], hash_w):<{hash_w}}"
            f" {calls:>7,} {row['tokens_saved']:>13,} {row['usd_saved']:>12.4f} {per_call:>12,}"
        )

    total_tokens = sum(r["tokens_saved"] for r in shown)
    total_usd = sum(r["usd_saved"] for r in shown)
    total_calls = sum(r["api_requests"] for r in shown)
    print()
    print(
        f"  {'TOTAL':<{alias_w + hash_w + 1}} {total_calls:>7,}"
        f" {total_tokens:>13,} {total_usd:>12.4f}"
    )
    print()
    print("  key alias is what a human edits; the hash is the key row in the DB.")
    print("  USD is priced per request at the served model's input rate; a model")
    print("  without a price (e.g. an OpenRouter ':free' model) reports tokens, $0.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Per-virtual-key token-saver savings, from the LiteLLM dashboard API.",
    )
    parser.add_argument(
        "--proxy-url",
        default=os.getenv("LITELLM_PROXY_URL", DEFAULT_PROXY_URL),
        help=f"gateway base URL (default: {DEFAULT_PROXY_URL}, env LITELLM_PROXY_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LITELLM_MASTER_KEY", ""),
        help="proxy master key (env LITELLM_MASTER_KEY)",
    )
    parser.add_argument("--start", help="first day, YYYY-MM-DD (UTC)")
    parser.add_argument("--end", help="last day, YYYY-MM-DD (UTC)")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="window size when --start/--end are omitted (default: 7)",
    )
    parser.add_argument(
        "--include-zero",
        action="store_true",
        help="also list keys that had traffic but saved nothing",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args(argv)

    if not args.api_key:
        print("no proxy key: export LITELLM_MASTER_KEY=sk-... or pass --api-key")
        return 1

    start, end = _resolve_window(args)
    results = _fetch_activity(args.proxy_url, args.api_key, start, end)
    per_key = _collect_per_key(results)

    rows = sorted(
        per_key.values(),
        key=lambda r: (-r["tokens_saved"], -r["usd_saved"], r["key_alias"]),
    )
    for row in rows:
        row["active_days"] = len(row.pop("days"))

    if args.json:
        print(
            json.dumps(
                {
                    "start_date": start,
                    "end_date": end,
                    "days_returned": len(results),
                    "keys": rows,
                },
                indent=2,
            )
        )
        return 0

    _print_table(rows, start, end, args.include_zero)
    return 0


if __name__ == "__main__":
    sys.exit(main())


