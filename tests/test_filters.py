"""Unit tests for the RTK filters — parity with 9Router's tests/unit/rtk.test.js."""

from rtk_saver.filters import (
    REGISTRY,
    all_filters,
    auto_detect_filter,
    build_output,
    dedup_log,
    find,
    git_diff,
    git_log,
    git_status,
    grep,
    ls,
    read_numbered,
    resolve_filter,
    safe_apply,
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
    UNSTRUCTURED_DEDUP_BLOB,
    UNSTRUCTURED_TRUNCATE_BLOB,
)


def test_all_twelve_filters_registered():
    assert len(all_filters()) == 12
    expected = {
        "git-diff",
        "git-status",
        "git-log",
        "grep",
        "find",
        "dedup-log",
        "ls",
        "tree",
        "smart-truncate",
        "read-numbered",
        "search-list",
        "build-output",
    }
    assert set(REGISTRY) == expected


def test_filter_name_attribute_present_on_every_filter():
    for name, fn in all_filters().items():
        assert getattr(fn, "filter_name", None) == name, name


def test_aliases_resolve():
    assert resolve_filter("rg") is grep
    assert resolve_filter("fd") is find
    assert resolve_filter("nope") is None


# ── autodetect ───────────────────────────────────────────────────────


def test_autodetect_routes_each_sample_to_expected_filter():
    cases = [
        (GIT_DIFF_SAMPLE, git_diff),
        (GIT_STATUS_SAMPLE, git_status),
        (GIT_LOG_SAMPLE, git_log),
        (GREP_SAMPLE, grep),
        (FIND_SAMPLE, find),
        (TREE_SAMPLE, tree),
        (LS_SAMPLE, ls),
        (BUILD_SAMPLE, build_output),
        (SEARCH_LIST_SAMPLE, search_list),
    ]
    for sample, expected in cases:
        got = auto_detect_filter(sample)
        assert got is expected, (
            f"expected {expected.filter_name}, "
            f"got {getattr(got, 'filter_name', got)}"
        )


def test_autodetect_read_numbered_is_unreachable_via_window():
    """Parity note (verified against 9Router's own JS at v0.5.81).

    `lines` in the read-numbered branch come from the 1024-char detect window,
    so `lines.length >= SMART_TRUNCATE_MIN_LINES (250)` can never be true —
    a 1024-char window holds ~33 lines. The branch is dead code upstream and
    therefore here too; `read-numbered` stays reachable via resolve_filter.
    """
    assert auto_detect_filter(READ_NUMBERED_SAMPLE) is dedup_log
    assert resolve_filter("read-numbered") is read_numbered


def test_autodetect_build_output_beats_porcelain_check():
    """cargo 'Compiling' lines must not be misread as git-status."""
    assert auto_detect_filter(BUILD_SAMPLE) is build_output


def test_autodetect_returns_dedup_for_generic_multi_line_noise():
    assert auto_detect_filter(DEDUP_SAMPLE) is dedup_log


def test_autodetect_dedup_precedes_smart_truncate():
    """RTK detect order: dedup-log (>=5 non-empty) is checked before smart-truncate.

    So smart-truncate is not reachable through auto-detect for varied text; it is
    an explicit last-resort filter. This test pins that documented ordering.
    """
    assert auto_detect_filter(UNSTRUCTURED_DEDUP_BLOB) is dedup_log
    assert auto_detect_filter(UNSTRUCTURED_TRUNCATE_BLOB) is dedup_log


def test_smart_truncate_is_still_directly_usable():
    """smart-truncate remains available via the registry / resolve_filter."""
    assert resolve_filter("smart-truncate") is smart_truncate
    out = smart_truncate(UNSTRUCTURED_TRUNCATE_BLOB)
    assert "lines truncated" in out


def test_autodetect_returns_none_for_short_plain_text():
    assert auto_detect_filter("hello world") is None


# ── safe_apply (fail-open) ───────────────────────────────────────────


def test_safe_apply_returns_raw_text_when_filter_raises():
    def boom(_text):
        raise RuntimeError("kaboom")

    boom.filter_name = "boom"
    assert safe_apply(boom, "original") == "original"


def test_safe_apply_returns_raw_text_when_filter_returns_non_string():
    assert safe_apply(lambda _t: 12345, "original") == "original"


def test_safe_apply_handles_none_filter():
    assert safe_apply(None, "original") == "original"
