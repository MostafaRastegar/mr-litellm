"""Port of filter_tree_output (rtk/src/cmds/system/tree.rs:65-94).

Removes summary line (e.g. "5 directories, 23 files") and trailing blanks.
"""

from ..constants import TREE_MAX_LINES


def tree(input_text: str) -> str:
    lines = input_text.split("\n")
    if not lines:
        return input_text

    filtered: list[str] = []
    for line in lines:
        # Drop "X directories, Y files" summary
        if "director" in line and "file" in line:
            continue
        # Drop leading blanks
        if line.strip() == "" and not filtered:
            continue
        filtered.append(line)

    # Drop trailing blanks
    while filtered and filtered[-1].strip() == "":
        filtered.pop()

    # Cap overly long trees (JS-only safeguard; Rust has no cap)
    if len(filtered) > TREE_MAX_LINES:
        cut = len(filtered) - TREE_MAX_LINES
        return "\n".join(filtered[:TREE_MAX_LINES]) + f"\n... +{cut} more lines"

    return "\n".join(filtered)


tree.filter_name = "tree"
