"""Shared pytest fixtures and sample payloads for the rtk_saver test-suite."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeKey:
    """Stand-in for LiteLLM's UserAPIKeyAuth."""

    def __init__(self, metadata=None):
        self.metadata = metadata or {}

    def __repr__(self):
        return f"FakeKey(metadata={self.metadata!r})"


@pytest.fixture
def key_off():
    return FakeKey({})


@pytest.fixture
def key_on():
    return FakeKey(
        {
            "token_saver": {
                "enabled": True,
                "caveman": "lite",
                "ponytail": "off",
                "rtk": True,
                "dedupe_tools": True,
            }
        }
    )


# ── sample tool outputs (large enough to clear MIN_COMPRESS_SIZE=500) ──

GIT_DIFF_SAMPLE = "\n".join(
    [
        "diff --git a/src/auth.py b/src/auth.py",
        "index 1234567..89abcde 100644",
        "--- a/src/auth.py",
        "+++ b/src/auth.py",
        "@@ -10,7 +10,7 @@ def authenticate(user, token):",
        "     if user is None:",
        "         return False",
        "-    if token.expires < now:",
        "+    if token.expires <= now:",
        "         return False",
        "     return True",
        "diff --git a/src/utils.py b/src/utils.py",
        "index aaa1111..bbb2222 100644",
        "--- a/src/utils.py",
        "+++ b/src/utils.py",
        "@@ -1,3 +1,4 @@",
        " import os",
        "+import sys",
        " ",
    ]
) + "\n".join(f"  context line {i} padding to exceed threshold" for i in range(30))

GIT_STATUS_SAMPLE = "\n".join(
    [
        "On branch feature/auth",
        "Changes to be committed:",
        "  new file:   src/auth.py",
        "  modified:   src/app.py",
        "Changes not staged for commit:",
        "  modified:   README.md",
        "  deleted:    old/legacy.py",
        "Untracked files:",
        "?? notes.txt",
        "?? scratch/",
    ]
    + [f"  modified:   src/mod_{i}.py" for i in range(20)]
)

GIT_LOG_SAMPLE = "\n".join(
    [
        "commit 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        "Author: Dev One <dev1@example.com>",
        "Date:   Mon Sep 21 10:00:00 2026 +0330",
        "",
        "    Fix token expiry comparison",
        "",
        "diff --git a/src/auth.py b/src/auth.py",
        "index 111..222 100644",
        "+ some diff body that should be omitted entirely from the output",
    ]
    + [
        f"  padding line {i} to make this blob exceed the minimum size threshold"
        for i in range(20)
    ]
)

GREP_SAMPLE = "\n".join(
    [f"src/module_{i}.py:{i * 7}:    return handler_{i}(request)" for i in range(30)]
)

FIND_SAMPLE = "\n".join(
    [
        "src/app.py",
        "src/utils.py",
        "src/auth/login.py",
        "src/auth/logout.py",
        "tests/test_app.py",
        "tests/test_utils.py",
        "docs/guide.md",
    ]
    + [f"src/pkg_{i}/nested/deep/module_file_{i}.py" for i in range(15)]
)

TREE_SAMPLE = "\n".join(
    [
        ".",
        "├── src",
        "│   ├── app.py",
        "│   └── utils.py",
        "└── tests",
        "    └── test_app.py",
        "",
        "5 directories, 23 files",
    ]
    + [f"│   └── filler_{i}.py" for i in range(25)]
)

LS_SAMPLE = "\n".join(
    [
        "total 48",
        "drwxr-xr-x  4 user user 4096 Sep 21 10:00 src",
        "drwxr-xr-x  2 user user 4096 Sep 21 10:00 tests",
        "-rw-r--r--  1 user user 2048 Sep 21 10:00 README.md",
        "-rw-r--r--  1 user user 8192 Sep 21 10:00 app.py",
        "drwxr-xr-x  2 user user 4096 Sep 21 10:00 node_modules",
    ]
    + [f"-rw-r--r--  1 user user 1024 Sep 21 10:00 file_{i}.js" for i in range(15)]
)

BUILD_SAMPLE = "\n".join(
    [
        "npm warn deprecated left-pad@1.0.0: no longer maintained",
        "npm warn deprecated request@2.88.0: deprecated",
        "npm warn deprecated har-validator@5.1.5: deprecated",
        "npm warn deprecated uuid@3.4.0: deprecated",
        "   Compiling mylib v0.1.0",
        "   Compiling dep_a v0.2.0",
        "   Compiling dep_b v0.3.0",
        " Downloading crates ...",
        "error[E0308]: mismatched types",
        " --> src/main.rs:42:5",
        "  |",
        "42 |     let x: i32 = \"str\";",
        "  |            ^^^ expected i32, found &str",
        "  = note: expected `i32`",
        "added 42 packages, and audited 43 packages in 3s",
    ]
    + [f"  verbose progress line {i}" for i in range(20)]
)

DEDUP_SAMPLE = "\n".join(
    [
        "GET /api/health 200",
        "GET /api/health 200",
        "GET /api/health 200",
        "GET /api/users 200",
        "",
        "",
        "cache hit ratio 0.97",
    ]
    + [f"INFO log line {i} with variable content" for i in range(20)]
)

READ_NUMBERED_SAMPLE = "\n".join(
    f"{i}|def function_{i}(): return {i * 3}" for i in range(400)
)

SEARCH_LIST_SAMPLE = "\n".join(
    ["Result of search in '**/*.py' (total 30 files):"]
    + [f"- src/pkg_{i % 5}/module_{i}.py" for i in range(30)]
)

# Plain unstructured noise. NOTE: >5 non-empty lines of non-duplicate text is
# classified as `dedup-log` by RTK's detect order, which is correct behaviour.
UNSTRUCTURED_DEDUP_BLOB = "\n".join(f"noise line {i} abcdef" for i in range(400))

# Unstructured blob whose lines are ALL identical -> collapse would yield nothing
# useful, so detect falls through to `smart-truncate`.
UNSTRUCTURED_TRUNCATE_BLOB = "\n".join(["repeated identical noise line"] * 400)
