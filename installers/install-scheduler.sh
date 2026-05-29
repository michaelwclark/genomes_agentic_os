#!/usr/bin/env bash
# Install (or remove) the always-on driver for the Agentic OS runtime supervisor.
#
# The OS has a full runtime surface but no daemon — this installs an external
# scheduler that calls `agentic-os runtime supervise --apply` on a cadence
# (the headline "make it tick" fix, backlog F-001). macOS uses a launchd agent;
# other platforms get a crontab line.
#
# Dry-run by default: it prints exactly what it would install and changes
# nothing. Pass --apply to install, --uninstall to remove.
set -euo pipefail

LABEL="com.genome.agentic-os.supervisor"
ROOT="${HOME}/agentic_os"
INTERVAL_MINUTES=15
AGENTIC_OS=""
MODE="dry-run"
ACTION="install"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/../templates/runtime/supervisor.launchd.plist.template"

usage() {
  cat <<'EOF'
Usage:
  install-scheduler.sh [options]

Installs an external scheduler that runs `agentic-os runtime supervise --apply`
on a cadence. macOS -> launchd agent; other platforms -> crontab line.

Options:
  --root PATH              Installed OS root. Default: ~/agentic_os
  --interval-minutes N     Tick cadence in minutes. Default: 15
  --agentic-os PATH        Path to the agentic-os binary. Default: autodetect
                           (command -v agentic-os, else repo .venv/bin/agentic-os)
  --label NAME             launchd label / cron marker. Default: com.genome.agentic-os.supervisor
  --apply                  Actually install (default is a dry-run preview)
  --uninstall              Remove a previously installed scheduler
  -h, --help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --interval-minutes) INTERVAL_MINUTES="$2"; shift 2 ;;
    --agentic-os) AGENTIC_OS="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --apply) MODE="apply"; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

# Resolve the binary if not given.
if [ -z "$AGENTIC_OS" ]; then
  if command -v agentic-os >/dev/null 2>&1; then
    AGENTIC_OS="$(command -v agentic-os)"
  elif [ -x "${SCRIPT_DIR}/../.venv/bin/agentic-os" ]; then
    AGENTIC_OS="$(cd "${SCRIPT_DIR}/.." && pwd)/.venv/bin/agentic-os"
  else
    echo "error: could not find agentic-os; pass --agentic-os PATH" >&2; exit 2
  fi
fi

ROOT="${ROOT/#\~/$HOME}"
INTERVAL_SECONDS=$(( INTERVAL_MINUTES * 60 ))
LOG_DIR="${ROOT}/shared_factory/06-runs-and-logs"
OUT_LOG="${LOG_DIR}/supervisor.out.log"
ERR_LOG="${LOG_DIR}/supervisor.err.log"
OS="$(uname -s)"

echo "Agentic OS supervisor scheduler"
echo "  action:   ${ACTION}"
echo "  mode:     ${MODE}"
echo "  platform: ${OS}"
echo "  label:    ${LABEL}"
echo "  binary:   ${AGENTIC_OS}"
echo "  root:     ${ROOT}"
echo "  cadence:  every ${INTERVAL_MINUTES} min (${INTERVAL_SECONDS}s)"
echo "  logs:     ${OUT_LOG}"
echo

if [ "$OS" = "Darwin" ]; then
  PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
  if [ "$ACTION" = "uninstall" ]; then
    echo "Would unload and remove: ${PLIST}"
    if [ "$MODE" = "apply" ]; then
      launchctl unload "$PLIST" 2>/dev/null || true
      rm -f "$PLIST"
      echo "uninstalled."
    fi
    exit 0
  fi
  [ -f "$TEMPLATE" ] || { echo "error: template not found: $TEMPLATE" >&2; exit 2; }
  RENDERED="$(sed \
    -e "s|{{LABEL}}|${LABEL}|g" \
    -e "s|{{AGENTIC_OS}}|${AGENTIC_OS}|g" \
    -e "s|{{ROOT}}|${ROOT}|g" \
    -e "s|{{INTERVAL_SECONDS}}|${INTERVAL_SECONDS}|g" \
    -e "s|{{OUT_LOG}}|${OUT_LOG}|g" \
    -e "s|{{ERR_LOG}}|${ERR_LOG}|g" \
    "$TEMPLATE")"
  echo "----- launchd agent (${PLIST}) -----"
  echo "$RENDERED"
  echo "------------------------------------"
  if [ "$MODE" = "apply" ]; then
    mkdir -p "$(dirname "$PLIST")" "$LOG_DIR"
    printf '%s\n' "$RENDERED" > "$PLIST"
    launchctl unload "$PLIST" 2>/dev/null || true
    launchctl load -w "$PLIST"
    echo "installed and loaded. Tail logs: tail -f ${OUT_LOG}"
  else
    echo "(dry-run) re-run with --apply to install."
  fi
else
  CRON_CMD="${AGENTIC_OS} runtime supervise --root ${ROOT} --apply >> ${OUT_LOG} 2>> ${ERR_LOG}"
  CRON_LINE="*/${INTERVAL_MINUTES} * * * * ${CRON_CMD}  # ${LABEL}"
  if [ "$ACTION" = "uninstall" ]; then
    echo "Would remove crontab line marked: # ${LABEL}"
    if [ "$MODE" = "apply" ]; then
      ( crontab -l 2>/dev/null | grep -v "# ${LABEL}\$" || true ) | crontab -
      echo "uninstalled."
    fi
    exit 0
  fi
  echo "----- crontab line -----"
  echo "$CRON_LINE"
  echo "------------------------"
  if [ "$MODE" = "apply" ]; then
    mkdir -p "$LOG_DIR"
    ( crontab -l 2>/dev/null | grep -v "# ${LABEL}\$" || true; echo "$CRON_LINE" ) | crontab -
    echo "installed. Verify: crontab -l | grep ${LABEL}"
  else
    echo "(dry-run) re-run with --apply to install."
  fi
fi
