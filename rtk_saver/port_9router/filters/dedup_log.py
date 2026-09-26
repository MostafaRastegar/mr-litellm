"""Generic fallback: collapse consecutive duplicate lines + blank-line dedupe + cap."""

from ..constants import DEDUP_LINE_MAX


def dedup_log(input_text: str) -> str:
    lines = input_text.split("\n")
    out: list[str] = []
    prev: str | None = None
    run_count = 0
    blank_streak = 0

    def flush_run() -> None:
        if prev is not None and run_count > 1:
            out.append(f"  ... ({run_count - 1} duplicate lines)")

    for line in lines:
        if line.strip() == "":
            if blank_streak < 1:
                out.append(line)
            blank_streak += 1
            flush_run()
            prev = None
            run_count = 0
            continue
        blank_streak = 0
        if line == prev:
            run_count += 1
            continue
        flush_run()
        out.append(line)
        prev = line
        run_count = 1
        if len(out) >= DEDUP_LINE_MAX:
            out.append(f"... (truncated at {DEDUP_LINE_MAX} lines)")
            return "\n".join(out)

    flush_run()
    return "\n".join(out)


dedup_log.filter_name = "dedup-log"
