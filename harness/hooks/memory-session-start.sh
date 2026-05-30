#!/usr/bin/env bash
# SessionStart hook: remind the agent that losmon-memory is the durable
# cross-session memory plane. Emits hookSpecificOutput.additionalContext JSON.
set -eu

cwd_basename="$(basename "${CODEX_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$PWD}}")"

read -r -d '' MSG <<EOF || true
[losmon-memory hook] The losmon-memory MCP is available (tools: memory_read, memory_write, memory_link, memory_forget). It is the durable cross-session memory plane backed by MemPalace + CoCoIndex.

Discipline for this session (cwd: ${cwd_basename}):
- Before non-trivial debugging or reconnaissance, call memory_read with a focused query to surface prior decisions, incidents, and rules of thumb. Do not re-derive state from scratch.
- At the end of substantive work, call memory_write to capture what was learned: surprises, non-obvious decisions, environment quirks. Use the four-type taxonomy (user / feedback / project / reference) in your write phrasing.
- Skip memory_write for trivial lookups, ephemeral debugging, or anything already obvious from the code.
EOF

jq -n --arg ctx "$MSG" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'

