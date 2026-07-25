#!/bin/sh
set -eu

usage() {
  echo "usage: install-macos.sh --apply --source-root PATH --release VERSION [--enable]" >&2
  exit 64
}

apply=false
enable=false
source_root=
release=
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --enable) enable=true ;;
    --source-root) shift; [ "$#" -gt 0 ] || usage; source_root=$1 ;;
    --release) shift; [ "$#" -gt 0 ] || usage; release=$1 ;;
    *) usage ;;
  esac
  shift
done

[ "$apply" = true ] || usage
[ "$(uname -s)" = Darwin ] || {
  echo "macOS installation must run on Darwin" >&2
  exit 77
}
[ -d "$source_root/deploy/execution-fabric" ] || usage
[ -d "$source_root/installers/execution-fabric" ] || usage
[ -n "$release" ] || usage

base="$HOME/Library/Application Support/GenomesAgenticOS/execution-fabric"
release_root="$base/releases/$release"
state_dir="$base/state"
runtime_env="$base/runtime.env"
launch_agents="$HOME/Library/LaunchAgents"
[ ! -e "$release_root" ] || {
  echo "release already installed: $release_root" >&2
  exit 73
}

install -d -m 0755 "$release_root/deploy" "$release_root/installers" "$state_dir/logs" "$launch_agents"
cp -R "$source_root/deploy/execution-fabric/." "$release_root/deploy/"
cp -R "$source_root/installers/execution-fabric/." "$release_root/installers/"
find "$release_root/installers/bin" -type f -name '*.sh' -exec chmod 0755 {} +
ln -sfn "$release_root" "$base/current"

if [ ! -e "$runtime_env" ]; then
  install -m 0600 "$source_root/deploy/execution-fabric/runtime.env.example" "$base/runtime.env.example"
fi

for template in "$source_root"/deploy/execution-fabric/launchd/*.plist; do
  destination="$launch_agents/$(basename "$template")"
  sed \
    -e "s|__INSTALL_ROOT__|$base/current/installers|g" \
    -e "s|__RUNTIME_ENV__|$runtime_env|g" \
    -e "s|__STATE_DIR__|$state_dir|g" \
    "$template" >"${destination}.tmp"
  plutil -lint "${destination}.tmp" >/dev/null
  mv "${destination}.tmp" "$destination"
done

if [ "$enable" = true ]; then
  for label in standby worker observer watchdog alarm-dispatcher artifact-replication candidate-reporter-health scheduler-role; do
    plist="$launch_agents/com.genomes.agentic-os.execution-fabric.$label.plist"
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/$(id -u)" "$plist"
  done
fi
