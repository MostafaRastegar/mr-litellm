"""Compact "Result of search in '...' (total N files):" output (Cursor Glob).

Groups by parent dir like find, shows basenames.
"""

import re

from ..constants import SEARCH_LIST_PER_DIR_MAX, SEARCH_LIST_TOTAL_DIR_MAX

SEARCH_LIST_HEADER_RE = re.compile(
    r"^Result of search in '[^']*' \(total (\d+) files?\):"
)


def search_list(input_text: str) -> str:
    lines = input_text.split("\n")
    if not lines:
        return input_text

    header = lines[0] if lines else ""
    rest = lines[1:]

    paths: list[str] = []
    for raw in rest:
        t = raw.strip()
        if not t.startswith("- "):
            continue
        paths.append(t[2:])
    if not paths:
        return input_text

    by_dir: dict[str, list[str]] = {}
    for p in paths:
        slash = p.rfind("/")
        if slash == -1:
            directory, name = ".", p
        else:
            directory = p[:slash] or "/"
            name = p[slash + 1 :]
        by_dir.setdefault(directory, []).append(name)

    dirs = sorted(by_dir.keys())
    out = f"{header}\n{len(paths)} files in {len(dirs)} dirs:\n\n"

    for directory in dirs[:SEARCH_LIST_TOTAL_DIR_MAX]:
        names = by_dir[directory]
        out += f"{directory}/ ({len(names)}):\n"
        for n in names[:SEARCH_LIST_PER_DIR_MAX]:
            out += f"  {n}\n"
        if len(names) > SEARCH_LIST_PER_DIR_MAX:
            out += f"  +{len(names) - SEARCH_LIST_PER_DIR_MAX}\n"
        out += "\n"

    if len(dirs) > SEARCH_LIST_TOTAL_DIR_MAX:
        out += f"+{len(dirs) - SEARCH_LIST_TOTAL_DIR_MAX} more dirs\n"

    return re.sub(r"\n+$", "", out)


search_list.filter_name = "search-list"
