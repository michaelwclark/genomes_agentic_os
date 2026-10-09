#!/bin/sh
set -eu
umask 077
script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
# shellcheck disable=SC1091
. "$script_dir/_lib.sh"
fabric_load_runtime

# Preserve PostgreSQL-only daily backup until complete daily recovery is qualified.
if [ "${FABRIC_RECOVERY_SETS_ENABLED:-0}" != 1 ]; then
  exec "$script_dir/backup-health.sh"
fi
: "${FABRIC_RECOVERY_DAILY_PLAN_FILE:?a qualified daily recovery plan is required}"
recovery_cli=${FABRIC_RECOVERY_AGENTIC_OS_CLI:-agentic-os}
fabric_require_command "$recovery_cli"
exec "$recovery_cli" runtime recovery-set daily \
  --root "$FABRIC_OS_ROOT" \
  --daily-plan "$FABRIC_RECOVERY_DAILY_PLAN_FILE" --apply --json
