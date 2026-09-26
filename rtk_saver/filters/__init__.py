"""RTK filter registry + autodetect.

Port of 9Router:
  open-sse/rtk/autodetect.js
  open-sse/rtk/registry.js
  open-sse/rtk/applyFilter.js
"""

import re
from typing import Callable, Optional

from ..constants import (
    DETECT_WINDOW,
    READ_NUMBERED_MIN_HIT_RATIO,
    SMART_TRUNCATE_MIN_LINES,
)
from .build_output import build_output
from .dedup_log import dedup_log
from .find import find
from .git_diff import git_diff
from .git_log import git_log
from .git_status import git_status
from .grep import grep
from .ls import ls
from .read_numbered import READ_NUMBERED_LINE_RE, read_numbered
from .search_list import SEARCH_LIST_HEADER_RE, search_list
from .smart_truncate import smart_truncate
from .tree import tree

RE_GIT_DIFF = re.compile(r"^diff --git ", re.M)
RE_GIT_DIFF_HUNK = re.compile(r"^@@ ", re.M)
RE_GIT_STATUS = re.compile(
    r"^On branch |^nothing to commit|^Changes (not |to be )|^Untracked files:", re.M
)
RE_GIT_LOG = re.compile(r"^[*|/\\ ]*commit [0-9a-f]{7,40}$", re.M)
RE_PORCELAIN = re.compile(r"^[ MADRCU?!][ MADRCU?!] \S")
RE_BUILD_OUTPUT = re.compile(
    r"^(npm (warn|error|ERR!)|yarn (warn|error)|\s*Compiling\s+\S+|"
    r"\s*Downloading\s+\S+|added \d+ package|\[ERROR\]|BUILD (SUCCESS|FAILED)|"
    r"\s*Finished\s+|Successfully (installed|built)|ERROR:)",
    re.M | re.I,
)
RE_TREE_GLYPH = re.compile(r"[├└]──|│  ")
RE_LS_ROW = re.compile(r"^[-dlbcps][rwx-]{9}", re.M)
RE_LS_TOTAL = re.compile(r"^total \d+$", re.M)

REGISTRY: dict[str, Callable[[str], str]] = {
    "git-diff": git_diff,
    "git-status": git_status,
    "git-log": git_log,
    "grep": grep,
    "find": find,
    "dedup-log": dedup_log,
    "ls": ls,
    "tree": tree,
    "smart-truncate": smart_truncate,
    "read-numbered": read_numbered,
    "search-list": search_list,
    "build-output": build_output,
}

# Rust resolve_filter aliases (pipe_cmd.rs): grep|rg, find|fd
ALIASES = {"rg": grep, "fd": find}


def resolve_filter(name: str) -> Optional[Callable[[str], str]]:
    return REGISTRY.get(name) or ALIASES.get(name)


def all_filters() -> dict[str, Callable[[str], str]]:
    return dict(REGISTRY)


def _is_grep_line(line: str) -> bool:
    first = line.find(":")
    if first == -1:
        return False
    second = line.find(":", first + 1)
    if second == -1:
        return False
    return line[first + 1 : second].isdigit()


def _is_path_like(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    # Windows absolute path
    if re.match(r"^[A-Za-z]:[\\/]", t):
        return True
    if ":" in t:
        return False
    return t.startswith(".") or t.startswith("/") or "/" in t


def _is_mostly_porcelain(head: str) -> bool:
    lines = [l for l in head.split("\n") if l.strip()]
    if len(lines) < 3:
        return False
    hits = sum(1 for l in lines if RE_PORCELAIN.match(l))
    return hits / len(lines) >= 0.6


def _is_line_numbered(lines: list[str]) -> bool:
    hits = 0
    non_empty = 0
    for l in lines[:100]:
        if l == "":
            continue
        non_empty += 1
        if READ_NUMBERED_LINE_RE.match(l):
            hits += 1
    if non_empty < 5:
        return False
    return hits / non_empty >= READ_NUMBERED_MIN_HIT_RATIO


def auto_detect_filter(text: str) -> Optional[Callable[[str], str]]:
    """Port of auto_detect_filter (rtk/src/cmds/system/pipe_cmd.rs:132-188)."""
    head = text[:DETECT_WINDOW] if len(text) > DETECT_WINDOW else text

    if RE_GIT_LOG.search(head):
        return git_log
    if RE_GIT_DIFF.search(head) or RE_GIT_DIFF_HUNK.search(head):
        return git_diff
    if RE_GIT_STATUS.search(head):
        return git_status

    # Build output BEFORE porcelain check: prevents cargo "Compiling" misdetect
    if RE_BUILD_OUTPUT.search(head):
        return build_output

    if _is_mostly_porcelain(head):
        return git_status

    lines = head.split("\n")
    non_empty = [l for l in lines if l.strip()]

    # Rust grep rule: first 5 non-empty lines, ANY matches "file:number:content"
    if any(_is_grep_line(l) for l in non_empty[:5]):
        return grep

    # Rust find rule: ALL non-empty lines path-like (no ':'), >=3 lines
    if len(non_empty) >= 3 and all(_is_path_like(l) for l in non_empty):
        return find

    if RE_TREE_GLYPH.search(head):
        return tree

    if RE_LS_TOTAL.search(head) or len(RE_LS_ROW.findall(head)) >= 3:
        return ls

    if SEARCH_LIST_HEADER_RE.search(head):
        return search_list

    if len(lines) >= SMART_TRUNCATE_MIN_LINES and _is_line_numbered(lines):
        return read_numbered

    if len(non_empty) >= 5:
        return dedup_log

    if len(lines) >= SMART_TRUNCATE_MIN_LINES:
        return smart_truncate

    return None


def safe_apply(fn: Optional[Callable[[str], str]], text: str) -> str:
    """Port of apply_filter — on panic/error: passthrough raw output."""
    if fn is None or not callable(fn):
        return text
    try:
        out = fn(text)
        if not isinstance(out, str):
            return text
        return out
    except Exception as exc:  # noqa: BLE001 - deliberate fail-open
        name = getattr(fn, "filter_name", None) or getattr(fn, "__name__", "anonymous")
        print(
            f"[rtk] warning: filter '{name}' raised — passing through raw output: {exc}",
            flush=True,
        )
        return text
