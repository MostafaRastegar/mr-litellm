"""Tests for the compression pipeline (compress_messages / dedupe_tools)."""

from rtk_saver.compress import (
    compress_messages,
    compress_text,
    dedupe_tools,
    format_rtk_log,
)
from rtk_saver.constants import MIN_COMPRESS_SIZE

from .conftest import GIT_DIFF_SAMPLE


def _stats():
    return {"bytes_before": 0, "bytes_after": 0, "hits": []}


# ── compress_text ────────────────────────────────────────────────────


def test_compress_text_skips_blobs_below_min_size():
    small = "tiny"
    stats = _stats()
    assert compress_text(small, stats, "openai-tool") == small
    assert stats["hits"] == []


def test_compress_text_compresses_large_git_diff():
    stats = _stats()
    out = compress_text(GIT_DIFF_SAMPLE, stats, "openai-tool")
    assert len(out) < len(GIT_DIFF_SAMPLE)
    assert stats["hits"][0]["filter"] == "git-diff"
    assert stats["hits"][0]["shape"] == "openai-tool"


def test_compress_text_never_grows_the_input():
    stats = _stats()
    plain = "x" * (MIN_COMPRESS_SIZE + 100)
    assert compress_text(plain, stats, "openai-tool") == plain


# ── OpenAI tool shape ────────────────────────────────────────────────


def test_compress_openai_tool_string_content():
    body = {"messages": [{"role": "tool", "content": GIT_DIFF_SAMPLE}]}
    stats = compress_messages(body)
    assert stats["hits"]
    assert len(body["messages"][0]["content"]) < len(GIT_DIFF_SAMPLE)


def test_compress_openai_tool_array_content():
    body = {
        "messages": [
            {"role": "tool", "content": [{"type": "text", "text": GIT_DIFF_SAMPLE}]}
        ]
    }
    stats = compress_messages(body)
    assert stats["hits"][0]["shape"] == "openai-tool-array"
    assert len(body["messages"][0]["content"][0]["text"]) < len(GIT_DIFF_SAMPLE)


# ── Anthropic tool_result shapes ─────────────────────────────────────


def test_compress_claude_string_form():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "tool_result", "content": GIT_DIFF_SAMPLE}],
            }
        ]
    }
    stats = compress_messages(body)
    assert stats["hits"][0]["shape"] == "claude-string"


def test_compress_claude_array_form():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": [{"type": "text", "text": GIT_DIFF_SAMPLE}],
                    }
                ],
            }
        ]
    }
    stats = compress_messages(body)
    assert stats["hits"][0]["shape"] == "claude-array"


def test_compress_preserves_error_tool_results():
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "is_error": True,
                        "content": GIT_DIFF_SAMPLE,
                    }
                ],
            }
        ]
    }
    stats = compress_messages(body)
    assert not stats["hits"]
    assert body["messages"][0]["content"][0]["content"] == GIT_DIFF_SAMPLE


# ── OpenAI Responses shapes ──────────────────────────────────────────


def test_compress_responses_string_output():
    body = {"input": [{"type": "function_call_output", "output": GIT_DIFF_SAMPLE}]}
    stats = compress_messages(body)
    assert stats["hits"][0]["shape"] == "openai-responses-string"


def test_compress_responses_array_output():
    body = {
        "input": [
            {
                "type": "function_call_output",
                "output": [{"type": "input_text", "text": GIT_DIFF_SAMPLE}],
            }
        ]
    }
    stats = compress_messages(body)
    assert stats["hits"][0]["shape"] == "openai-responses-array"


# ── Kiro shape ───────────────────────────────────────────────────────


def test_compress_kiro_conversation_state():
    body = {
        "conversationState": {
            "history": [
                {
                    "userInputMessage": {
                        "userInputMessageContext": {
                            "toolResults": [{"content": [{"text": GIT_DIFF_SAMPLE}]}]
                        }
                    }
                }
            ]
        }
    }
    stats = compress_messages(body)
    assert stats["hits"][0]["shape"] == "kiro-tool-result"


def test_compress_kiro_skips_error_status():
    body = {
        "conversationState": {
            "history": [
                {
                    "userInputMessage": {
                        "userInputMessageContext": {
                            "toolResults": [
                                {
                                    "status": "error",
                                    "content": [{"text": GIT_DIFF_SAMPLE}],
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }
    stats = compress_messages(body)
    assert not stats["hits"]


# ── guards ───────────────────────────────────────────────────────────


def test_compress_messages_disabled_returns_none():
    body = {"messages": [{"role": "tool", "content": GIT_DIFF_SAMPLE}]}
    assert compress_messages(body, enabled=False) is None


def test_compress_messages_without_messages_returns_none():
    assert compress_messages({"model": "x"}) is None


def test_compress_messages_does_not_touch_non_tool_messages():
    body = {"messages": [{"role": "user", "content": GIT_DIFF_SAMPLE}]}
    stats = compress_messages(body)
    assert not stats["hits"]
    assert body["messages"][0]["content"] == GIT_DIFF_SAMPLE


def test_compress_messages_fail_open_on_bad_shape():
    body = {"messages": [{"role": "tool", "content": {"unexpected": True}}]}
    stats = compress_messages(body)
    assert stats is not None


# ── format_rtk_log ───────────────────────────────────────────────────


def test_format_rtk_log_reports_savings_and_filters():
    stats = _stats()
    compress_text(GIT_DIFF_SAMPLE, stats, "openai-tool")
    line = format_rtk_log(stats)
    assert "[RTK] saved" in line
    assert "git-diff" in line


def test_format_rtk_log_none_when_no_hits():
    assert format_rtk_log(_stats()) is None
    assert format_rtk_log(None) is None


# ── dedupe_tools ─────────────────────────────────────────────────────


def test_dedupe_tools_replaces_older_duplicates():
    items = [
        {"role": "tool", "content": GIT_DIFF_SAMPLE},
        {"role": "user", "content": "please continue"},
        {"role": "tool", "content": GIT_DIFF_SAMPLE},
    ]
    result = dedupe_tools(items)
    assert result["replaced"] == 1
    assert result["bytes"] == len(GIT_DIFF_SAMPLE) - len(
        "[duplicate tool output omitted — see message #2]"
    )
    assert "duplicate tool output omitted" in items[0]["content"]
    assert items[2]["content"] == GIT_DIFF_SAMPLE  # newest kept intact


def test_dedupe_tools_ignores_small_payloads():
    items = [
        {"role": "tool", "content": "ok"},
        {"role": "tool", "content": "ok"},
    ]
    assert dedupe_tools(items) == {"replaced": 0, "bytes": 0}


def test_dedupe_tools_handles_array_content():
    items = [
        {"role": "tool", "content": [{"type": "text", "text": GIT_DIFF_SAMPLE}]},
        {"role": "tool", "content": [{"type": "text", "text": GIT_DIFF_SAMPLE}]},
    ]
    result = dedupe_tools(items)
    assert result["replaced"] == 1
    assert result["bytes"] > 0
    assert isinstance(items[0]["content"], list)
