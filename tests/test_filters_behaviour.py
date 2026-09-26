"""Behavioural tests for each individual RTK filter."""

from rtk_saver.constants import (
    FIND_PER_DIR_MAX,
    FIND_TOTAL_DIR_MAX,
    GREP_PER_FILE_MAX,
    STATUS_MAX_FILES,
)
from rtk_saver.filters import (
    build_output,
    dedup_log,
    find,
    git_diff,
    git_log,
    git_status,
    grep,
    ls,
    read_numbered,
    search_list,
    smart_truncate,
    tree,
)

from .conftest import (
    BUILD_SAMPLE,
    DEDUP_SAMPLE,
    FIND_SAMPLE,
    GIT_DIFF_SAMPLE,
    GIT_LOG_SAMPLE,
    GIT_STATUS_SAMPLE,
    GREP_SAMPLE,
    LS_SAMPLE,
    READ_NUMBERED_SAMPLE,
    SEARCH_LIST_SAMPLE,
    TREE_SAMPLE,
)


# ── git-diff ─────────────────────────────────────────────────────────


def test_git_diff_keeps_file_headers_and_hunk_markers():
    out = git_diff(GIT_DIFF_SAMPLE)
    assert "src/auth.py" in out
    assert "src/utils.py" in out
    assert "@@" in out


def test_git_diff_keeps_the_actual_change_lines():
    out = git_diff(GIT_DIFF_SAMPLE)
    assert "-    if token.expires < now:" in out
    assert "+    if token.expires <= now:" in out


def test_git_diff_adds_plus_minus_counters():
    out = git_diff(GIT_DIFF_SAMPLE)
    # "+1 -1" style counters are emitted per file
    assert "+1 -1" in out


def test_git_diff_shrinks_the_payload():
    assert len(git_diff(GIT_DIFF_SAMPLE)) < len(GIT_DIFF_SAMPLE)


def test_git_diff_marks_truncation_with_recovery_hint():
    """When a hunk blows past the per-hunk cap, a recovery hint is emitted."""
    big_hunk = "\n".join(
        ["diff --git a/big.py b/big.py", "@@ -1,200 +1,200 @@"]
        + [f"+added line {i}" for i in range(200)]
    )
    out = git_diff(big_hunk)
    assert "truncated" in out
    assert "[full diff: rtk git diff --no-compact]" in out


def test_git_diff_small_diff_is_not_marked_truncated():
    out = git_diff(GIT_DIFF_SAMPLE)
    assert "[full diff" not in out


# ── git-status ───────────────────────────────────────────────────────


def test_git_status_extracts_branch_and_counts():
    out = git_status(GIT_STATUS_SAMPLE)
    assert "feature/auth" in out
    assert "Staged:" in out
    assert "Modified:" in out
    assert "Untracked:" in out


def test_git_status_caps_listed_files():
    out = git_status(GIT_STATUS_SAMPLE)
    listed = [l for l in out.split("\n") if l.startswith("   ")]
    # staged + modified + untracked listings, each capped
    assert len(listed) <= 3 * STATUS_MAX_FILES + 5
    assert "more" in out


def test_git_status_porcelain_input():
    porcelain = "## main...origin/main\n M src/a.py\n?? src/b.py\nA  src/c.py"
    out = git_status(porcelain)
    assert "main" in out
    assert "src/a.py" in out
    assert "src/b.py" in out


def test_git_status_empty_input_is_clean():
    assert git_status("") == "Clean working tree"


def test_git_status_reports_clean_when_no_changes():
    out = git_status("On branch main")
    assert "clean" in out.lower()


# ── git-log ──────────────────────────────────────────────────────────


def test_git_log_keeps_commit_subject_and_author():
    out = git_log(GIT_LOG_SAMPLE)
    assert "commit 1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b" in out
    assert "Subject: Fix token expiry comparison" in out
    assert "Author: Dev One" in out


def test_git_log_omits_embedded_diff_bodies():
    out = git_log(GIT_LOG_SAMPLE)
    assert "diff body omitted" in out
    assert "some diff body that should be omitted" not in out


def test_git_log_oneline_mode_passes_sha_subject():
    out = git_log("abc1234 Fix the thing\nfed4321 Add another thing")
    assert "abc1234 Fix the thing" in out
    assert "fed4321 Add another thing" in out


def test_git_log_never_grows_the_input():
    assert len(git_log(GIT_LOG_SAMPLE)) <= len(GIT_LOG_SAMPLE)


# ── grep ─────────────────────────────────────────────────────────────


def test_grep_groups_by_file_with_match_count():
    out = grep(GREP_SAMPLE)
    assert "matches in" in out
    assert "[file] src/module_0.py" in out


def test_grep_caps_matches_per_file():
    heavy = "\n".join(f"src/big.py:{i}:match content {i}" for i in range(50))
    out = grep(heavy)
    assert f"+{50 - GREP_PER_FILE_MAX}" in out
    body_lines = [l for l in out.split("\n") if l.startswith("  ") and ":" in l]
    assert len(body_lines) == GREP_PER_FILE_MAX


def test_grep_passthrough_when_no_match_lines():
    assert grep("no colons here") == "no colons here"
    assert grep("not-a-number:abc:content") == "not-a-number:abc:content"


def test_grep_preserves_line_numbers_and_trims_content():
    out = grep("src/a.py:42:    indented content   ")
    assert "42: indented content" in out


# ── find ─────────────────────────────────────────────────────────────


def test_find_groups_by_directory():
    out = find(FIND_SAMPLE)
    assert "files in" in out
    assert "src/auth/  (2)" in out


def test_find_caps_per_dir_and_total_dirs():
    out = find(FIND_SAMPLE)
    per_dir = [
        l for l in out.split("\n") if l.startswith("  ") and not l.startswith("  +")
    ]
    assert len(per_dir) <= FIND_PER_DIR_MAX * FIND_TOTAL_DIR_MAX


def test_find_marks_overflow_when_a_dir_exceeds_per_dir_cap():
    many = "\n".join(f"src/big/file_{i}.py" for i in range(FIND_PER_DIR_MAX + 7))
    out = find(many)
    assert "  +7" in out


def test_find_marks_more_dirs_when_over_the_cap():
    many = "\n".join(f"dir_{i}/file.py" for i in range(FIND_TOTAL_DIR_MAX + 10))
    out = find(many)
    assert "more dirs" in out


def test_find_handles_windows_paths():
    win = "\n".join([r"C:\repo\src\a.py", r"C:\repo\src\b.py", r"C:\repo\tests\c.py"])
    out = find(win)
    assert "C:/repo/src/" in out


def test_find_passthrough_on_empty():
    assert find("   \n  ") == "   \n  "


# ── tree ─────────────────────────────────────────────────────────────


def test_tree_drops_summary_and_trailing_blanks():
    out = tree(TREE_SAMPLE)
    assert "directories" not in out
    assert not out.endswith("\n")
    assert "├── src" in out


def test_tree_caps_long_output():
    huge = "\n".join(["root"] + [f"├── f{i}" for i in range(500)])
    out = tree(huge)
    assert "more lines" in out
    assert len(out.split("\n")) <= 202


# ── ls ───────────────────────────────────────────────────────────────


def test_ls_marks_dirs_and_drops_noise():
    out = ls(LS_SAMPLE)
    assert "src/" in out
    assert "tests/" in out
    assert "node_modules" not in out


def test_ls_emits_summary_line():
    out = ls(LS_SAMPLE)
    assert "Summary:" in out
    assert "dirs" in out


def test_ls_drops_total_header_and_humanizes_size():
    out = ls(LS_SAMPLE)
    assert not out.startswith("total ")
    assert "2.0K" in out or "1.0K" in out or "B" in out


# ── build-output ─────────────────────────────────────────────────────


def test_build_output_keeps_rust_error_block_verbatim():
    out = build_output(BUILD_SAMPLE)
    assert "error[E0308]: mismatched types" in out
    assert "src/main.rs:42:5" in out
    assert "expected `i32`" in out


def test_build_output_collapses_compiling_and_downloading_counts():
    out = build_output(BUILD_SAMPLE)
    assert "Compiled 3 packages" in out
    assert "Downloaded 1 packages" in out


def test_build_output_keeps_summary_line():
    out = build_output(BUILD_SAMPLE)
    assert "audited 43 packages" in out


def test_build_output_caps_deprecations():
    many = "\n".join(f"npm warn deprecated pkg{i}@1.0.0: reason" for i in range(10))
    out = build_output(many)
    assert "more deprecated packages" in out


def test_build_output_shrinks_payload():
    assert len(build_output(BUILD_SAMPLE)) < len(BUILD_SAMPLE)


# ── dedup-log ────────────────────────────────────────────────────────


def test_dedup_log_collapses_consecutive_duplicates():
    out = dedup_log(DEDUP_SAMPLE)
    assert "duplicate lines" in out
    assert out.count("GET /api/health 200") == 1
    assert "GET /api/users 200" in out


def test_dedup_log_collapses_blank_streaks():
    out = dedup_log("a\n\n\n\n\nb")
    assert out.count("\n\n") == 1


def test_dedup_log_shrinks_payload():
    assert len(dedup_log(DEDUP_SAMPLE)) < len(DEDUP_SAMPLE)


# ── smart-truncate ───────────────────────────────────────────────────


def test_smart_truncate_keeps_head_and_tail():
    blob = "\n".join(f"line {i}" for i in range(400))
    out = smart_truncate(blob)
    assert out.startswith("line 0")
    assert out.endswith("line 399")
    assert "lines truncated" in out


def test_smart_truncate_passthrough_below_threshold():
    small = "\n".join(f"line {i}" for i in range(10))
    assert smart_truncate(small) == small


# ── read-numbered ────────────────────────────────────────────────────


def test_read_numbered_keeps_head_and_tail():
    out = read_numbered(READ_NUMBERED_SAMPLE)
    assert out.startswith("0|")
    assert out.endswith("399|def function_399(): return 1197")
    assert "file continues" in out
    assert "200|" not in out  # middle is cut


def test_read_numbered_passthrough_when_small():
    small = "\n".join(f"{i}|x" for i in range(5))
    assert read_numbered(small) == small


# ── search-list ──────────────────────────────────────────────────────


def test_search_list_keeps_header_and_groups_dirs():
    out = search_list(SEARCH_LIST_SAMPLE)
    assert "Result of search in" in out
    assert "files in" in out
    assert "src/pkg_0/ (" in out


def test_search_list_passthrough_without_paths():
    lone = "Result of search in '**/*.py' (total 0 files):"
    assert search_list(lone) == lone


def test_search_list_shrinks_payload():
    assert len(search_list(SEARCH_LIST_SAMPLE)) < len(SEARCH_LIST_SAMPLE)
