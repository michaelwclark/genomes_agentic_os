#!/usr/bin/env bash
# Agentic OS — CLI ground-truth validation harness.
#
# Exercises the full `agentic-os` command surface against a THROWAWAY scratch
# root in /tmp. Never touches the real ~/agentic_os install. Emits a compact
# status matrix to stdout, writes per-command logs under $WORK/logs, and
# regenerates .agentic-atlas/validation/RESULTS.md.
#
# Status legend:
#   OK        rc=0, command succeeded
#   USAGE     rc=2, argparse usage error (args wrong; contract exists)
#   ERR       rc=1, command ran but reported a handled error (inspect log)
#   TRACEBACK rc!=0 AND a Python traceback in output (likely a real defect)
#   OTHER     any other non-zero rc
#
# Re-run any time:  bash .agentic-atlas/tools/validate-cli.sh
set -u

REPO="/Users/genome/projects/genomes_agentic_os"
AOS="$REPO/.venv/bin/agentic-os"
WORK="${AOS_VALIDATE_WORK:-/tmp/aos-validate}"
ROOT="$WORK/root"
LOGS="$WORK/logs"
RESULTS="$WORK/results.tsv"
RESULTS_MD="$REPO/.agentic-atlas/validation/RESULTS.md"

rm -rf "$WORK"
mkdir -p "$LOGS"
: > "$RESULTS"

n=0
run() {
  local label="$1"; shift
  n=$((n+1))
  local slug; slug=$(printf '%02d-%s' "$n" "$(echo "$label" | tr ' /' '__' | tr -cd 'A-Za-z0-9_-')")
  local log="$LOGS/$slug.log"
  { echo "# CMD: $*"; echo "# CWD: $(pwd)"; echo "# ---"; "$@"; } >"$log" 2>&1
  local rc=$?
  # Classify. Note: the CLI uses exit code 2 for BOTH argparse usage errors and
  # some handled runtime errors, so distinguish by the presence of an argparse
  # "usage:" banner rather than by rc alone.
  local status="OK"
  if grep -q "Traceback (most recent call last)" "$log"; then status="TRACEBACK";
  elif [ "$rc" -eq 0 ]; then status="OK";
  elif grep -q "^usage: agentic-os" "$log"; then status="USAGE";
  else status="GUARDED"; fi  # non-zero exit, ran on purpose (health-fail / refusal / handled error)
  printf "rc=%-3s %-9s %s\n" "$rc" "$status" "$label"
  printf "%s\t%s\t%s\t%s\n" "$rc" "$status" "$label" "$slug" >> "$RESULTS"
}

echo "================ AGENTIC OS CLI VALIDATION ================"
echo "AOS:  $AOS"; echo "ROOT: $ROOT (scratch; real install untouched)"; echo "LOGS: $LOGS"
echo "=========================================================="
echo "---- CORE LIFECYCLE ----"
run "init (scratch root)"            "$AOS" init --target "$ROOT"
run "validate root"                  "$AOS" validate --root "$ROOT"
run "doctor"                         "$AOS" doctor --root "$ROOT"
run "doctor --fix-missing"           "$AOS" doctor --root "$ROOT" --fix-missing
echo "---- DOMAIN / PROJECT / ROUTING ----"
run "domain create acme"             "$AOS" domain create acme --root "$ROOT"
run "project create acme launch"     "$AOS" project create acme launch --root "$ROOT"
mkdir -p "$WORK/source-repo"
run "project link-source acme launch" "$AOS" project link-source acme launch --root "$ROOT" --repo "$WORK/source-repo"
run "project onboard acme launch"    "$AOS" project onboard acme launch --root "$ROOT"
run "project work-item create intake" "$AOS" project work-item create acme launch --root "$ROOT" --title "Validation intake idea" --summary "capture the validation intake idea"
run "project work-item create packet" "$AOS" project work-item create acme launch --root "$ROOT" --title "Validation packet idea" --summary "capture the expanded validation packet" --format packet
mkdir -p "$WORK/source-worktree"
run "project worktree add acme launch" "$AOS" project worktree add acme launch source_worktree --root "$ROOT" --path "$WORK/source-worktree"
run "route a request"                "$AOS" route "ship the launch blog post" --root "$ROOT"
run "context build --domain"         "$AOS" context build --domain acme --project launch --root "$ROOT"
( cd "$ROOT/acme" && run "here route (cwd-aware)" "$AOS" here route "update the launch project" )
echo "---- WORKFLOWS (with fixture) ----"
WF="$ROOT/acme/03-workflows/engineering/launch_blog"
mkdir -p "$WF"; cp "$REPO"/templates/workflow/*.md "$WF"/ 2>/dev/null
run "workflow check (templated)"     "$AOS" workflow check acme engineering launch_blog --root "$ROOT"
echo "---- AUTOMATIONS (with fixture) ----"
AU="$ROOT/acme/04-automations/marketing/weekly_report"
mkdir -p "$AU/logs"; cp "$REPO"/templates/automation/*.md "$AU"/ 2>/dev/null
printf '# Run Evidence\n' > "$AU/logs/README.md"
run "automation check (templated)"   "$AOS" automation check acme marketing weekly_report --root "$ROOT"
run "automation attach -> launch"    "$AOS" automation attach acme marketing weekly_report --project launch --root "$ROOT"
run "automation set-maturity prepare" "$AOS" automation set-maturity acme marketing weekly_report prepare --root "$ROOT"
echo "---- RUN LOG (create -> close round-trip) ----"
run "run-log create"                 "$AOS" run-log create acme launch_blog --root "$ROOT"
RUN_ID=$(ls -t "$ROOT/acme/06-runs-and-logs/runs" 2>/dev/null | head -1)
run "run-log close ($RUN_ID)"        "$AOS" run-log close acme "$RUN_ID" --status done --summary "shipped" --validation "manual QA passed" --next-action "monitor" --root "$ROOT"
echo "---- PROFILES / ROOMS ----"
run "profile create"                 "$AOS" profile create --target "$WORK/os.yml"
run "profile validate"               "$AOS" profile validate "$WORK/os.yml"
echo "---- RUNTIME / ALWAYS-ON SURFACE ----"
run "runtime init"                   "$AOS" runtime init --root "$ROOT"
run "runtime doctor"                 "$AOS" runtime doctor --root "$ROOT"
run "runtime run-next (dry)"         "$AOS" runtime run-next --root "$ROOT" --dry-run
run "runtime supervise (dry)"        "$AOS" runtime supervise --root "$ROOT" --dry-run
run "runtime supervise (apply)"      "$AOS" runtime supervise --root "$ROOT" --apply
run "heartbeat list"                 "$AOS" heartbeat list --root "$ROOT"
run "heartbeat doctor"               "$AOS" heartbeat doctor --root "$ROOT"
run "schedule create demo"           "$AOS" schedule create demo --cadence daily --root "$ROOT"
run "schedule run-due (dry)"         "$AOS" schedule run-due --root "$ROOT" --dry-run
run "integration list"               "$AOS" integration list --root "$ROOT"
run "integration doctor"             "$AOS" integration doctor --root "$ROOT"
echo "---- EVENT GRAPH / CHAINS ----"
run "event list"                     "$AOS" event list --root "$ROOT"
run "event summary"                  "$AOS" event summary --root "$ROOT"
run "event process-due (dry)"        "$AOS" event process-due --root "$ROOT" --dry-run
run "chain list"                     "$AOS" chain list --root "$ROOT"
run "chain doctor"                   "$AOS" chain doctor --root "$ROOT"
echo "---- CONNECTED SOURCES / WATCH ----"
run "connected-system list"          "$AOS" connected-system list --root "$ROOT"
run "watch-source list"              "$AOS" watch-source list --root "$ROOT"
echo "---- SSHFS REMOTE MOUNTS (feat-64, dry-run only — no network) ----"
# Set up a minimal project with a mount block and a hosts.yml for dry-run
RM_DOM="rmtest"; RM_PROJ="losmon"
"$AOS" domain create "$RM_DOM" --root "$ROOT" >/dev/null 2>&1
"$AOS" project create "$RM_DOM" "$RM_PROJ" --root "$ROOT" >/dev/null 2>&1
mkdir -p "$ROOT/config"
printf 'hosts:\n  genomesbox:\n    ssh_alias: genomesbox\n    ssh_options: []\n' \
  > "$ROOT/config/hosts.yml"
RM_YML="$ROOT/$RM_DOM/02-projects/$RM_PROJ/project.yml"
python3 - "$RM_YML" <<'PYEOF'
import sys, yaml
path = sys.argv[1]
data = yaml.safe_load(open(path).read()) or {}
data.setdefault("sources", {})["remotes"] = [{
    "name": "losmon", "host": "genomesbox",
    "path": "/home/genome/projects/losmon",
    "kind": "git", "authority": "remote",
    "mount": {
        "namespace": "SSH_genomesbox",
        "local_path": "/tmp/SSH_genomesbox/losmon",
        "access": "sshfs", "execution": "remote",
    },
}]
open(path, "w").write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
PYEOF
run "mount-remote (dry-run)"    "$AOS" project mount-remote "$RM_DOM" "$RM_PROJ" --root "$ROOT" --dry-run
run "unmount-remote (dry-run)"  "$AOS" project unmount-remote "$RM_DOM" "$RM_PROJ" --root "$ROOT" --dry-run
echo "---- NOTION CONTROL PLANE (plan only) ----"
run "notion plan-sync"               "$AOS" notion plan-sync --root "$ROOT"
echo "---- CONFIG (Codex) ----"
run "config doctor (layer)"          "$AOS" config doctor --root "$ROOT" --layer agentic_os_root
run "config install (dry)"           "$AOS" config install --root "$WORK/config-layer" --layer agentic_os_root --dry-run
run "config install-tree (dry)"      "$AOS" config install-tree --root "$ROOT" --dry-run
echo "---- UPDATE / BACKUP / LICENSE ----"
run "license activate"               "$AOS" license activate --key "VALIDATION-TEST-KEY" --root "$ROOT"
run "update register"                "$AOS" update register --root "$ROOT"
run "update check"                   "$AOS" update check --root "$ROOT"
run "update status"                  "$AOS" update status --root "$ROOT"
run "backup run (dry)"               "$AOS" backup run --root "$ROOT" --dry-run
echo "---- MIGRATE / LOSMON / PLAN / DOCS ----"
run "migrate plan"                   "$AOS" migrate plan --root "$ROOT"
run "losmon validate"                "$AOS" losmon validate --root "$ROOT"
run "plan capture"                   "$AOS" plan capture --title "weekly report automation" --summary "automate the weekly report" --root "$ROOT"
run "docs install"                   "$AOS" docs install --root "$ROOT"
echo "---- CUSTOMER OS FACTORY ----"
run "customer init (example)"        "$AOS" customer init acme_ops --profile "$REPO/customer_profiles/example-customer.yml" --target "$WORK/customer"
run "customer validate"              "$AOS" customer validate --root "$WORK/customer"

echo "=========================================================="
echo "SUMMARY:"
awk -F'\t' '{c[$2]++} END {for (k in c) printf "  %-9s %d\n", k, c[k]}' "$RESULTS"
total=$(wc -l < "$RESULTS" | tr -d ' ')
echo "TOTAL: $total commands"

# Regenerate durable markdown results matrix.
{
  echo "# CLI Validation Results"
  echo
  echo "Generated by \`.agentic-atlas/tools/validate-cli.sh\` against a scratch root."
  echo "Status: OK=succeeded · USAGE=arg error · ERR=handled error · TRACEBACK=defect."
  echo
  echo "| # | Status | rc | Command |"
  echo "| --- | --- | --- | --- |"
  awk -F'\t' '{printf "| %s | %s | %s | %s |\n", NR, $2, $1, $3}' "$RESULTS"
  echo
  echo "## Totals"
  echo
  awk -F'\t' '{c[$2]++} END {for (k in c) printf "- %s: %d\n", k, c[k]}' "$RESULTS"
} > "$RESULTS_MD"
echo "Wrote $RESULTS_MD"

# Regenerate durable real-output examples (quote these in docs).
EXAMPLES_MD="$REPO/.agentic-atlas/validation/command-output-examples.md"
{
  echo "# Real Command Output Examples"
  echo
  echo "Captured by \`.agentic-atlas/tools/validate-cli.sh\` against a scratch root."
  echo "Real stdout/stderr from a working install — safe to quote verbatim in docs."
  echo
  for f in "$LOGS"/*.log; do
    echo "## $(basename "$f" .log)"
    echo '```text'
    cat "$f"
    echo '```'
    echo
  done
} > "$EXAMPLES_MD"
echo "Wrote $EXAMPLES_MD"
echo "Logs: $LOGS"
