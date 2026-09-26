"""Handles Cursor/Codex read_file output: "  1|content\\n  2|content".

Strategy mirrors Rust filter::smart_truncate (filter.rs): keep head+tail.
"""

import re

from ..constants import (
    SMART_TRUNCATE_HEAD,
    SMART_TRUNCATE_MIN_LINES,
    SMART_TRUNCATE_TAIL,
)

READ_NUMBERED_LINE_RE = re.compile(r"^\s*\d+\|")


def read_numbered(input_text: str) -> str:
    lines = input_text.split("\n")
    if len(lines) < SMART_TRUNCATE_MIN_LINES:
        return input_text

    head = lines[:SMART_TRUNCATE_HEAD]
    tail = lines[-SMART_TRUNCATE_TAIL:]
    cut = len(lines) - len(head) - len(tail)

    return "\n".join(
        [*head, f"... +{cut} lines truncated (file continues)", *tail]
    )


read_numbered.filter_name = "read-numbered"
