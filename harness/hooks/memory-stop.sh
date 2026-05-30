#!/usr/bin/env bash
# Stop hook: remind the agent to durably capture useful learnings before
# yielding back to the user. Emits hookSpecificOutput.additionalContext JSON.
set -eu

read -r -d '' MSG <<'EOF' || true
[losmon-memory hook] Before you finish this turn: if you learned something durable this session that a future agent would benefit from, call memory_write to capture it. Good candidates are non-obvious decisions, environment quirks, user preferences, new project facts, and reference pointers. Skip if the turn was trivial or the content is already covered by an existing memory.
EOF

jq -n --arg ctx "$MSG" '{hookSpecificOutput: {hookEventName: "Stop", additionalContext: $ctx}}'

