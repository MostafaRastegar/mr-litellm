"""Dump sample inputs to JSON so the JS reference runner can consume them."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.conftest import (  # noqa: E402
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

SAMPLES = {
    "git_diff": GIT_DIFF_SAMPLE,
    "git_status": GIT_STATUS_SAMPLE,
    "git_log": GIT_LOG_SAMPLE,
    "grep": GREP_SAMPLE,
    "find": FIND_SAMPLE,
    "tree": TREE_SAMPLE,
    "ls": LS_SAMPLE,
    "build_output": BUILD_SAMPLE,
    "dedup": DEDUP_SAMPLE,
    "read_numbered": READ_NUMBERED_SAMPLE,
    "search_list": SEARCH_LIST_SAMPLE,
    "unstructured_dedup": UNSTRUCTURED_DEDUP_BLOB,
    "unstructured_truncate": UNSTRUCTURED_TRUNCATE_BLOB,
}

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/rtk_src/parity_samples.json"
    with open(target, "w") as fh:
        json.dump(SAMPLES, fh, indent=2)
    print(f"wrote {len(SAMPLES)} samples to {target}")
