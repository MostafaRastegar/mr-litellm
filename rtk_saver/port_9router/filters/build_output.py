"""Compress build tool output (npm, cargo, pip, maven, gradle, etc.).

Keeps: errors, warnings, final summary.
Strips: progress logs, verbose "Compiling X" lists, download logs.
"""

import re

# Cargo/rustc error continuation: " --> file:line", "  |", "N | code", "  = note: ..."
_RE_CARGO_ERR_CONT = re.compile(r"^\s*(-->|\||\d+\s*\||=)")
DEPRECATION_KEEP = 3


def build_output(input_text: str) -> str:
    lines = input_text.split("\n")
    if not lines:
        return input_text

    errors: list[str] = []
    warnings: list[str] = []
    deprecations: list[str] = []
    summary: str | None = None
    compiling_count = 0
    downloading_count = 0
    in_cargo_error = False

    for line in lines:
        trimmed = line.strip()

        if in_cargo_error:
            if not trimmed:
                in_cargo_error = False
                continue
            if _RE_CARGO_ERR_CONT.match(line):
                errors.append(line)
                continue
            in_cargo_error = False

        if not trimmed:
            continue

        if re.match(r"^npm (ERR!|error)", trimmed, re.I) or re.match(
            r"^yarn error", trimmed, re.I
        ):
            errors.append(line)
            continue

        if re.match(r"^npm warn deprecated", trimmed, re.I):
            deprecations.append(line)
            continue
        if re.match(r"^npm warn", trimmed, re.I) or re.match(
            r"^yarn warn", trimmed, re.I
        ):
            warnings.append(line)
            continue

        if re.match(r"^error(\[|:)", trimmed, re.I) or trimmed.startswith("error -->"):
            errors.append(line)
            in_cargo_error = True
            continue

        if re.match(r"^warning(\[|:)", trimmed, re.I) or trimmed.startswith(
            "warning -->"
        ):
            warnings.append(line)
            in_cargo_error = True
            continue

        if re.match(r"^ERROR:", trimmed, re.I):
            errors.append(line)
            continue

        if re.match(r"^\[ERROR\]", trimmed, re.I) or re.match(
            r"^BUILD FAILED", trimmed, re.I
        ):
            errors.append(line)
            continue

        if re.match(r"^\[WARNING\]", trimmed, re.I):
            warnings.append(line)
            continue

        if re.match(r"^\s*Compiling\s+\S+", trimmed, re.I):
            compiling_count += 1
            continue
        if re.match(r"^\s*Downloading\s+\S+", trimmed, re.I) or re.match(
            r"^Fetching\s+", trimmed, re.I
        ):
            downloading_count += 1
            continue

        if (
            re.match(
                r"^(added|removed|changed|audited|installed)\s+\d+\s+package",
                trimmed,
                re.I,
            )
            or re.match(r"^\s*Finished\s+", trimmed, re.I)
            or re.match(r"^BUILD SUCCESS", trimmed, re.I)
            or re.match(r"^\d+\s+(vulnerabilities|packages?|warnings?|errors?)", trimmed, re.I)
            or re.match(r"^Successfully (installed|built)", trimmed, re.I)
            or re.match(r"^To address .* issues", trimmed, re.I)
            or re.match(r"^Run `npm (audit|fund)`", trimmed, re.I)
            or "packages are looking for funding" in trimmed
        ):
            summary = f"{summary}\n{line}" if summary else line
            continue

    out = ""

    keep_dep = deprecations[:DEPRECATION_KEEP]
    for d in keep_dep:
        out += f"{d}\n"
    if len(deprecations) > DEPRECATION_KEEP:
        out += f"... +{len(deprecations) - DEPRECATION_KEEP} more deprecated packages\n"

    if compiling_count > 0:
        out += f"Compiled {compiling_count} packages\n"
    if downloading_count > 0:
        out += f"Downloaded {downloading_count} packages\n"

    for e in errors:
        out += f"{e}\n"

    for w in warnings[:5]:
        out += f"{w}\n"
    if len(warnings) > 5:
        out += f"... +{len(warnings) - 5} more warnings\n"

    if summary:
        out += f"{summary}\n"

    return re.sub(r"\n+$", "", out) or input_text


build_output.filter_name = "build-output"
