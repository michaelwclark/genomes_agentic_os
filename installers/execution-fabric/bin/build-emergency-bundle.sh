#!/bin/sh
set -eu

usage() {
  echo "usage: build-emergency-bundle.sh --source-root PATH --os-root PATH --image-lock PATH --output PATH --release VERSION" >&2
  exit 64
}

source_root=
os_root=
image_lock=
output=
release=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source-root) shift; [ "$#" -gt 0 ] || usage; source_root=$1 ;;
    --os-root) shift; [ "$#" -gt 0 ] || usage; os_root=$1 ;;
    --image-lock) shift; [ "$#" -gt 0 ] || usage; image_lock=$1 ;;
    --output) shift; [ "$#" -gt 0 ] || usage; output=$1 ;;
    --release) shift; [ "$#" -gt 0 ] || usage; release=$1 ;;
    *) usage ;;
  esac
  shift
done

[ -d "$source_root/deploy/execution-fabric" ] || usage
[ -d "$source_root/installers/execution-fabric" ] || usage
[ -d "$os_root/harness" ] || usage
[ -s "$image_lock" ] || usage
[ -n "$output" ] || usage
[ -n "$release" ] || usage
[ ! -e "$output" ] || {
  echo "output already exists; refusing to overwrite: $output" >&2
  exit 73
}

script_dir=$(CDPATH="" cd -- "$(dirname -- "$0")" && pwd)
staging=$(mktemp -d "${TMPDIR:-/tmp}/execution-fabric-bundle.XXXXXX")
trap 'rm -rf "$staging"' EXIT HUP INT TERM
bundle="$staging/execution-fabric-emergency-$release"
mkdir -p "$bundle/source" "$bundle/config"

cp -R "$source_root/deploy/execution-fabric" "$bundle/source/deploy"
cp -R "$source_root/installers/execution-fabric" "$bundle/source/installers"
cp "$image_lock" "$bundle/execution-fabric-image-lock.json"
"$script_dir/materialize-image-lock.sh" \
  "$bundle/execution-fabric-image-lock.json" >"$bundle/images.lock.env"

copy_config() {
  relative=$1
  if [ -f "$os_root/$relative" ]; then
    destination="$bundle/config/$relative"
    mkdir -p "$(dirname "$destination")"
    cp "$os_root/$relative" "$destination"
  fi
}

copy_config harness/config/execution-fabric.yml
copy_config config/hosts.yml
copy_config harness/config/hosts.yml
copy_config harness/registries/hosts-routing.yml
copy_config harness/registries/alerts.yml

[ -f "$bundle/config/harness/config/execution-fabric.yml" ] || {
  echo "canonical execution-fabric config is missing" >&2
  exit 78
}
if [ ! -f "$bundle/config/config/hosts.yml" ] && [ ! -f "$bundle/config/harness/config/hosts.yml" ]; then
  echo "canonical host config is missing" >&2
  exit 78
fi

{
  printf 'release=%s\n' "$release"
  printf 'built_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'source_commit=%s\n' "$(git -C "$source_root" rev-parse HEAD)"
  printf 'secrets_included=false\n'
} >"$bundle/RELEASE"

checksums=$(mktemp "$staging/CHECKSUMS.XXXXXX")
(
  cd "$bundle"
  find . -type f ! -name CHECKSUMS.sha256 -print | LC_ALL=C sort |
    while IFS= read -r file; do
      if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file"
      else
        shasum -a 256 "$file"
      fi
    done >"$checksums"
)
mv "$checksums" "$bundle/CHECKSUMS.sha256"

"$script_dir/validate-emergency-bundle.sh" "$bundle"
mkdir -p "$(dirname "$output")"
mv "$bundle" "$output"
trap - EXIT HUP INT TERM
rm -rf "$staging"
printf '%s\n' "$output"
