"""Port of grep_wrapper (rtk/src/cmds/system/pipe_cmd.rs:50-86).

Input format: "file:lineno:content" — splitn(3, ':') in Rust.
"""

import re

from ..constants import GREP_PER_FILE_MAX

_LINENO_RE = re.compile(r"^\d+$")


def grep(input_text: str) -> str:
    by_file: dict[str, list[tuple[str, str]]] = {}
    total = 0

    for line in input_text.split("\n"):
        first = line.find(":")
        if first == -1:
            continue
        second = line.find(":", first + 1)
        if second == -1:
            continue
        file_name = line[:first]
        line_num_str = line[first + 1 : second]
        content = line[second + 1 :]
        if not _LINENO_RE.match(line_num_str):
            continue
        total += 1
        by_file.setdefault(file_name, []).append((line_num_str, content))

    if total == 0:
        return input_text

    files = sorted(by_file.keys())
    out = f"{total} matches in {len(files)}F:\n\n"

    for file_name in files:
        matches = by_file[file_name]
        out += f"[file] {file_name} ({len(matches)}):\n"
        for line_num, content in matches[:GREP_PER_FILE_MAX]:
            out += f"  {line_num.rjust(4)}: {content.strip()}\n"
        if len(matches) > GREP_PER_FILE_MAX:
            out += f"  +{len(matches) - GREP_PER_FILE_MAX}\n"
        out += "\n"

    return out


grep.filter_name = "grep"
