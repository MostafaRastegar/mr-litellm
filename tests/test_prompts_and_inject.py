"""Tests for Caveman / Ponytail prompts and system-prompt injection."""

from rtk_saver.inject import detect_wire_format, inject_system_prompt
from rtk_saver.prompts import (
    ALL_CAVEMAN_LEVELS,
    ALL_PONYTAIL_LEVELS,
    CAVEMAN_PROMPTS,
    PONYTAIL_PROMPTS,
    SHARED_BOUNDARIES,
    SHARED_LADDER,
    SHARED_PERSONA,
)


# ── prompt catalogue ─────────────────────────────────────────────────


def test_all_caveman_levels_present():
    assert set(ALL_CAVEMAN_LEVELS) == {
        "lite",
        "full",
        "ultra",
        "wenyan-lite",
        "wenyan",
        "wenyan-ultra",
    }


def test_all_ponytail_levels_present():
    assert set(ALL_PONYTAIL_LEVELS) == {"lite", "full", "ultra"}


def test_caveman_prompts_carry_shared_boundaries():
    for level, prompt in CAVEMAN_PROMPTS.items():
        assert SHARED_BOUNDARIES in prompt, level


def test_caveman_prompts_protect_technical_accuracy():
    """Boundaries must tell the model to keep code/paths/commands exact."""
    assert "keep exact" in SHARED_BOUNDARIES
    assert "Code blocks, file paths, commands, errors, URLs" in SHARED_BOUNDARIES


def test_caveman_prompts_carry_anti_self_reference_guard():
    prompt = CAVEMAN_PROMPTS["lite"]
    assert "No self-reference" in prompt
    assert "No decorative emoji" in prompt


def test_ponytail_prompts_carry_persona_and_ladder():
    for level, prompt in PONYTAIL_PROMPTS.items():
        assert SHARED_PERSONA in prompt, level
        assert SHARED_LADDER in prompt, level


def test_ponytail_levels_are_distinct():
    assert (
        PONYTAIL_PROMPTS["lite"]
        != PONYTAIL_PROMPTS["full"]
        != PONYTAIL_PROMPTS["ultra"]
    )


def test_ponytail_ultra_is_the_most_aggressive():
    assert "YAGNI extremist" in PONYTAIL_PROMPTS["ultra"]


# ── detection ────────────────────────────────────────────────────────


def test_detect_wire_format_from_call_type():
    assert detect_wire_format({}, "anthropic_messages") == "anthropic"
    assert detect_wire_format({}, "responses") == "responses"


def test_detect_wire_format_from_shape():
    assert detect_wire_format({"messages": []}) == "openai"
    assert detect_wire_format({"system": "hi"}) == "anthropic"
    assert detect_wire_format({"instructions": "hi"}) == "responses"
    assert detect_wire_format({"contents": []}) == "gemini"
    assert detect_wire_format({"systemInstruction": {}}) == "gemini"


# ── OpenAI chat injection ────────────────────────────────────────────


def test_inject_openai_appends_to_existing_system_string():
    body = {
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
    }
    assert inject_system_prompt(body, "NEW RULE") is True
    assert body["messages"][0]["content"] == "You are helpful.\n\nNEW RULE"


def test_inject_openai_creates_system_message_when_missing():
    body = {"messages": [{"role": "user", "content": "hi"}]}
    inject_system_prompt(body, "NEW RULE")
    assert body["messages"][0] == {"role": "system", "content": "NEW RULE"}
    assert body["messages"][1]["role"] == "user"


def test_inject_openai_handles_block_content():
    body = {
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": "base"}]},
            {"role": "user", "content": "hi"},
        ]
    }
    inject_system_prompt(body, "NEW RULE")
    assert body["messages"][0]["content"][-1] == {"type": "text", "text": "NEW RULE"}


# ── Anthropic injection ──────────────────────────────────────────────


def test_inject_anthropic_uses_dedicated_system_field():
    body = {"system": "base system", "messages": [{"role": "user", "content": "hi"}]}
    inject_system_prompt(body, "NEW RULE", "anthropic")
    assert body["system"] == "base system\n\nNEW RULE"


def test_inject_anthropic_does_not_add_system_role_to_messages():
    """Anthropic rejects a 'system' role inside messages[]."""
    body = {"messages": [{"role": "user", "content": "hi"}]}
    inject_system_prompt(body, "NEW RULE", "anthropic")
    assert "system" in body
    assert all(m.get("role") != "system" for m in body["messages"])


def test_inject_anthropic_handles_block_system():
    body = {"system": [{"type": "text", "text": "base"}], "messages": []}
    inject_system_prompt(body, "NEW RULE", "anthropic")
    assert body["system"][-1] == {"type": "text", "text": "NEW RULE"}


# ── Responses injection ──────────────────────────────────────────────


def test_inject_responses_prefers_instructions():
    body = {"instructions": "base", "input": [{"role": "user", "content": "hi"}]}
    inject_system_prompt(body, "NEW RULE", "responses")
    assert body["instructions"] == "base\n\nNEW RULE"


def test_inject_responses_adds_system_item_when_no_instructions():
    body = {"input": [{"role": "user", "content": "hi"}]}
    inject_system_prompt(body, "NEW RULE", "responses")
    assert body["input"][0]["role"] == "system"


def test_inject_responses_leaves_string_input_untouched():
    body = {"input": "raw string input"}
    inject_system_prompt(body, "NEW RULE", "responses")
    assert body["input"] == "raw string input"
    assert body["instructions"] == "NEW RULE"


# ── Gemini injection ─────────────────────────────────────────────────


def test_inject_gemini_creates_system_instruction():
    body = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
    inject_system_prompt(body, "NEW RULE", "gemini")
    assert body["systemInstruction"]["parts"][-1] == {"text": "NEW RULE"}


def test_inject_gemini_appends_to_existing_parts():
    body = {"systemInstruction": {"parts": [{"text": "base"}]}, "contents": []}
    inject_system_prompt(body, "NEW RULE", "gemini")
    assert len(body["systemInstruction"]["parts"]) == 2


# ── guards ───────────────────────────────────────────────────────────


def test_inject_noop_on_empty_prompt():
    body = {"messages": []}
    assert inject_system_prompt(body, "") is False
    assert inject_system_prompt(body, None) is False


def test_inject_noop_on_non_dict_body():
    assert inject_system_prompt("not a dict", "RULE") is False
    assert inject_system_prompt(None, "RULE") is False


def test_inject_unknown_shape_returns_false():
    assert inject_system_prompt({"weird": 1}, "RULE") is False


def test_inject_auto_detects_openai():
    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert inject_system_prompt(body, "RULE", "auto") is True
    assert body["messages"][0]["role"] == "system"
