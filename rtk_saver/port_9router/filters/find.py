"""Port of find_wrapper (rtk/src/cmds/system/pipe_cmd.rs:89-128).

Group by parent dir, show basenames, cap 10/dir and 20 dirs total.
"""

from ..constants import FIND_PER_DIR_MAX, FIND_TOTAL_DIR_MAX

SEP_CHARS = ("/", "\\")


def find(input_text: str) -> str:
    lines = [l for l in input_text.split("\n") if l.strip()]
    if not lines:
        return input_text

    by_dir: dict[str, list[str]] = {}

    for path in lines:
        last_sep = max(path.rfind("/"), path.rfind("\\"))
        if last_sep == -1:
            directory, basename = ".", path
        else:
            directory = path[:last_sep] or "/"
            basename = path[last_sep + 1 :]
        by_dir.setdefault(directory, []).append(basename)

    dirs = sorted(by_dir.keys())
    out = f"{len(lines)} files in {len(dirs)} dirs:\n\n"

    for directory in dirs[:FIND_TOTAL_DIR_MAX]:
        files = by_dir[directory]
        dir_label = directory.replace("\\", "/")
        out += f"{dir_label}/  ({len(files)})\n"
        for f in files[:FIND_PER_DIR_MAX]:
            out += f"  {f}\n"
        if len(files) > FIND_PER_DIR_MAX:
            out += f"  +{len(files) - FIND_PER_DIR_MAX}\n"

    if len(dirs) > FIND_TOTAL_DIR_MAX:
        out += f"\n+{len(dirs) - FIND_TOTAL_DIR_MAX} more dirs\n"

    return out


find.filter_name = "find"
