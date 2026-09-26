"""Token Saver for LiteLLM — RTK + Caveman + Ponytail inside the gateway.

Drop-in replacement for a separate 9Router/OmniRoute hop. Everything happens
in-process during the pre-call phase, so the provider receives a request built
by LiteLLM's own native SDK clients — no third-party gateway sits in the path.

That matters for providers that reject rewritten requests (dropped/replaced
`anthropic-beta`, mangled body fields). We only ever *append* to the system
prompt and only ever *shrink* tool_result content; we never touch beta headers,
never rewrite response headers, and never drop unknown fields.

Enablement is per virtual key via `metadata.token_saver`:

    {
      "token_saver": {
        "enabled": true,
        "caveman": "lite",       // off | lite | full | ultra | wenyan*
        "ponytail": "off",       // off | lite | full | ultra
        "rtk": true,             // compress tool_result blobs
        "dedupe_tools": true,    // collapse repeated tool outputs
        "min_bytes": 500         // skip tiny blobs
      }
    }

A global default can be supplied through `TOKEN_SAVER_DEFAULT_CONFIG` (JSON)
so the rollout can be opt-out instead of opt-in.
"""

import json
import os
import time
from typing import Any, Literal, Optional

from .port_9router.compress import compress_messages, dedupe_tools, format_rtk_log
from .inject import detect_wire_format, inject_system_prompt, strip_injected_marker
from .port_9router.prompts import CAVEMAN_PROMPTS, PONYTAIL_PROMPTS


try:  # LiteLLM may be absent in a pure-unit-test environment
    from litellm.integrations.custom_logger import CustomLogger
except Exception:  # noqa: BLE001

    class CustomLogger:  # type: ignore[no-redef]
        """Minimal stand-in so the module imports without LiteLLM installed."""


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "caveman": "off",
    "ponytail": "off",
    "rtk": True,
    "dedupe_tools": True,
    "min_bytes": 500,
}

_TRUTHY = {"1", "true", "yes", "on", "enabled"}

# ── Savings accounting ────────────────────────────────────────────────
# One JSON line per completed call. Inspect with:
#   docker exec litellm-litellm-1 cat /app/token_saver_metrics.jsonl \
#     | python3 tools/savings_report.py -
#
# The same per-call savings are also published to the LiteLLM dashboard: the
# request metadata carries LiteLLM's ``compression_savings`` key, which the
# proxy prices at the model's input rate and rolls up per UTC day per key —
# that feeds the Savings tab on a virtual key and the Cost Optimization page.
# See ``_record_compression_savings``.
METRICS_PATH = os.getenv("TOKEN_SAVER_METRICS_PATH", "/app/token_saver_metrics.jsonl")

# Bytes → tokens for the dashboard savings record. Same heuristic the offline
# report uses (tools/savings_report.py: "≈tokens is bytes ÷ 4").
BYTES_PER_TOKEN = 4

# In-memory handoff from pre-call → success-event, keyed by litellm_call_id.
_pending: dict[str, dict[str, Any]] = {}


def _saved_bytes(stats: dict) -> int:
    """Bytes of prompt the saver removed: RTK filters plus dedupe stubs.

    Mirrors the accounting in tools/savings_report.py so the dashboard and the
    offline report agree on the underlying number.
    """
    rtk = stats.get("rtk") or {}
    rtk_saved = max(int(rtk.get("bytes_before", 0) or 0) - int(rtk.get("bytes_after", 0) or 0), 0)
    dedupe_saved = max(int(stats.get("dedupe_bytes", 0) or 0), 0)
    return rtk_saved + dedupe_saved


def _record_compression_savings(data: dict, stats: dict) -> None:
    """Publish this request's savings so LiteLLM's dashboard can show them.

    LiteLLM reads the request metadata key ``compression_savings``
    (``{tokens_before, tokens_after, tokens_saved, source}``) when it writes
    the spend log, prices ``tokens_saved`` at the served model's input rate,
    and rolls it up per UTC day per virtual key. That rollup is what feeds the
    Savings tab on a key and the Cost Optimization page — so writing this one
    key is enough; no proxy patch or extra endpoint is involved.

    Only ``tokens_saved`` is priced, so the savings are reported exactly. The
    tokens still in the prompt are not known here (compression sees tool blobs,
    not the whole conversation), so ``tokens_after`` stays 0 rather than
    carrying a figure nobody measured.
    """
    try:
        saved_bytes = _saved_bytes(stats)
        tokens_saved = saved_bytes // BYTES_PER_TOKEN
        if tokens_saved <= 0:
            # Nothing measurable was removed: record nothing rather than a
            # zero-valued row LiteLLM would price at $0 and store anyway.
            return

        savings = {
            "tokens_before": tokens_saved,  # tokens that were in the prompt
            "tokens_after": 0,  # tokens they were reduced to (all removed)
            "tokens_saved": tokens_saved,
            # Literal in LiteLLM's CompressionSavingsMetadata: the only value
            # the spend-log reader accepts.
            "source": "compression_interception",
        }

        # Chat/completions-style requests carry proxy metadata under
        # ``metadata``; /v1/messages, /v1/responses, batches and files seed
        # ``litellm_metadata`` instead. LiteLLM reads back whichever bucket the
        # route created, so reuse it and never introduce the other one — on
        # Anthropic Messages ``metadata`` is the provider's own API field.
        bucket = data.get("metadata")
        if not isinstance(bucket, dict):
            bucket = data.get("litellm_metadata")
        if not isinstance(bucket, dict):
            bucket = {}
            data["litellm_metadata"] = bucket
        bucket["compression_savings"] = savings
    except Exception as exc:  # noqa: BLE001 - accounting must never break a call
        print(f"[TokenSaver] savings report error (fail-open): {exc}", flush=True)


def _record_metrics(call_id: str, stats: dict, kwargs: Any) -> None:
    """Append one savings record when the call completes successfully."""
    try:
        usage = getattr(kwargs.get("response_obj") if kwargs else None, "usage", None)
        usage = getattr(usage, "model_dump", lambda: dict(usage))()
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "call_id": call_id,
            "key_alias": ((kwargs or {}).get("litellm_params") or {}).get("metadata", {}).get(
                "user_api_key_alias"
            )
            or (((kwargs or {}).get("litellm_metadata") or {}).get("key_alias") or ""),
            "model": (kwargs or {}).get("model", ""),
            "rtk": stats.get("rtk"),
            "dedupe_replaced": stats.get("dedupe_replaced", 0),
            "dedupe_bytes": stats.get("dedupe_bytes", 0),
            "wire_before": stats.get("wire_before", 0),
            "wire_after": stats.get("wire_after", 0),
            "prompt": f"{stats.get('caveman')}/{stats.get('ponytail')}",
            "usage": usage or {},
        }
        with open(METRICS_PATH, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception as exc:  # noqa: BLE001 - metrics must never break calls
        print(f"[TokenSaver] metrics write error: {exc}", flush=True)
    finally:
        _pending.pop(call_id, None)


def _env_default_config() -> dict[str, Any]:
    raw = os.getenv("TOKEN_SAVER_DEFAULT_CONFIG")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception as exc:  # noqa: BLE001
        print(f"[TokenSaver] bad TOKEN_SAVER_DEFAULT_CONFIG: {exc}", flush=True)
    return {}


_FLAT_KEYS = {"enabled", "caveman", "ponytail", "rtk", "dedupe_tools", "min_bytes"}


def _read_flat_metadata(meta: dict) -> dict[str, Any]:
    """Read token_saver fields stored as flat top-level keys.

    Dashboard-friendly format — each field is individually visible/editable:
        {"ts_enabled": true, "ts_caveman": "lite", "ts_rtk": true, ...}

    Falls back to plain names too (enabled, caveman, ...) for manual edits.
    """
    out: dict[str, Any] = {}
    for key in _FLAT_KEYS:
        ts_val = meta.get(f"ts_{key}")
        plain_val = meta.get(key)
        val = ts_val if ts_val is not None else plain_val
        if val is not None:
            out[key] = val
    return out


def resolve_config(
    user_api_key_dict: Any, data: Optional[dict] = None
) -> dict[str, Any]:
    """Merge defaults <- env config <- key metadata <- per-request metadata."""
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_env_default_config())

    key_meta = getattr(user_api_key_dict, "metadata", None) or {}
    if isinstance(key_meta, dict):
        saver = key_meta.get("token_saver")
        if isinstance(saver, dict):
            # Nested format: {"token_saver": {"enabled": true, "caveman": "lite", ...}}
            cfg.update(saver)
        else:
            # Flat / dashboard-friendly: {"ts_enabled": true, "ts_caveman": "lite", ...}
            flat = _read_flat_metadata(key_meta)
            if flat:
                cfg.update(flat)
            elif "token_saver_enabled" in key_meta:
                # Legacy single-flag format
                cfg["enabled"] = bool(key_meta["token_saver_enabled"])

    if isinstance(data, dict):
        req_meta = data.get("metadata")
        if isinstance(req_meta, dict):
            saver = req_meta.get("token_saver")
            if isinstance(saver, dict):
                cfg.update(saver)

    return cfg


def is_enabled(cfg: dict[str, Any]) -> bool:
    value = cfg.get("enabled", False)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return bool(value)


def _level(cfg: dict[str, Any], key: str) -> str:
    value = cfg.get(key)
    if isinstance(value, bool):
        # Boolean is not a valid level string (off|lite|full|ultra|wenyan*).
        # Dashboard checkboxes may yield JSON true/false; treat as "off" so the
        # system doesn't silently emit a bogus "true" level into metrics and
        # prompt composition.  Only warn when True (the surprising case).
        if value is True:
            print(
                f"[TokenSaver] config '{key}' set to boolean True — "
                f"expected a string level (off/lite/full/ultra). Using 'off'.",
                flush=True,
            )
        return "off"
    if value is None or value == "":
        return "off"
    return str(value).strip().lower()


def build_system_additions(cfg: dict[str, Any]) -> str:
    """Compose the Caveman and/or Ponytail instruction block."""
    parts: list[str] = []

    caveman_level = _level(cfg, "caveman")
    if caveman_level in CAVEMAN_PROMPTS:
        parts.append(CAVEMAN_PROMPTS[caveman_level])

    ponytail_level = _level(cfg, "ponytail")
    if ponytail_level in PONYTAIL_PROMPTS:
        parts.append(PONYTAIL_PROMPTS[ponytail_level])

    return "\n\n".join(parts)


def _wire_bytes(data: dict) -> int:
    """Approximate provider-bound prompt size (serialized messages/input)."""
    items = data.get("messages")
    if not isinstance(items, list):
        items = data.get("input")
    if not isinstance(items, list):
        return 0
    try:
        return len(json.dumps(items, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 - accounting must never break calls
        return 0


def apply_token_saver(
    data: dict,
    cfg: dict[str, Any],
    call_type: str = "",
) -> Optional[dict]:
    """Mutate `data` in place. Returns a stats dict, or None when untouched."""
    stats: dict[str, Any] = {
        "rtk": None,
        "dedupe_replaced": 0,
        "caveman": _level(cfg, "caveman"),
        "ponytail": _level(cfg, "ponytail"),
        "injected": False,
    }

    items = None
    if isinstance(data.get("messages"), list):
        items = data["messages"]
    elif isinstance(data.get("input"), list):
        items = data["input"]

    size_before = _wire_bytes(data)

    # 1. RTK — compress tool_result content
    if cfg.get("rtk", True) and items is not None:
        rtk_stats = compress_messages(data, enabled=True)
        if rtk_stats:
            stats["rtk"] = rtk_stats

    # 2. dedupe repeated tool outputs
    if cfg.get("dedupe_tools", True) and items is not None:
        dedupe_stats = dedupe_tools(items)
        stats["dedupe_replaced"] = dedupe_stats["replaced"]
        stats["dedupe_bytes"] = dedupe_stats["bytes"]

    # 3. Caveman / Ponytail prompt injection
    additions = build_system_additions(cfg)
    if additions:
        wire = detect_wire_format(data, call_type)
        stats["injected"] = inject_system_prompt(data, additions, wire)

    # 4. Internal bookkeeping must never reach the provider
    strip_injected_marker(data)

    # 5. Net wire accounting: measure AFTER the marker strip so the numbers
    #    match what is actually sent upstream. Positive delta = saved bytes,
    #    negative delta = the injected prompt outweighed the compression.
    stats["wire_before"] = size_before
    stats["wire_after"] = _wire_bytes(data)

    return stats


def summarize(stats: Optional[dict]) -> str:
    if not stats:
        return "[TokenSaver] no-op"
    bits = []
    rtk_line = format_rtk_log(stats.get("rtk"))
    if rtk_line:
        bits.append(rtk_line)
    if stats.get("dedupe_replaced"):
        bits.append(f"dedupe={stats['dedupe_replaced']}")
    if "wire_before" in stats:
        net = stats["wire_before"] - stats["wire_after"]
        if net > 0:
            bits.append(f"net saved {net}B")
        elif net < 0:
            bits.append(f"net cost {abs(net)}B (injection > compression)")
    if stats.get("injected"):
        style = stats.get("caveman", "off")
        tail = stats.get("ponytail", "off")
        if tail != "off":
            style = (
                f"{style}+ponytail:{tail}" if style != "off" else f"ponytail:{tail}"
            )
        bits.append(f"prompt={style}")
    return "[TokenSaver] " + (" ".join(bits) if bits else "no-op")


class TokenSaverLogger(CustomLogger):
    """LiteLLM proxy hook implementing the token saver."""

    async def async_pre_call_hook(
        self,
        user_api_key_dict: Any,
        cache: Any,
        data: dict,
        call_type: Literal[
            "completion",
            "acompletion",
            "text_completion",
            "atext_completion",
            "embeddings",
            "aembeddings",
            "anthropic_messages",
            "aanthropic_messages",
            "responses",
            "aresponses",
            "generate_content",
            "agenerate_content",
            "generate_content_stream",
            "agenerate_content_stream",
        ],
    ) -> Optional[dict]:
        try:
            cfg = resolve_config(user_api_key_dict, data)
            if not is_enabled(cfg):
                return data
            if not isinstance(data, dict):
                return data

            req_meta = data.get("metadata")

            # Explicit per-request bypass
            if isinstance(req_meta, dict) and req_meta.get("token_saver_bypass"):
                return data

            stats = apply_token_saver(data, cfg, call_type)
            if stats:
                call_id = str(data.get("litellm_call_id") or "")
                if call_id:
                    _pending[call_id] = stats
                if isinstance(req_meta, dict):
                    req_meta.setdefault("token_saver_stats", stats)
                _record_compression_savings(data, stats)
                print(summarize(stats), flush=True)
            return data
        except Exception as exc:  # noqa: BLE001 - fail-open, never break a call
            print(f"[TokenSaver] pre_call_hook error (fail-open): {exc}", flush=True)
            return data

    async def async_log_success_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        """Attach real token usage to the per-call savings record."""
        call_id = str((kwargs or {}).get("litellm_call_id") or "")
        stats = _pending.get(call_id)
        if not stats:
            return
        kw = dict(kwargs or {})
        kw["response_obj"] = response_obj
        _record_metrics(call_id, stats, kw)


proxy_handler_instance = TokenSaverLogger()
