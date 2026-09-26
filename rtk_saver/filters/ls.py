"""Port of compact_ls (rtk/src/cmds/system/ls.rs:154-232).

Input: `ls -la` style output. Output: compact "name/  (dirs)\\nname  size".
"""

import re

from ..constants import LS_EXT_SUMMARY_TOP, LS_NOISE_DIRS

# Rust LS_DATE_RE: month + day + (year|HH:MM)
_LS_DATE_RE = re.compile(
    r"\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+\d{1,2}\s+(\d{4}|\d{2}:\d{2})\s+"
)


def _human_size(num_bytes: int) -> str:
    if num_bytes >= 1_048_576:
        return f"{num_bytes / 1_048_576:.1f}M"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f}K"
    return f"{num_bytes}B"


def _parse_ls_line(line: str):
    m = _LS_DATE_RE.search(line)
    if not m:
        return None
    name = line[m.end() :]
    before_date = line[: m.start()]
    before_parts = [p for p in re.split(r"\s+", before_date) if p]
    if len(before_parts) < 4:
        return None

    perms = before_parts[0]
    file_type = perms[0]

    # size = rightmost parseable number before the date
    size = 0
    for token in reversed(before_parts):
        try:
            n = int(token)
        except ValueError:
            continue
        if str(n) == token:
            size = n
            break
    return file_type, size, name


def ls(input_text: str) -> str:
    dirs: list[str] = []
    files: list[tuple[str, str]] = []
    by_ext: dict[str, int] = {}

    for line in input_text.split("\n"):
        if line.startswith("total ") or line == "":
            continue
        parsed = _parse_ls_line(line)
        if not parsed:
            continue
        file_type, size, name = parsed
        if name in (".", ".."):
            continue
        if name in LS_NOISE_DIRS:
            continue

        if file_type == "d":
            dirs.append(name)
        elif file_type in ("-", "l"):
            dot = name.rfind(".")
            ext = name[dot:] if dot > 0 else "no ext"
            by_ext[ext] = by_ext.get(ext, 0) + 1
            files.append((name, _human_size(size)))

    if not dirs and not files:
        return input_text

    out = ""
    for d in dirs:
        out += f"{d}/\n"
    for name, size in files:
        out += f"{name}  {size}\n"

    summary = f"\nSummary: {len(files)} files, {len(dirs)} dirs"
    if by_ext:
        ext_sorted = sorted(by_ext.items(), key=lambda kv: (-kv[1], kv[0]))
        parts = [f"{c} {e}" for e, c in ext_sorted[:LS_EXT_SUMMARY_TOP]]
        summary += f" ({', '.join(parts)}"
        if len(ext_sorted) > LS_EXT_SUMMARY_TOP:
            summary += f", +{len(ext_sorted) - LS_EXT_SUMMARY_TOP} more"
        summary += ")"

    return out + summary


ls.filter_name = "ls"
