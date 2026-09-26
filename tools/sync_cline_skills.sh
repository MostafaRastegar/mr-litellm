#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# DEPRECATED — use `litellm-marketplace` instead.
#
# This was the first attempt at getting LiteLLM marketplace plugins into
# Cline CLI. It only handled Cline and required Claude Code to be
# installed. It is superseded by tools/litellm_marketplace.py, which reads
# the marketplace directly and installs into every agent (OpenCode, Cline,
# Claude) with a manifest so removal is clean.
#
#   litellm-marketplace list
#   litellm-marketplace install <plugin>
#   litellm-marketplace update [plugin]
#   litellm-marketplace remove [plugin]
#
# Kept as a thin shim so existing notes keep working.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "note: sync_cline_skills.sh is deprecated; delegating to litellm-marketplace" >&2
if [ "$#" -eq 0 ]; then
  exec "$HERE/litellm_marketplace.py" install
fi
exec "$HERE/litellm_marketplace.py" "$@"
