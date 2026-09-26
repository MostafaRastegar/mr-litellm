"""Port of git::format_status_output (rtk/src/cmds/git/git.rs:619-730)."""

from ..constants import STATUS_MAX_FILES, STATUS_MAX_UNTRACKED

import re

_LONG_BRANCH_RE = re.compile(r"^On branch (\S+)")
_PORCELAIN_RE = re.compile(r"^[ MADRCU?!][ MADRCU?!] ")
_LONG_FORM_RE = re.compile(
    r"^\s*(modified|new file|deleted|renamed|both modified):\s+(.+)$"
)


def git_status(input_text: str) -> str:
    lines = input_text.split("\n")
    if not lines or (len(lines) == 1 and not lines[0].strip()):
        return "Clean working tree"

    branch = ""
    staged_files: list[str] = []
    modified_files: list[str] = []
    untracked_files: list[str] = []
    conflicts = 0

    for raw in lines:
        if not raw.strip():
            continue

        m = _LONG_BRANCH_RE.match(raw)
        if m:
            branch = m.group(1)
            continue

        if raw.startswith("##"):
            branch = re.sub(r"^##\s*", "", raw)
            continue

        if len(raw) >= 3 and _PORCELAIN_RE.match(raw):
            x, y = raw[0], raw[1]
            path = raw[3:]

            if raw[:2] == "??":
                untracked_files.append(path)
                continue

            if x in "MADRC":
                staged_files.append(path)
            elif x == "U":
                conflicts += 1

            if y in ("M", "D"):
                modified_files.append(path)
            continue

        m = _LONG_FORM_RE.match(raw)
        if m:
            kind, path = m.group(1), m.group(2).strip()
            if kind == "both modified":
                conflicts += 1
            elif kind in ("modified", "deleted"):
                modified_files.append(path)
            elif kind in ("new file", "renamed"):
                staged_files.append(path)
            continue

    staged = len(staged_files)
    modified = len(modified_files)
    untracked = len(untracked_files)

    out = ""
    if branch:
        out += f"* {branch}\n"

    if staged > 0:
        out += f"+ Staged: {staged} files\n"
        for f in staged_files[:STATUS_MAX_FILES]:
            out += f"   {f}\n"
        if staged > STATUS_MAX_FILES:
            out += f"   ... +{staged - STATUS_MAX_FILES} more\n"

    if modified > 0:
        out += f"~ Modified: {modified} files\n"
        for f in modified_files[:STATUS_MAX_FILES]:
            out += f"   {f}\n"
        if modified > STATUS_MAX_FILES:
            out += f"   ... +{modified - STATUS_MAX_FILES} more\n"

    if untracked > 0:
        out += f"? Untracked: {untracked} files\n"
        for f in untracked_files[:STATUS_MAX_UNTRACKED]:
            out += f"   {f}\n"
        if untracked > STATUS_MAX_UNTRACKED:
            out += f"   ... +{untracked - STATUS_MAX_UNTRACKED} more\n"

    if conflicts > 0:
        out += f"conflicts: {conflicts} files\n"

    if staged == 0 and modified == 0 and untracked == 0 and conflicts == 0:
        out += "clean — nothing to commit\n"

    return re.sub(r"\n+$", "", out)


git_status.filter_name = "git-status"
