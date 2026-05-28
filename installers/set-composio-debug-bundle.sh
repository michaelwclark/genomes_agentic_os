#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  set-composio-debug-bundle.sh [options]
  cat composio-debug-bundle.txt | set-composio-debug-bundle.sh

Options:
  --project-id VALUE
  --org-id VALUE
  --org-member-email VALUE
  --user-id VALUE
  --bundle-file PATH       Parse @project_id: style bundle lines from a file.
  --zshenv PATH            Target shell env file. Defaults to ~/.zshenv.
  --dry-run                Validate and report keys without writing values.
  -h, --help

Accepted bundle format:
  @project_id: pr_...
  @org_id: ok_...
  @org_member_email: user@example.com
  @user_id: ...
EOF
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

quote_zsh() {
  local value="$1"
  printf "'%s'" "${value//\'/\'\\\'\'}"
}

parse_bundle_line() {
  local line key value
  line="$(trim "$1")"
  [[ -z "$line" || "$line" == \#* ]] && return 0
  [[ "$line" == *:* ]] || return 0

  key="$(trim "${line%%:*}")"
  value="$(trim "${line#*:}")"

  case "$key" in
    @project_id|project_id) COMPOSIO_DEBUG_PROJECT_ID="$value" ;;
    @org_id|org_id) COMPOSIO_DEBUG_ORG_ID="$value" ;;
    @org_member_email|org_member_email) COMPOSIO_DEBUG_ORG_MEMBER_EMAIL="$value" ;;
    @user_id|user_id) COMPOSIO_DEBUG_USER_ID="$value" ;;
  esac
}

parse_bundle_file() {
  local file="$1"
  while IFS= read -r line || [[ -n "$line" ]]; do
    parse_bundle_line "$line"
  done < "$file"
}

COMPOSIO_DEBUG_PROJECT_ID="${COMPOSIO_DEBUG_PROJECT_ID:-}"
COMPOSIO_DEBUG_ORG_ID="${COMPOSIO_DEBUG_ORG_ID:-}"
COMPOSIO_DEBUG_ORG_MEMBER_EMAIL="${COMPOSIO_DEBUG_ORG_MEMBER_EMAIL:-}"
COMPOSIO_DEBUG_USER_ID="${COMPOSIO_DEBUG_USER_ID:-}"
TARGET_ZSHENV="${ZSHENV:-$HOME/.zshenv}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      COMPOSIO_DEBUG_PROJECT_ID="${2:-}"
      shift 2
      ;;
    --org-id)
      COMPOSIO_DEBUG_ORG_ID="${2:-}"
      shift 2
      ;;
    --org-member-email)
      COMPOSIO_DEBUG_ORG_MEMBER_EMAIL="${2:-}"
      shift 2
      ;;
    --user-id)
      COMPOSIO_DEBUG_USER_ID="${2:-}"
      shift 2
      ;;
    --bundle-file)
      parse_bundle_file "${2:-}"
      shift 2
      ;;
    --zshenv)
      TARGET_ZSHENV="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -t 0 ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    parse_bundle_line "$line"
  done
fi

missing=()
[[ -n "$COMPOSIO_DEBUG_PROJECT_ID" ]] || missing+=("COMPOSIO_DEBUG_PROJECT_ID")
[[ -n "$COMPOSIO_DEBUG_ORG_ID" ]] || missing+=("COMPOSIO_DEBUG_ORG_ID")
[[ -n "$COMPOSIO_DEBUG_ORG_MEMBER_EMAIL" ]] || missing+=("COMPOSIO_DEBUG_ORG_MEMBER_EMAIL")
[[ -n "$COMPOSIO_DEBUG_USER_ID" ]] || missing+=("COMPOSIO_DEBUG_USER_ID")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "missing required values: ${missing[*]}" >&2
  exit 2
fi

keys=(
  COMPOSIO_DEBUG_PROJECT_ID
  COMPOSIO_DEBUG_ORG_ID
  COMPOSIO_DEBUG_ORG_MEMBER_EMAIL
  COMPOSIO_DEBUG_USER_ID
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "would append keys to $TARGET_ZSHENV: ${keys[*]}"
  exit 0
fi

{
  printf '\n# added via genomes_agentic_os composio debug bundle on %s\n' "$(date +%F)"
  printf 'export COMPOSIO_DEBUG_PROJECT_ID=%s\n' "$(quote_zsh "$COMPOSIO_DEBUG_PROJECT_ID")"
  printf 'export COMPOSIO_DEBUG_ORG_ID=%s\n' "$(quote_zsh "$COMPOSIO_DEBUG_ORG_ID")"
  printf 'export COMPOSIO_DEBUG_ORG_MEMBER_EMAIL=%s\n' "$(quote_zsh "$COMPOSIO_DEBUG_ORG_MEMBER_EMAIL")"
  printf 'export COMPOSIO_DEBUG_USER_ID=%s\n' "$(quote_zsh "$COMPOSIO_DEBUG_USER_ID")"
} >> "$TARGET_ZSHENV"

echo "appended keys to $TARGET_ZSHENV: ${keys[*]}"
