#!/usr/bin/env bash
# harness-emit-trace.sh <agent>
# Reads a Stop hook JSON payload from stdin and emits a non-blocking AGENT_TRACE
# to the local losmon-memory MCP HTTP endpoint. Failures are logged and never
# block hook completion.
set -uo pipefail

MCP_URL="${LOSMON_MEMORY_MCP_URL:-http://127.0.0.1:3155/mcp}"
LOG_DIR="${HOME}/.local/state/harness"
LOG_FILE="${LOG_DIR}/emit-trace.log"
AGENT="${1:-unknown}"
HOST="$(hostname -s 2>/dev/null || echo "unknown")"
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

mkdir -p "${LOG_DIR}" 2>/dev/null || true
PAYLOAD="$(cat 2>/dev/null || true)"

SESSION_ID="$(printf '%s' "${PAYLOAD}" | jq -r '.session_id // .sessionId // empty' 2>/dev/null || true)"
TRANSCRIPT="$(printf '%s' "${PAYLOAD}" | jq -r '.transcript_path // .transcriptPath // empty' 2>/dev/null || true)"
CWD="$(printf '%s' "${PAYLOAD}" | jq -r '.cwd // empty' 2>/dev/null || true)"

SESSION_ID="${SESSION_ID:-unknown}"
TRANSCRIPT="${TRANSCRIPT:-}"
CWD="${CWD:-unknown}"

N_TURNS=0
if [[ -n "${TRANSCRIPT}" && "${TRANSCRIPT}" == *.jsonl && -f "${TRANSCRIPT}" ]]; then
  N_TURNS="$(wc -l < "${TRANSCRIPT}" 2>/dev/null | tr -d ' ' || echo 0)"
fi

CONTENT="${HOST}/${AGENT} session ${SESSION_ID} ended ${TS}: cwd=${CWD}, turns=${N_TURNS}, transcript=${TRANSCRIPT:-none}"
PERSONA="${AGENT}-${HOST}"
RPC_BODY="$(jq -n \
  --arg content "${CONTENT}" \
  --arg persona "${PERSONA}" \
  '{
    jsonrpc: "2.0",
    id: 1,
    method: "tools/call",
    params: {
      name: "memory_write",
      arguments: {
        content: $content,
        kindHint: "AGENT_TRACE",
        persona: $persona
      }
    }
  }' 2>/dev/null || true)"

if [[ -n "${RPC_BODY}" ]]; then
  (
    tmpfile="$(mktemp 2>/dev/null || echo "/tmp/harness-trace-$$")"
    http_status="$(curl -s -m 60 -o "${tmpfile}" -w "%{http_code}" \
      -X POST "${MCP_URL}" \
      -H "Content-Type: application/json" \
      -d "${RPC_BODY}" 2>/dev/null || echo "0")"
    resp_len="$(wc -c < "${tmpfile}" 2>/dev/null | tr -d ' ' || echo 0)"
    rm -f "${tmpfile}" 2>/dev/null || true
    done_ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    printf '%s agent=%s session=%s async_status=%s resp_bytes=%s content="%s"\n' \
      "${done_ts}" "${AGENT}" "${SESSION_ID}" "${http_status}" "${resp_len}" "${CONTENT}" \
      >> "${LOG_FILE}" 2>/dev/null || true
  ) &
  disown 2>/dev/null || true
else
  printf '%s agent=%s session=%s async_status=jq_error resp_bytes=0 content="%s"\n' \
    "${TS}" "${AGENT}" "${SESSION_ID}" "${CONTENT}" \
    >> "${LOG_FILE}" 2>/dev/null || true
fi

printf '%s agent=%s session=%s dispatched content="%s"\n' \
  "${TS}" "${AGENT}" "${SESSION_ID}" "${CONTENT}" \
  >> "${LOG_FILE}" 2>/dev/null || true

printf '{"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":""}}\n'
exit 0

