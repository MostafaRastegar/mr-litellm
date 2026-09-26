"""Token Saver for LiteLLM — RTK + Caveman + Ponytail inside the gateway.

See rtk_saver.callback for the LiteLLM hook entry point:

    litellm_settings:
      callbacks: rtk_saver.callback.proxy_handler_instance
"""

from .callback import (
    TokenSaverLogger,
    apply_token_saver,
    build_system_additions,
    is_enabled,
    proxy_handler_instance,
    resolve_config,
    summarize,
)
from .inject import detect_wire_format, inject_system_prompt

# Backward-compatible facade re-exports (legacy import paths)
from .port_9router.compress import compress_messages, dedupe_tools, format_rtk_log, compress_text
from .port_9router.constants import *
from .port_9router.prompts import CAVEMAN_PROMPTS, PONYTAIL_PROMPTS
from .port_9router.filters import *

__all__ = [
    "TokenSaverLogger",
    "apply_token_saver",
    "build_system_additions",
    "is_enabled",
    "proxy_handler_instance",
    "resolve_config",
    "summarize",
    "compress_messages",
    "dedupe_tools",
    "format_rtk_log",
    "compress_text",
    "detect_wire_format",
    "inject_system_prompt",
    "CAVEMAN_PROMPTS",
    "PONYTAIL_PROMPTS",
]
