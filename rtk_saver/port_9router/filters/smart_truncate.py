"""Port concept of filter::smart_truncate (rtk/src/core/filter.rs).

Keep HEAD + TAIL lines, replace middle with "... +N lines truncated".
"""

from ..constants import (
    SMART_TRUNCATE_HEAD,
    SMART_TRUNCATE_MIN_LINES,
    SMART_TRUNCATE_TAIL,
)


def smart_truncate(input_text: str) -> str:
    lines = input_text.split("\n")
    if len(lines) < SMART_TRUNCATE_MIN_LINES:
        return input_text

    head = lines[:SMART_TRUNCATE_HEAD]
    tail = lines[-SMART_TRUNCATE_TAIL:]
    cut = len(lines) - len(head) - len(tail)
    return "\n".join([*head, f"... +{cut} lines truncated", *tail])


smart_truncate.filter_name = "smart-truncate"
