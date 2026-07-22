#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
qa_root="${AGENTIC_OS_QA_ROOT:-${HOME}/agentic_os_qa}"
receipt_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      qa_root="$2"
      shift 2
      ;;
    --receipt-dir)
      receipt_dir="$2"
      shift 2
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

qa_root="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve())' "$qa_root")"
case "$qa_root" in
  "/"|"$HOME"|"/Users/genome/agentic_os")
    echo "refusing unsafe or live Agentic OS QA root: $qa_root" >&2
    exit 2
    ;;
esac

scratch="$(mktemp -d "${TMPDIR:-/tmp}/agentic-os-qa.XXXXXX")"
trap 'rm -rf "$scratch"' EXIT
fresh_root="$scratch/fresh"
sentinel="$qa_root/.qa-operator-owned"

run_init_validate() {
  local target="$1"
  uv run agentic-os init --target "$target"
  uv run agentic-os validate --root "$target"
}

cd "$repo_root"
run_init_validate "$fresh_root"

mkdir -p "$qa_root"
if [[ ! -f "$sentinel" ]]; then
  printf 'operator-owned QA sentinel\n' > "$sentinel"
fi
sentinel_before="$(shasum -a 256 "$sentinel" | awk '{print $1}')"

run_init_validate "$qa_root"
run_init_validate "$qa_root"

sentinel_after="$(shasum -a 256 "$sentinel" | awk '{print $1}')"
if [[ "$sentinel_before" != "$sentinel_after" ]]; then
  echo "operator-owned sentinel changed during reinstall" >&2
  exit 1
fi

if [[ -n "$receipt_dir" ]]; then
  mkdir -p "$receipt_dir"
  receipt="$receipt_dir/reinstall-agentic-os.json"
  python3 - "$receipt" "$qa_root" "$sentinel_after" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
path.write_text(
    json.dumps(
        {
            "schema": "genomes-agentic-os-reinstall-qa/v1",
            "ok": True,
            "qa_root": sys.argv[2],
            "passes": ["fresh_install", "secondary_install", "secondary_reinstall"],
            "sentinel_sha256": sys.argv[3],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
  echo "$receipt"
fi

echo "fresh install and two secondary-root install passes validated"
