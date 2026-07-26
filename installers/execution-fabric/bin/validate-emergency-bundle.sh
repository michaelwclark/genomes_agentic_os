#!/bin/sh
set -eu

[ "$#" -eq 1 ] || {
  echo "usage: validate-emergency-bundle.sh BUNDLE_DIR" >&2
  exit 64
}
bundle=$1
[ -d "$bundle" ] || {
  echo "bundle directory is missing: $bundle" >&2
  exit 66
}

required_files="
RELEASE
CHECKSUMS.sha256
images.lock.env
execution-fabric-image-lock.json
config/harness/config/execution-fabric.yml
source/deploy/compose.genomesbox.yml
source/deploy/compose.bigmac.yml
source/deploy/emergency-bundle/manifest.yml
source/installers/bin/promote.sh
source/installers/bin/failback.sh
source/installers/bin/materialize-image-lock.sh
"
for relative in $required_files; do
  [ -s "$bundle/$relative" ] || {
    echo "required bundle file is missing or empty: $relative" >&2
    exit 78
  }
done

materialized=$(mktemp "${TMPDIR:-/tmp}/execution-fabric-image-lock.XXXXXX")
trap 'rm -f "$materialized"' EXIT HUP INT TERM
if ! "$bundle/source/installers/bin/materialize-image-lock.sh" \
  "$bundle/execution-fabric-image-lock.json" >"$materialized"
then
  echo "canonical execution fabric image lock is invalid" >&2
  exit 78
fi
cmp -s "$materialized" "$bundle/images.lock.env" || {
  echo "materialized image environment does not match the canonical JSON lock" >&2
  exit 78
}

[ "$(sed -n 's/^secrets_included=//p' "$bundle/RELEASE")" = false ] || {
  echo "bundle claims to include secrets; refusing validation" >&2
  exit 78
}

(
  cd "$bundle"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c CHECKSUMS.sha256
  else
    shasum -a 256 -c CHECKSUMS.sha256
  fi
) >/dev/null

printf 'execution-fabric emergency bundle valid: %s\n' "$bundle"
