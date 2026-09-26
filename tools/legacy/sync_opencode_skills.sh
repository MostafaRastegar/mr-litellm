#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# DEPRECATED — use `litellm-marketplace` instead.
#
# This was the first attempt at getting LiteLLM marketplace plugins into
# OpenCode. It only handled OpenCode and required Claude Code to be
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

echo "note: sync_opencode_skills.sh is deprecated; delegating to litellm-marketplace" >&2
if [ "$#" -eq 0 ]; then
  exec "$HERE/litellm_marketplace.py" install
fi
exec "$HERE/litellm_marketplace.py" "$@"

# 4. Copy every skills/<name>/SKILL.md into OpenCode's skills dir.
copied=0
while IFS= read -r skill_md; do
  skill_name="$(basename "$(dirname "$skill_md")")"
  mkdir -p "$OPENCODE_SKILLS_DIR/$skill_name"
  cp -f "$skill_md" "$OPENCODE_SKILLS_DIR/$skill_name/SKILL.md"
  echo "  ✔ $skill_name"
  copied=$((copied + 1))
done < <(find "$VERSION_DIR/skills" -mindepth 2 -maxdepth 2 -name 'SKILL.md' 2>/dev/null | sort)

if [ "$copied" -eq 0 ]; then
  echo "✘ No SKILL.md files found under $VERSION_DIR/skills" >&2
  exit 1
fi

echo "✔ Synced $copied skill(s) into $OPENCODE_SKILLS_DIR"
