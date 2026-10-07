#!/bin/sh
# Agent hub: wire this agent/app into Langfuse (own project, keys, evals, ratings, LLM gateway).
# curl -fsSL {{BASE}}/install.sh | LF_TOKEN=<token> sh -s -- <agent-name> [target-dir]
set -eu
BASE={{BASE}}
NAME=$(printf %s "${1:-${LF_NAME:-$(basename "$PWD")}}" | tr -cd 'A-Za-z0-9._-')
DIR=${2:-${LF_DIR:-.}}
ENV="$DIR/.env"
[ -n "${LF_TOKEN:-}" ] || { echo "ERROR: set LF_TOKEN (the enroll token)"; exit 1; }
command -v curl >/dev/null || { echo "ERROR: curl is required"; exit 1; }
mkdir -p "$DIR"
TMP=$(mktemp)
CODE=$(curl -sS -o "$TMP" -w '%{http_code}' -X POST "$BASE/v1/enroll?format=env" \
  -H "Authorization: Bearer $LF_TOKEN" -H 'Content-Type: application/json' --data "{\"name\":\"$NAME\"}")
if [ "$CODE" != 200 ]; then echo "ERROR: enroll HTTP $CODE: $(cat "$TMP")"; rm -f "$TMP"; exit 1; fi

# merge into .env: back up, drop old values of the keys we set, append fresh ones
KEYS=$(grep -v '^#' "$TMP" | cut -d= -f1 | paste -sd'|' -)
if [ -f "$ENV" ]; then
  cp "$ENV" "$ENV.pre-langfuse.bak"
  grep -Ev "^(export )?($KEYS)=|^# Langfuse \+ LLM gateway" "$ENV.pre-langfuse.bak" > "$ENV" || true
fi
cat "$TMP" >> "$ENV"; rm -f "$TMP"; chmod 600 "$ENV" 2>/dev/null || true
if git -C "$DIR" rev-parse --git-dir >/dev/null 2>&1; then
  for p in .env .env.pre-langfuse.bak; do
    git -C "$DIR" check-ignore -q "$p" || echo "$p" >> "$DIR/.gitignore"
  done
fi
get() { grep "^$1=" "$ENV" | tail -1 | cut -d= -f2-; }
HOST=$(get LANGFUSE_HOST); PK=$(get LANGFUSE_PUBLIC_KEY); SK=$(get LANGFUSE_SECRET_KEY); PID=$(get LANGFUSE_PROJECT_ID)

# smoke 1: direct trace through the Langfuse API (proves keys + network)
ID="smoke-$(date +%s)-$$"; TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
S1=$(curl -sS -o /dev/null -w '%{http_code}' -u "$PK:$SK" -H 'Content-Type: application/json' "$HOST/api/public/ingestion" \
  --data "{\"batch\":[{\"id\":\"$ID-e\",\"type\":\"trace-create\",\"timestamp\":\"$TS\",\"body\":{\"id\":\"$ID\",\"name\":\"hub-smoke\",\"tags\":[\"smoke\",\"$NAME\"],\"input\":\"What is the capital of France?\",\"output\":\"Paris is the capital of France.\"}}]}")
# smoke 2: one LLM call through the gateway (proves the LLM key; it is traced into this project)
S2=$(curl -sS -o /dev/null -w '%{http_code}' "$(get LLM_BASE_URL)/chat/completions" -H "Authorization: Bearer $(get LLM_API_KEY)" \
  -H 'Content-Type: application/json' --data "{\"model\":\"$(get LLM_MODEL)\",\"max_tokens\":256,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with: hub connected\"}]}")

echo "Langfuse project : $NAME ($HOST/project/$PID)"
echo "Keys written to  : $ENV (gitignored; values not shown)"
echo "Smoke trace      : HTTP $S1 -> $HOST/project/$PID/traces/$ID"
echo "Gateway LLM call : HTTP $S2 (appears under Traces in ~1 min)"
echo "Next             : read $BASE/ and wire your code (section 2)."
[ "$S1" = 207 ] || [ "$S1" = 200 ] || exit 2
