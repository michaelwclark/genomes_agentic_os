#!/bin/sh
set -eu

# This package-owned executable is the stable host-worker entrypoint. Operators
# may select the Python interpreter, but do not need to write or maintain a
# wrapper around the shipped execution_fabric_worker module.
python_command=${FABRIC_WORKER_PYTHON:-python3}
python_path=$(command -v "$python_command" 2>/dev/null || true)
[ -n "$python_path" ] && [ -x "$python_path" ] || {
  echo "configured Execution Fabric worker Python is unavailable: $python_command" >&2
  exit 69
}

if [ "${1:-}" = "--preflight" ]; then
  [ "$#" -eq 1 ] || {
    echo "usage: python-worker.sh [--preflight]" >&2
    exit 64
  }
  exec "$python_path" -c \
    "from genomes_agentic_os.execution_fabric_worker import main; assert callable(main)"
fi

exec "$python_path" -m genomes_agentic_os.execution_fabric_worker "$@"
