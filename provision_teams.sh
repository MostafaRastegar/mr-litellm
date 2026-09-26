#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# provision_teams.sh — create per-team budgets and per-team virtual keys,
# with the token saver configured per the team's needs.
#
# Usage:
#   export LITELLM_MASTER_KEY="sk-..."
#   export LITELLM_URL="http://localhost:4000"
#   ./provision_teams.sh
#
# Every team gets its own key. Nobody ever sees a provider API key, and
# nobody can call a model outside their allowlist.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

LITELLM_URL="${LITELLM_URL:-http://localhost:4000}"
: "${LITELLM_MASTER_KEY:?set LITELLM_MASTER_KEY first}"

AUTH=(-H "Authorization: Bearer ${LITELLM_MASTER_KEY}" -H "Content-Type: application/json")

jqf() { python3 -c "import sys,json;print(json.load(sys.stdin)$1)"; }

echo "▶ gateway: ${LITELLM_URL}"

# ── 1. Teams ──────────────────────────────────────────────────────────
# Each entry: alias|models(json)|budget_usd|budget_duration
#   • content    — lightweight models; prose output, no heavy compression
#   • programmer — coding models; aggressive token saving with all filters
TEAMS=(
  'content|["claude-haiku","gemini-pro","or-free"]|150|30d'
  'programmer|["claude-sonnet","gpt-4o"]|400|30d'
)

declare -A TEAM_IDS

for entry in "${TEAMS[@]}"; do
  IFS='|' read -r alias models budget duration <<<"$entry"
  echo "▶ creating team: ${alias}"

  resp=$(curl -sS -X POST "${LITELLM_URL}/team/new" "${AUTH[@]}" \
    -d "$(printf '{"team_alias":"%s","models":%s,"max_budget":%s,"budget_duration":"%s"}' \
          "$alias" "$models" "$budget" "$duration")")

  tid=$(echo "$resp" | jqf "['team_id']" 2>/dev/null || true)
  if [[ -z "${tid:-}" ]]; then
    echo "  ⚠ could not create ${alias}; response: ${resp}"
    continue
  fi
  TEAM_IDS["$alias"]="$tid"
  echo "  ✔ team_id=${tid}  budget=\$${budget}/${duration}"
done

# ── 2. Virtual keys ───────────────────────────────────────────────────
# token_saver metadata is attached per key, so rollout is granular.
#   caveman levels: off | lite | full | ultra | wenyan-lite | wenyan | wenyan-ultra
#   ponytail levels: off | lite | full | ultra
#
# NOTE: caveman/ponytail affect OUTPUT style. Keep them off for content/
# prose work; they are fine (even desirable) for code/tool-heavy sessions.
emit_key() {
  local alias="$1" team="$2" sav_cfg="$3" note="$4"
  local tid="${TEAM_IDS[$team]:-}"
  [[ -z "$tid" ]] && { echo "  ⚠ skipping ${alias}: team ${team} missing"; return; }

  # Fetch the team's model allowlist (use json.dumps for valid JSON, not Python repr)
  local models_json
  models_json=$(curl -sS "${LITELLM_URL}/team/info?team_id=${tid}" "${AUTH[@]}" \
    | python3 -c "import sys,json;print(json.dumps(json.load(sys.stdin)['team_info']['models']))" 2>/dev/null || true)
  [[ -z "$models_json" ]] && models_json='[]'

  # Build the request body with Python to avoid shell-escaping hell.
  # Store token_saver as flat ts_* keys so the dashboard shows each field.
  local body
  body=$(python3 -c "
import json, sys
profile = json.loads(sys.argv[1])
note = sys.argv[2]
# Flat format: ts_enabled, ts_caveman, etc. — dashboard-friendly
meta = {f'ts_{k}': v for k, v in profile.items()}
meta['ts_note'] = note
payload = {
    'key_alias': sys.argv[3],
    'team_id': sys.argv[4],
    'models': json.loads(sys.argv[5]),
    'metadata': meta,
}
print(json.dumps(payload))
" "$sav_cfg" "$note" "$alias" "$tid" "$models_json")

  local resp
  resp=$(curl -sS -X POST "${LITELLM_URL}/key/generate" "${AUTH[@]}" -d "$body")

  local key
  key=$(echo "$resp" | jqf "['key']" 2>/dev/null || true)
  if [[ -z "${key:-}" ]]; then
    echo "  ⚠ key generation failed for ${alias}: ${resp}"
    return
  fi
  echo "  ✔ ${alias}"
  echo "      key       : ${key}"
  echo "      config    : ${sav_cfg}"
  echo "      ${note}"
}

# ── Token saver profiles ──────────────────────────────────────────────
# Content team: RTK + dedupe compression only. No caveman/ponytail — content
# output must sound natural. Saves on token blobs (tool results, long
# contexts) without altering prose style.
CONTENT_PROFILE='{"enabled":true,"caveman":"off","ponytail":"off","rtk":true,"dedupe_tools":true,"min_bytes":500}'

# Programmer team: full savings. RTK + dedupe + Caveman-lite for terse,
# code-friendly output (shorter explanations, more direct responses).
PROGRAMMER_PROFILE='{"enabled":true,"caveman":"lite","ponytail":"off","rtk":true,"dedupe_tools":true,"min_bytes":500}'

echo
echo "▶ generating virtual keys"

# ── Content team keys ────────────────────────────────────────────────
emit_key "content-prod"  content  "$CONTENT_PROFILE"   "RTK + dedupe. No style injection — natural prose preserved."
emit_key "content-dev"   content  "$CONTENT_PROFILE"   "RTK + dedupe. Staging/development content work."

# ── Programmer team keys ─────────────────────────────────────────────
emit_key "programmer-prod" programmer "$PROGRAMMER_PROFILE" "Full savings: RTK + dedupe + Caveman-lite for terse code output."
emit_key "programmer-dev"  programmer "$PROGRAMMER_PROFILE" "Full savings: dev/staging with full compression profile."

# ── 3. Summary ────────────────────────────────────────────────────────
echo
echo "▶ spend snapshot"
curl -sS "${LITELLM_URL}/global/spend/report?group_by=team" "${AUTH[@]}" \
  | python3 -m json.tool 2>/dev/null || echo "  (no spend yet)"

echo
echo "▶ teams created"
curl -sS "${LITELLM_URL}/team/info" "${AUTH[@]}" \
  | python3 -m json.tool 2>/dev/null || echo "  (no teams yet)"

cat <<'EOF'

─────────────────────────────────────────────────────────────────────
Done. Where to look next:

  Usage dashboard : http://localhost:4000/ui  → Usage / Teams / Logs
  Per-team spend  : curl -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
                      "$LITELLM_URL/global/spend/teams"
  Per-key spend   : curl -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
                      "$LITELLM_URL/spend/logs?api_key=<key>"

To verify compression actually ran, grep the container logs for [TokenSaver]:
  docker compose -f docker-compose.tokensaver.yml logs -f litellm | grep TokenSaver

Per-request bypass (for A/B comparison):
  add {"metadata":{"token_saver_bypass":true}} to the request body
─────────────────────────────────────────────────────────────────────
EOF
