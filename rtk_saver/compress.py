"""Backward compatibility facade. Real implementation lives in `rtk_saver.port_9router.compress`."""

from .port_9router.compress import *

# Explicit re-exports for tools that use `from rtk_saver.compress import X`
from .port_9router.compress import compress_messages, compress_text, dedupe_tools, format_rtk_log
