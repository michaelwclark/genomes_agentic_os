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
config/harness/config/execution-fabric.yml
source/deploy/compose.genomesbox.yml
source/deploy/compose.bigmac.yml
source/deploy/emergency-bundle/manifest.yml
source/installers/bin/promote.sh
source/installers/bin/failback.sh
"
for relative in $required_files; do
  [ -s "$bundle/$relative" ] || {
    echo "required bundle file is missing or empty: $relative" >&2
    exit 78
  }
done

if grep -E '(^|[=:[:space:]])[^#[:space:]]+:latest([[:space:]]|$)' "$bundle/images.lock.env" >/dev/null; then
  echo "latest image tags are prohibited" >&2
  exit 78
fi

for variable in \
  FABRIC_CONTROL_PLANE_IMAGE \
  FABRIC_POSTGRES_IMAGE \
  FABRIC_VALKEY_IMAGE \
  FABRIC_MINIO_IMAGE \
  FABRIC_MINIO_CLIENT_IMAGE
do
  value=$(sed -n "s/^${variable}=//p" "$bundle/images.lock.env")
  printf '%s\n' "$value" | grep -Eq '^.+@sha256:[a-f0-9]{64}$' || {
    echo "$variable must be locked to an immutable sha256 digest" >&2
    exit 78
  }
  printf '%s\n' "$value" | grep -Eq '@sha256:0{64}$' && {
    echo "$variable uses the prohibited all-zero placeholder digest" >&2
    exit 78
  }
done

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
