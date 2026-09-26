"""System-prompt injector: appends an instruction into the system message.

Port of 9Router open-sse/rtk/systemInject.js, adapted for LiteLLM's request
shapes (OpenAI chat / Anthropic messages / OpenAI Responses / Gemini).

Design note: unlike 9Router we do NOT guess the wire format from an internal
format label — LiteLLM keeps the client's native body. We dispatch purely on
the shape we actually receive, and we never drop client fields.
"""

from typing import Any, Optional

SEP = "\n\n"


def _append_text(existing: str, prompt: str) -> str:
    if not existing:
        return prompt
    return f"{existing}{SEP}{prompt}"


def _inject_openai_chat(body: dict, prompt: str) -> None:
    """OpenAI /v1/chat/completions shape: body["messages"][{role, content}]."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"] = _append_text(content, prompt)
                return
            if isinstance(content, list):
                content.append({"type": "text", "text": prompt})
                return
    messages.insert(0, {"role": "system", "content": prompt})


def _inject_anthropic(body: dict, prompt: str) -> None:
    """Anthropic /v1/messages shape: top-level body["system"].

    Anthropic rejects a "system" role inside messages[], so the dedicated
    system field is the only valid target.
    """
    system = body.get("system")
    if isinstance(system, str):
        body["system"] = _append_text(system, prompt)
        return
    if isinstance(system, list):
        system.append({"type": "text", "text": prompt})
        return
    body["system"] = prompt


def _inject_responses(body: dict, prompt: str) -> None:
    """OpenAI /v1/responses shape: body["instructions"] or body["input"]."""
    instructions = body.get("instructions")
    if isinstance(instructions, str):
        body["instructions"] = _append_text(instructions, prompt)
        return

    inp = body.get("input")
    if isinstance(inp, list):
        for item in inp:
            if not isinstance(item, dict):
                continue
            if item.get("role") in ("system", "developer"):
                content = item.get("content")
                if isinstance(content, str):
                    item["content"] = _append_text(content, prompt)
                    return
                if isinstance(content, list):
                    content.append({"type": "input_text", "text": prompt})
                    return
        inp.insert(0, {"role": "system", "content": prompt})
        return

    if isinstance(inp, str):
        # String input must stay untouched; fall back to instructions.
        body["instructions"] = prompt
        return

    body["instructions"] = prompt


def _inject_gemini(body: dict, prompt: str) -> None:
    """Google generateContent shape: body["systemInstruction"] / body["contents"]."""
    sys_inst = body.get("systemInstruction")
    if isinstance(sys_inst, dict):
        parts = sys_inst.setdefault("parts", [])
        if isinstance(parts, list):
            parts.append({"text": prompt})
            return
    if isinstance(sys_inst, str):
        body["systemInstruction"] = {"parts": [{"text": _append_text(sys_inst, prompt)}]}
        return
    body["systemInstruction"] = {"parts": [{"text": prompt}]}


def _inject_gemini_nested(body: dict, prompt: str) -> None:
    """Antigravity-style wrapper: body["request"] holds the Gemini payload."""
    inner = body.get("request")
    if isinstance(inner, dict):
        _inject_gemini(inner, prompt)
    else:
        _inject_gemini(body, prompt)


def inject_system_prompt(
    body: Any, prompt: Optional[str], wire_format: str = "auto"
) -> bool:
    """Append `prompt` to the system instruction of `body`, in place.

    Returns True when the body was modified. Fails open: any error leaves the
    body untouched, so a bad injection never breaks an LLM call.
    """
    if not prompt or not isinstance(body, dict):
        return False

    try:
        if wire_format == "anthropic":
            _inject_anthropic(body, prompt)
            return True
        if wire_format == "openai":
            _inject_openai_chat(body, prompt)
            return True
        if wire_format == "responses":
            _inject_responses(body, prompt)
            return True
        if wire_format == "gemini":
            _inject_gemini(body, prompt)
            return True
        if wire_format == "gemini_nested":
            _inject_gemini_nested(body, prompt)
            return True

        # auto: dispatch on actual shape
        if isinstance(body.get("system"), (str, list)):
            _inject_anthropic(body, prompt)
            return True
        if isinstance(body.get("instructions"), str):
            _inject_responses(body, prompt)
            return True
        if "systemInstruction" in body:
            _inject_gemini(body, prompt)
            return True
        if isinstance(body.get("request"), dict) and "contents" in body["request"]:
            _inject_gemini_nested(body, prompt)
            return True
        if isinstance(body.get("contents"), list):
            _inject_gemini(body, prompt)
            return True
        if isinstance(body.get("input"), list) and not isinstance(
            body.get("messages"), list
        ):
            _inject_responses(body, prompt)
            return True
        if isinstance(body.get("messages"), list):
            _inject_openai_chat(body, prompt)
            return True
    except Exception as exc:  # noqa: BLE001 - deliberate fail-open
        print(f"[RTK] inject_system_prompt error (fail-open): {exc}", flush=True)
        return False

    return False


def detect_wire_format(data: dict, call_type: str = "") -> str:
    """Best-effort wire-format label from the LiteLLM call type + body shape."""
    if call_type in ("anthropic_messages", "aanthropic_messages"):
        return "anthropic"
    if call_type in ("responses", "aresponses"):
        return "responses"

    if isinstance(data.get("system"), (str, list)):
        return "anthropic"
    if isinstance(data.get("instructions"), str):
        return "responses"
    if "systemInstruction" in data:
        return "gemini"
    if isinstance(data.get("request"), dict) and "contents" in data["request"]:
        return "gemini_nested"
    if isinstance(data.get("contents"), list):
        return "gemini"
    if isinstance(data.get("input"), list) and not isinstance(
        data.get("messages"), list
    ):
        return "responses"
    if isinstance(data.get("messages"), list):
        return "openai"
    return "auto"


def strip_injected_marker(obj: Any) -> None:
    """Remove RTK bookkeeping markers from a body before it goes upstream.

    Port of RTK's stripContinuityFields concern: internal fields must never
    leak to providers.
    """
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            if isinstance(key, str) and key.startswith("_rtk"):
                del obj[key]
            else:
                strip_injected_marker(obj[key])
    elif isinstance(obj, list):
        for item in obj:
            strip_injected_marker(item)
