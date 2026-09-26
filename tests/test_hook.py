"""Integration tests for the LiteLLM pre-call hook."""

import asyncio
import json

from rtk_saver.callback import (
    BYTES_PER_TOKEN,
    DEFAULT_CONFIG,
    TokenSaverLogger,
    _level,
    _record_compression_savings,
    _saved_bytes,
    apply_token_saver,
    build_system_additions,
    is_enabled,
    proxy_handler_instance,
    resolve_config,
    summarize,
)

from .conftest import FakeKey, GIT_DIFF_SAMPLE


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _hook():
    return TokenSaverLogger()


def _data_with_tool_output():
    return {
        "model": "claude-sonnet",
        "messages": [
            {"role": "system", "content": "You are a coding assistant."},
            {"role": "user", "content": "Check the diff"},
            {"role": "tool", "content": GIT_DIFF_SAMPLE},
        ],
    }


# ── config resolution ────────────────────────────────────────────────


def test_disabled_by_default():
    assert is_enabled(DEFAULT_CONFIG) is False
    assert is_enabled(resolve_config(FakeKey({}))) is False


def test_enabled_via_key_metadata_nested_dict():
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "ultra"}})
    cfg = resolve_config(key)
    assert is_enabled(cfg) is True
    assert cfg["caveman"] == "ultra"


def test_enabled_via_legacy_flat_metadata_flag():
    assert is_enabled(resolve_config(FakeKey({"token_saver_enabled": True}))) is True


def test_enabled_via_flat_ts_metadata():
    """Dashboard-friendly flat ts_* keys — each field visible/editable."""
    meta = {
        "ts_enabled": True,
        "ts_caveman": "lite",
        "ts_rtk": True,
        "ts_dedupe_tools": True,
        "ts_min_bytes": 500,
    }
    cfg = resolve_config(FakeKey(meta))
    assert is_enabled(cfg) is True
    assert cfg["caveman"] == "lite"
    assert cfg["rtk"] is True
    assert cfg["dedupe_tools"] is True
    assert cfg["min_bytes"] == 500


def test_flat_plain_keys_fallback():
    """Plain keys without ts_ prefix — for manual dashboard edits."""
    meta = {"enabled": True, "caveman": "full", "ponytail": "ultra"}
    cfg = resolve_config(FakeKey(meta))
    assert is_enabled(cfg) is True
    assert cfg["caveman"] == "full"
    assert cfg["ponytail"] == "ultra"


def test_nested_takes_precedence_over_flat():
    """If both nested and flat exist, nested wins."""
    meta = {
        "token_saver": {"enabled": True, "caveman": "off"},
        "ts_enabled": True,
        "ts_caveman": "ultra",
    }
    cfg = resolve_config(FakeKey(meta))
    assert cfg["caveman"] == "off"


def test_enabled_accepts_string_truthy_values():
    for value in ("true", "TRUE", "1", "yes", "on", "enabled"):
        cfg = resolve_config(FakeKey({"token_saver": {"enabled": value}}))
        assert is_enabled(cfg) is True, value


def test_request_metadata_overrides_key_metadata():
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "lite"}})
    data = {"metadata": {"token_saver": {"caveman": "full"}}}
    cfg = resolve_config(key, data)
    assert cfg["caveman"] == "full"
    assert is_enabled(cfg) is True


def test_env_default_config_is_merged(monkeypatch):
    monkeypatch.setenv(
        "TOKEN_SAVER_DEFAULT_CONFIG", json.dumps({"enabled": True, "caveman": "full"})
    )
    cfg = resolve_config(FakeKey({}))
    assert is_enabled(cfg) is True
    assert cfg["caveman"] == "full"


def test_bad_env_default_config_is_ignored(monkeypatch):
    monkeypatch.setenv("TOKEN_SAVER_DEFAULT_CONFIG", "{not valid json")
    cfg = resolve_config(FakeKey({}))
    assert is_enabled(cfg) is False


# ── _level: boolean config values (dashboard checkbox artefacts) ──────────


def test_level_boolean_true_falls_back_to_off():
    """ts_ponytail: true (JSON boolean) must not become string 'true'."""
    assert _level({"ponytail": True}, "ponytail") == "off"


def test_level_boolean_false_falls_back_to_off():
    assert _level({"caveman": False}, "caveman") == "off"


def test_level_string_values_pass_through():
    assert _level({"ponytail": "lite"}, "ponytail") == "lite"
    assert _level({"caveman": "ultra"}, "caveman") == "ultra"


def test_level_none_and_empty_fall_back_to_off():
    assert _level({}, "ponytail") == "off"
    assert _level({"ponytail": None}, "caveman") == "off"
    assert _level({"caveman": ""}, "caveman") == "off"


def test_level_boolean_ponytail_does_not_produce_true_in_stats():
    """End-to-end: a key with ts_ponytail: true must record 'off', not 'true'."""
    key = FakeKey({"ts_enabled": True, "ts_caveman": "lite", "ts_ponytail": True})
    data = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    cfg = resolve_config(key, data)
    stats = apply_token_saver(data, cfg)
    assert stats["ponytail"] == "off"
    assert stats["caveman"] == "lite"


# ── prompt composition ───────────────────────────────────────────────


def test_build_system_additions_empty_when_all_off():
    assert build_system_additions({"caveman": "off", "ponytail": "off"}) == ""


def test_build_system_additions_caveman_only():
    out = build_system_additions({"caveman": "lite", "ponytail": "off"})
    assert "Respond tersely" in out


def test_build_system_additions_combines_both():
    out = build_system_additions({"caveman": "full", "ponytail": "lite"})
    assert "caveman" in out.lower() or "terse caveman" in out
    assert "lazy senior developer" in out


def test_build_system_additions_ignores_unknown_levels():
    assert build_system_additions({"caveman": "nope", "ponytail": "nope"}) == ""


# ── apply_token_saver ────────────────────────────────────────────────


def test_apply_compresses_tool_output_and_injects_prompt():
    data = _data_with_tool_output()
    cfg = {"enabled": True, "caveman": "lite", "ponytail": "off", "rtk": True,
           "dedupe_tools": True}
    stats = apply_token_saver(data, cfg)
    assert stats["rtk"]["hits"]
    assert stats["injected"] is True
    assert len(data["messages"][2]["content"]) < len(GIT_DIFF_SAMPLE)
    assert "Respond tersely" in data["messages"][0]["content"]


def test_apply_preserves_the_client_system_prompt():
    data = _data_with_tool_output()
    cfg = {"caveman": "lite", "rtk": False, "dedupe_tools": False}
    apply_token_saver(data, cfg)
    assert data["messages"][0]["content"].startswith("You are a coding assistant.")


def test_apply_never_touches_anthropic_beta_headers():
    data = _data_with_tool_output()
    data["anthropic_beta"] = ["some-new-client-beta"]
    cfg = {"caveman": "lite", "rtk": True, "dedupe_tools": True}
    apply_token_saver(data, cfg)
    assert data["anthropic_beta"] == ["some-new-client-beta"]


def test_apply_preserves_unknown_body_fields():
    data = _data_with_tool_output()
    data["future_provider_field"] = {"nested": [1, 2, 3]}
    cfg = {"caveman": "lite", "rtk": True, "dedupe_tools": True}
    apply_token_saver(data, cfg)
    assert data["future_provider_field"] == {"nested": [1, 2, 3]}


def test_apply_strips_internal_rtk_markers():
    data = _data_with_tool_output()
    data["_rtk_internal"] = "secret"
    cfg = {"caveman": "lite", "rtk": True, "dedupe_tools": True}
    apply_token_saver(data, cfg)
    assert "_rtk_internal" not in data


def test_apply_rtk_can_be_disabled():
    data = _data_with_tool_output()
    cfg = {"caveman": "off", "rtk": False, "dedupe_tools": False}
    stats = apply_token_saver(data, cfg)
    assert stats["rtk"] is None
    assert data["messages"][2]["content"] == GIT_DIFF_SAMPLE


# ── the async hook itself ────────────────────────────────────────────


def test_hook_passthrough_when_disabled():
    data = _data_with_tool_output()
    original = json.dumps(data, sort_keys=True)
    out = run(_hook().async_pre_call_hook(FakeKey({}), None, data, "completion"))
    assert json.dumps(out, sort_keys=True) == original


def test_hook_transforms_when_enabled():
    data = _data_with_tool_output()
    key = FakeKey(
        {"token_saver": {"enabled": True, "caveman": "lite", "rtk": True,
                         "dedupe_tools": True}}
    )
    out = run(_hook().async_pre_call_hook(key, None, data, "completion"))
    assert "Respond tersely" in out["messages"][0]["content"]
    assert len(out["messages"][2]["content"]) < len(GIT_DIFF_SAMPLE)


def test_hook_records_stats_in_metadata():
    data = _data_with_tool_output()
    data["metadata"] = {"tags": ["team:backend"]}
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "off", "rtk": True}})
    out = run(_hook().async_pre_call_hook(key, None, data, "completion"))
    assert "token_saver_stats" in out["metadata"]
    assert out["metadata"]["tags"] == ["team:backend"]  # existing metadata kept


def test_hook_honours_per_request_bypass():
    data = _data_with_tool_output()
    data["metadata"] = {"token_saver_bypass": True}
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "lite"}})
    out = run(_hook().async_pre_call_hook(key, None, data, "completion"))
    assert out["messages"][2]["content"] == GIT_DIFF_SAMPLE
    assert "Respond tersely" not in out["messages"][0]["content"]


def test_hook_applies_to_anthropic_messages_call_type():
    data = {
        "system": "base",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "tool_result", "content": GIT_DIFF_SAMPLE}],
            }
        ],
    }
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "lite", "rtk": True}})
    out = run(
        _hook().async_pre_call_hook(key, None, data, "anthropic_messages")
    )
    assert out["system"] != "base"  # prompt appended to dedicated system field
    assert all(m.get("role") != "system" for m in out["messages"])
    assert len(out["messages"][0]["content"][0]["content"]) < len(GIT_DIFF_SAMPLE)


def test_hook_fails_open_on_malformed_input():
    """A broken body must never raise out of the hook."""
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "lite"}})
    out = run(_hook().async_pre_call_hook(key, None, None, "completion"))
    assert out is None


def test_hook_fails_open_when_content_is_wrong_type():
    data = {"messages": "not-a-list"}
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "lite"}})
    out = run(_hook().async_pre_call_hook(key, None, data, "completion"))
    assert out == data


def test_proxy_handler_instance_is_exported():
    assert isinstance(proxy_handler_instance, TokenSaverLogger)


# ── summarize ────────────────────────────────────────────────────────


def test_summarize_reports_rtk_and_prompt():
    data = _data_with_tool_output()
    cfg = {"caveman": "lite", "ponytail": "off", "rtk": True, "dedupe_tools": True}
    line = summarize(apply_token_saver(data, cfg))
    assert line.startswith("[TokenSaver]")
    assert "[RTK] saved" in line
    assert "prompt=lite" in line


def test_summarize_handles_none():
    assert summarize(None) == "[TokenSaver] no-op"


# ── dashboard savings record (compression_savings) ────────────────────


def test_saved_bytes_adds_rtk_and_dedupe():
    stats = {
        "rtk": {"bytes_before": 8000, "bytes_after": 1000},
        "dedupe_bytes": 2400,
    }
    assert _saved_bytes(stats) == 9400


def test_saved_bytes_never_goes_negative():
    stats = {"rtk": {"bytes_before": 100, "bytes_after": 900}, "dedupe_bytes": -50}
    assert _saved_bytes(stats) == 0


def test_savings_record_written_to_metadata_bucket():
    """A chat-style request must carry the record in `metadata`."""
    data = {"metadata": {"user_api_key_alias": "programmer-prod"}}
    stats = {"rtk": {"bytes_before": 4100, "bytes_after": 310}, "dedupe_bytes": 0}
    _record_compression_savings(data, stats)

    rec = data["metadata"]["compression_savings"]
    assert rec["tokens_saved"] == (4100 - 310) // BYTES_PER_TOKEN
    assert rec["source"] == "compression_interception"
    assert rec["tokens_after"] == 0
    # The key the proxy already owned must survive untouched.
    assert data["metadata"]["user_api_key_alias"] == "programmer-prod"


def test_savings_record_reuses_litellm_metadata_when_present():
    """/v1/messages style requests keep their record in `litellm_metadata`."""
    data = {"litellm_metadata": {}}
    _record_compression_savings(data, {"rtk": {"bytes_before": 4000, "bytes_after": 0}})
    assert "compression_savings" in data["litellm_metadata"]
    assert "metadata" not in data  # never invent the Anthropic field


def test_savings_record_prefers_existing_metadata_bucket():
    data = {"metadata": {}, "litellm_metadata": {}}
    _record_compression_savings(data, {"rtk": {"bytes_before": 4000, "bytes_after": 0}})
    assert "compression_savings" in data["metadata"]
    assert data["litellm_metadata"] == {}


def test_savings_record_skipped_when_nothing_saved():
    data = {"metadata": {}}
    _record_compression_savings(
        data, {"rtk": {"bytes_before": 500, "bytes_after": 500}, "dedupe_bytes": 0}
    )
    assert data["metadata"] == {}


def test_savings_record_skipped_when_net_is_negative():
    """Injection outweighing compression must not be reported as savings."""
    data = {"metadata": {}}
    _record_compression_savings(
        data, {"rtk": {"bytes_before": 100, "bytes_after": 900}, "dedupe_bytes": 0}
    )
    assert data["metadata"] == {}


def test_savings_record_skipped_below_one_token():
    data = {"metadata": {}}
    _record_compression_savings(
        data, {"rtk": {"bytes_before": 503, "bytes_after": 500}, "dedupe_bytes": 0}
    )
    assert data["metadata"] == {}


def test_savings_record_fails_open_on_malformed_stats():
    data = {"metadata": {}}
    _record_compression_savings(data, {"rtk": "not-a-dict", "dedupe_bytes": None})
    assert data["metadata"] == {}


def test_hook_publishes_savings_for_dashboard():
    """End to end through the hook: enabled key + compressible body."""
    data = _data_with_tool_output()
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "off", "rtk": True}})
    out = run(_hook().async_pre_call_hook(key, None, data, "completion"))

    # No metadata bucket existed, so the record lands in litellm_metadata —
    # the same bucket LiteLLM reads back on routes that carry one.
    rec = out["litellm_metadata"]["compression_savings"]
    assert rec["tokens_saved"] > 0
    assert rec["source"] == "compression_interception"
    assert rec["tokens_before"] == rec["tokens_saved"]


def test_hook_publishes_savings_into_existing_metadata_bucket():
    """A request that already carries `metadata` keeps the record there."""
    data = _data_with_tool_output()
    data["metadata"] = {"user_api_key_alias": "programmer-prod"}
    key = FakeKey({"token_saver": {"enabled": True, "caveman": "off", "rtk": True}})
    out = run(_hook().async_pre_call_hook(key, None, data, "completion"))

    rec = out["metadata"]["compression_savings"]
    assert rec["tokens_saved"] > 0
    assert out["metadata"]["user_api_key_alias"] == "programmer-prod"
    assert "litellm_metadata" not in out


def test_hook_publishes_no_savings_when_disabled():
    data = _data_with_tool_output()
    out = run(_hook().async_pre_call_hook(FakeKey({"enabled": False}), None, data, "completion"))
    assert "compression_savings" not in (out.get("metadata") or {})
