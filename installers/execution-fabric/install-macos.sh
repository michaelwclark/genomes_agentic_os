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
already_installed=false
if [ -e "$release_root" ]; then
  [ -d "$release_root/deploy" ] &&
    [ -d "$release_root/installers/bin" ] || {
    echo "installed release is incomplete: $release_root" >&2
    exit 73
  }
  current_target=$(readlink "$base/current" 2>/dev/null || true)
  [ "$current_target" = "$release_root" ] || {
    echo "release is installed but is not current: $release_root" >&2
    exit 73
  }
  already_installed=true
else
  install -d -m 0755 "$release_root/deploy" "$release_root/installers" "$state_dir/logs" "$launch_agents"
  cp -R "$source_root/deploy/execution-fabric/." "$release_root/deploy/"
  cp -R "$source_root/installers/execution-fabric/." "$release_root/installers/"
  find "$release_root/installers/bin" -type f -name '*.sh' -exec chmod 0755 {} +
  chmod 0755 \
    "$release_root/installers/activate-linux.sh" \
    "$release_root/installers/activate-macos.sh"
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
fi

if [ "$enable" = true ]; then
  activator="$release_root/installers/activate-macos.sh"
  [ -x "$activator" ] || {
    echo "installed release has no governed macOS activator: $activator" >&2
    exit 69
  }
  "$activator" --apply
elif [ "$already_installed" = true ]; then
  echo "release already installed and remains inactive unless explicitly activated: $release_root"
fi
