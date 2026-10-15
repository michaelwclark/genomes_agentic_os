#!/bin/sh
set -eu
umask 077
script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=_lib.sh
# shellcheck disable=SC1091
. "$script_dir/_lib.sh"
fabric_load_runtime
if [ "${FABRIC_RECOVERY_SETS_ENABLED:-0}" != 1 ]; then
  printf '%s\n' '{"status":"disabled","authorityTransferAuthorized":false}'
  exit 0
fi
: "${FABRIC_RECOVERY_SOURCE_HOST:?the exact primary source host is required}"
: "${FABRIC_RECOVERY_LOCAL_STAGING_ROOT:?a private local staging root is required}"
: "${FABRIC_RECOVERY_REPOSITORY:?an independently initialized encrypted repository is required}"
: "${FABRIC_RECOVERY_PASSWORD_FILE:?a protected custodian password-file reference is required}"
recovery_cli=${FABRIC_RECOVERY_AGENTIC_OS_CLI:-agentic-os}
fabric_require_command "$recovery_cli"
exec "$recovery_cli" runtime recovery-set collect-current --root "$FABRIC_OS_ROOT" \
  --source-host "$FABRIC_RECOVERY_SOURCE_HOST" \
  --local-root "$FABRIC_RECOVERY_LOCAL_STAGING_ROOT" \
  --repository "$FABRIC_RECOVERY_REPOSITORY" \
  --password-file "$FABRIC_RECOVERY_PASSWORD_FILE" \
  --restic "${FABRIC_RECOVERY_RESTIC:-restic}" --apply --json
