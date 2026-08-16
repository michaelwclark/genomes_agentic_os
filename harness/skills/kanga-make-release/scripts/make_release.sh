#!/bin/bash
# make_release.sh — deterministic driver for the Kanga develop→main release cut.
#
# Phases (run in order; default is the read-only preflight):
#   preflight  verify each repo is releasable (CI green, ahead-only, pipeline present)
#   cut        create release/<UTC-date> from develop + open PR → main (idempotent)
#   merge      merge-commit the release PR once its checks are green (NEVER squash:
#              semantic-release needs the individual conventional commits on main)
#   watch      wait for the Release workflow on main; report tag/Release + prod gating
#   all        preflight → cut → merge → watch
#
# Production deploys stay gated: deploy.yml only deploys main when dispatched
# (gh workflow run deploy.yml --ref main -f environment=production) or AUTO_DEPLOY_PROD=true.
# This script never dispatches a production deploy unless --prod-dispatch is passed.
set -euo pipefail
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH

ORG=KANGA-BOOKING
# All five repos (KAN-162). Mobile repos participate once their gitflow
# migration + deploy lanes land (KAN-159/152); until then their preflight
# fails, which is the correct readiness signal. Narrow with --repos.
REPOS="kanga-backend kanga-user-web kanga-business-web kanga-user-app kanga-business-app"
PHASE=preflight
PROD_DISPATCH=false
DATE_UTC=$(date -u +%Y-%m-%d)
OUT_DIR=""

usage() { sed -n '2,16p' "$0"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repos) REPOS=$(echo "$2" | tr ',' ' '); shift 2 ;;
    --phase) PHASE="$2"; shift 2 ;;
    --prod-dispatch) PROD_DISPATCH=true; shift ;;
    --output-dir) OUT_DIR="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1"; usage ;;
  esac
done

[ -z "$OUT_DIR" ] && OUT_DIR="$HOME/agentic_os/clarks_consulting/02-projects/kanga/artifacts/releases/$DATE_UTC"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/release-run.log"
say() { echo "$(date -u +%H:%M:%S) $*" | tee -a "$LOG"; }
RC=0

preflight_repo() {
  local r=$1 ok=true
  say "== preflight $ORG/$r"
  local ci
  ci=$(gh run list -R "$ORG/$r" --branch develop --workflow CI --limit 1 --json conclusion --jq '.[0].conclusion' 2>/dev/null || echo none)
  [ "$ci" = "success" ] || { say "  FAIL: latest develop CI conclusion=$ci"; ok=false; }
  local cmp ahead behind
  cmp=$(gh api "repos/$ORG/$r/compare/main...develop" --jq '"\(.ahead_by) \(.behind_by)"')
  ahead=${cmp% *}; behind=${cmp#* }
  say "  main...develop ahead=$ahead behind=$behind"
  [ "$behind" = "0" ] || { say "  FAIL: main has commits missing from develop — reconcile first"; ok=false; }
  [ "$ahead" != "0" ] || say "  NOTE: nothing to release (develop == main)"
  for f in ci.yml deploy.yml release.yml; do
    gh api "repos/$ORG/$r/contents/.github/workflows/$f?ref=develop" --jq '.name' >/dev/null 2>&1 \
      || { say "  FAIL: $f missing on develop"; ok=false; }
  done
  local envs
  envs=$(gh api "repos/$ORG/$r/environments" --jq '[.environments[].name] | join(",")' 2>/dev/null || echo "")
  case "$envs" in *beta*production*|*production*beta*) ;; *) say "  WARN: environments=$envs (want beta+production)";; esac
  local adp
  adp=$(gh api "repos/$ORG/$r/actions/variables/AUTO_DEPLOY_PROD" --jq '.value' 2>/dev/null || echo unset)
  say "  AUTO_DEPLOY_PROD=$adp (false/unset = prod deploys gated to workflow_dispatch)"
  local tags
  tags=$(gh api "repos/$ORG/$r/tags" --jq '.[].name' 2>/dev/null || true)
  echo "$tags" | grep -iE '^v[0-9]+\.[0-9]+\.[0-9]+$' | while read -r t; do
    [ -n "$t" ] || continue
    gh release view "$t" -R "$ORG/$r" >/dev/null 2>&1 \
      || say "  WARN: bare tag $t has no GitHub Release — see KAN-154 normalization before enabling beta prereleases"
  done
  echo "$tags" | grep -vE '^v[0-9]+\.[0-9]+\.[0-9]+(-beta\.[0-9]+)?$' | while read -r t; do
    [ -n "$t" ] || continue
    say "  WARN: non-semver legacy tag '$t' — normalize deliberately (KAN-154/KAN-160 pattern: verify release-less, record SHA, delete)"
  done
  if ! echo "$tags" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
    say "  NOTE: no vX.Y.Z baseline tag — first release starts at v1.0.0 unless a baseline is created first (mobile: tag the store version per KAN-160)"
  fi
  $ok && say "  preflight OK" || { say "  preflight FAILED"; return 1; }
}

cut_repo() {
  local r=$1 br="release/$DATE_UTC"
  say "== cut $ORG/$r $br"
  local head
  head=$(gh api "repos/$ORG/$r/git/ref/heads/develop" --jq '.object.sha')
  if gh api "repos/$ORG/$r/git/ref/heads/$br" >/dev/null 2>&1; then
    say "  branch $br exists — reusing (delete it to re-cut from a newer develop)"
  else
    gh api -X POST "repos/$ORG/$r/git/refs" -f ref="refs/heads/$br" -f sha="$head" --jq '.ref' >>"$LOG"
    say "  cut $br @ ${head:0:9}"
  fi
  local pr
  pr=$(gh pr list -R "$ORG/$r" --head "$br" --base main --state open --json number --jq '.[0].number' 2>/dev/null || echo "")
  if [ -n "$pr" ] && [ "$pr" != "null" ]; then
    say "  release PR #$pr already open"
  else
    gh pr create -R "$ORG/$r" --base main --head "$br" \
      --title "release: promote develop to main ($DATE_UTC)" \
      --body "$(printf 'First-class release cut per docs/RELEASING.md — promotes develop (beta) to main (production channel).\n\n**Merge with a MERGE COMMIT, never squash**: semantic-release on main analyzes the individual conventional commits to compute the version.\n\nProduction deploy remains gated after merge (workflow_dispatch / AUTO_DEPLOY_PROD).\n\nLinear: [KAN-153](https://linear.app/genomes/issue/KAN-153)')" >>"$LOG" 2>&1
    say "  release PR opened: $(gh pr list -R "$ORG/$r" --head "$br" --base main --state open --json number,url --jq '.[0].url')"
  fi
}

merge_repo() {
  local r=$1 br="release/$DATE_UTC"
  say "== merge $ORG/$r"
  local pr
  pr=$(gh pr list -R "$ORG/$r" --head "$br" --base main --state open --json number --jq '.[0].number' 2>/dev/null || echo "")
  [ -n "$pr" ] && [ "$pr" != "null" ] || { say "  no open release PR for $br — run cut first"; return 1; }
  local tries=0
  while [ $tries -lt 40 ]; do
    local checks
    checks=$(gh pr checks "$pr" -R "$ORG/$r" 2>/dev/null || true)
    if echo "$checks" | grep -qE '\bfail\b'; then say "  FAIL: PR #$pr has failing checks"; return 1; fi
    if [ -z "$checks" ] || ! echo "$checks" | grep -qE '\b(pending|queued|in_progress)\b'; then break; fi
    tries=$((tries+1)); sleep 15
  done
  # Merge commit REQUIRED (see header). --admin not used; branch protection wins.
  gh pr merge "$pr" -R "$ORG/$r" --merge >>"$LOG" 2>&1 \
    && say "  merged release PR #$pr into main (merge commit)" \
    || { say "  FAIL: merge of PR #$pr refused — resolve manually"; return 1; }
}

watch_repo() {
  local r=$1
  say "== watch $ORG/$r Release on main"
  local tries=0 run_id="" concl=""
  while [ $tries -lt 60 ]; do
    run_id=$(gh run list -R "$ORG/$r" --branch main --workflow Release --limit 1 --json databaseId,status,conclusion --jq '.[0] | "\(.databaseId) \(.status) \(.conclusion)"' 2>/dev/null || echo "")
    if [ -n "$run_id" ]; then
      local status=${run_id#* }; status=${status%% *}
      concl=${run_id##* }
      [ "${run_id% *}" != "" ] && [ "$status" = "completed" ] && break
    fi
    tries=$((tries+1)); sleep 15
  done
  say "  Release run: ${run_id:-none-found} (conclusion=$concl)"
  say "  latest tag: $(gh api "repos/$ORG/$r/tags" --jq '.[0].name' 2>/dev/null || echo none)"
  say "  latest GitHub Release: $(gh release list -R "$ORG/$r" --limit 1 2>/dev/null | head -1 || echo none)"
  local dep
  dep=$(gh run list -R "$ORG/$r" --branch main --workflow Deploy --limit 1 --json conclusion --jq '.[0].conclusion' 2>/dev/null || echo none)
  say "  Deploy on main: $dep (production deploy executes only via dispatch or AUTO_DEPLOY_PROD=true)"
  if [ "$PROD_DISPATCH" = "true" ]; then
    say "  dispatching PRODUCTION deploy (explicit --prod-dispatch)"
    # --ref main is mandatory: a bare dispatch runs the repo's DEFAULT branch
    # (develop on all five repos) and would build develop's tree into production.
    gh workflow run deploy.yml -R "$ORG/$r" --ref main -f environment=production >>"$LOG" 2>&1 || say "  FAIL: dispatch refused"
  fi
}

for r in $REPOS; do
  case "$PHASE" in
    preflight) preflight_repo "$r" || RC=1 ;;
    cut)       cut_repo "$r" || RC=1 ;;
    merge)     merge_repo "$r" || RC=1 ;;
    watch)     watch_repo "$r" || RC=1 ;;
    all)       { preflight_repo "$r" && cut_repo "$r" && merge_repo "$r" && watch_repo "$r"; } || RC=1 ;;
    *) echo "unknown phase: $PHASE"; usage ;;
  esac
done
say "done phase=$PHASE rc=$RC — receipts in $OUT_DIR"
exit $RC
