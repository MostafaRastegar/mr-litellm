"""JS-native git-log filter port.

Compresses `git log` output: keeps commit headers, subjects, Author/Date;
drops body padding, decoration, embedded diff lines.
"""

import re

from ..constants import GIT_LOG_MAX_LINES

_COMMIT_HEADER_RE = re.compile(r"^commit [0-9a-f]{7,40}$", re.IGNORECASE)
_COMMIT_GRAPH_RE = re.compile(r"^[*|/\\ ]+commit [0-9a-f]{7,40}", re.IGNORECASE)
_AUTHOR_DATE_RE = re.compile(r"^[*|/\\ ]*(?:Author|Date):", re.IGNORECASE)
_INDENTED_SUBJECT_RE = re.compile(r"^[*|/\\ ]*    \S")
_STAT_SUMMARY_RE = re.compile(r"^\d+ file\w* changed")
_GRAPH_SHA_SUBJECT_RE = re.compile(r"^[*|/\\ ]+([0-9a-f]{7,40}\s+.+)", re.IGNORECASE)
_ONELINE_RE = re.compile(r"^[0-9a-f]{7,40}\s+")
_GRAPH_DECORATION_RE = re.compile(r"^[*|/\\ ]+$")


def git_log(text: str, max_lines: int = GIT_LOG_MAX_LINES) -> str:
    if not text:
        return ""

    lines = text.split("\n")
    out: list[str] = []
    skipped = 0
    in_commit = False
    subject_seen = False

    def push_line(line: str) -> None:
        nonlocal skipped
        if len(out) < max_lines:
            out.append(line)
        else:
            skipped += 1

    for raw in lines:
        line = raw.rstrip()
        trimmed = line.strip()

        if _COMMIT_HEADER_RE.match(trimmed) or _COMMIT_GRAPH_RE.match(trimmed):
            in_commit = True
            subject_seen = False
            push_line(line)
            continue

        if in_commit:
            if _AUTHOR_DATE_RE.match(trimmed):
                push_line(trimmed)
                continue
            if trimmed == "":
                continue
            if not subject_seen and _INDENTED_SUBJECT_RE.match(line):
                push_line("  Subject: " + trimmed)
                subject_seen = True
                continue
            if _STAT_SUMMARY_RE.match(trimmed):
                push_line("  " + trimmed)
                continue
            if trimmed.startswith("diff --git "):
                push_line("  ... diff body omitted")
                continue
            continue

        # Not in a commit block (--oneline / --graph modes)
        m = _GRAPH_SHA_SUBJECT_RE.match(trimmed)
        if m:
            push_line(m.group(1))
            continue

        if _ONELINE_RE.match(trimmed):
            push_line(trimmed)
            continue

        if _GRAPH_DECORATION_RE.match(trimmed) and re.search(r"[*|/\\]", trimmed):
            continue

        push_line(trimmed)

    if skipped > 0:
        out.append(f"... ({skipped} more lines)")

    result = "\n".join(out)
    if not result and text:
        return text
    if len(result) > len(text):
        return text
    return result


git_log.filter_name = "git-log"
