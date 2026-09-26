"""Core algorithms ported verbatim from 9Router (JS / Rust) to Python.

This package contains pure deterministic logic for tool output compression,
prompts, and constants. It is completely decoupled from LiteLLM gateway
customizations.
"""

from .compress import compress_text, compress_messages
from .constants import *
from .prompts import *
