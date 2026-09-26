"""RTK port constants (mirror Rust defaults / 9Router open-sse/rtk/constants.js)."""

RAW_CAP = 10 * 1024 * 1024  # 10 MiB
MIN_COMPRESS_SIZE = 500  # bytes; skip tiny blobs
DETECT_WINDOW = 1024  # autodetect peeks first N chars
GIT_DIFF_HUNK_MAX_LINES = 100  # per-hunk line cap
GIT_DIFF_CONTEXT_KEEP = 3  # context lines around changes
GIT_LOG_MAX_LINES = 200  # gitLog line cap
DEDUP_LINE_MAX = 2000  # dedupLog truncation cap

# Rust pipe_cmd.rs parity caps
GREP_PER_FILE_MAX = 10  # match rust: matches.iter().take(10)
FIND_PER_DIR_MAX = 10  # match rust: files.iter().take(10)
FIND_TOTAL_DIR_MAX = 20  # match rust: dirs.iter().take(20)

# git status caps (rust config::limits())
STATUS_MAX_FILES = 10  # config::limits().status_max_files
STATUS_MAX_UNTRACKED = 10  # config::limits().status_max_untracked

# ls compact_ls (rtk/src/cmds/system/ls.rs)
LS_EXT_SUMMARY_TOP = 5  # top-N extensions in summary
LS_NOISE_DIRS = [
    "node_modules",
    ".git",
    "target",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".cache",
    ".turbo",
    ".vercel",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
    "venv",
    "env",  # Python legacy virtualenv; .env (dotenv) intentionally excluded
    "coverage",
    ".nyc_output",
    ".DS_Store",
    "Thumbs.db",
    ".idea",
    ".vscode",
    ".vs",
    "*.egg-info",
    ".eggs",
]

# tree filter_tree_output cap (no rust cap, we add one to be safe)
TREE_MAX_LINES = 200

# Cursor Glob "Result of search in '...' (total N files):" list
SEARCH_LIST_PER_DIR_MAX = 10
SEARCH_LIST_TOTAL_DIR_MAX = 20

# Smart truncate (port of filter.rs smart_truncate fallback)
SMART_TRUNCATE_HEAD = 120  # lines kept from top
SMART_TRUNCATE_TAIL = 60  # lines kept from bottom
SMART_TRUNCATE_MIN_LINES = 250  # only kick in above this

# readNumbered (files with "  N|content" lines, e.g. Cursor read_file)
READ_NUMBERED_MIN_HIT_RATIO = 0.7

# Filter name strings (Rust parity + JS extras)
FILTERS = {
    "GIT_DIFF": "git-diff",
    "GIT_STATUS": "git-status",
    "GIT_LOG": "git-log",
    "GREP": "grep",
    "FIND": "find",
    "DEDUP_LOG": "dedup-log",
    "LS": "ls",
    "TREE": "tree",
    "SMART_TRUNCATE": "smart-truncate",
    "READ_NUMBERED": "read-numbered",
    "SEARCH_LIST": "search-list",
    "BUILD_OUTPUT": "build-output",
}
