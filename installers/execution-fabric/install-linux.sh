#!/bin/sh
set -eu

usage() {
  echo "usage: install-linux.sh --apply --source-root PATH --release VERSION [--enable]" >&2
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
[ "$(id -u)" -eq 0 ] || {
  echo "Linux installation requires root" >&2
  exit 77
}
[ -d "$source_root/deploy/execution-fabric" ] || usage
[ -d "$source_root/installers/execution-fabric" ] || usage
[ -n "$release" ] || usage

install_root=/opt/genomes-agentic-os/execution-fabric
release_root="$install_root/releases/$release"
config_root=/etc/genomes-agentic-os/execution-fabric
already_installed=false
if [ -e "$release_root" ]; then
  [ -d "$release_root/deploy" ] &&
    [ -d "$release_root/installers/bin" ] || {
    echo "installed release is incomplete: $release_root" >&2
    exit 73
  }
  current_target=$(readlink "$install_root/current" 2>/dev/null || true)
  [ "$current_target" = "$release_root" ] || {
    echo "release is installed but is not current: $release_root" >&2
    exit 73
  }
  already_installed=true
else
  install -d -m 0755 "$release_root/deploy" "$release_root/installers" "$config_root"
  cp -R "$source_root/deploy/execution-fabric/." "$release_root/deploy/"
  cp -R "$source_root/installers/execution-fabric/." "$release_root/installers/"
  find "$release_root/installers/bin" -type f -name '*.sh' -exec chmod 0755 {} +
  chmod 0755 \
    "$release_root/installers/activate-linux.sh" \
    "$release_root/installers/activate-macos.sh"
  ln -sfn "$release_root" "$install_root/current"

  if [ ! -e "$config_root/runtime.env" ]; then
    install -m 0600 "$source_root/deploy/execution-fabric/runtime.env.example" "$config_root/runtime.env.example"
  fi

  for unit in "$source_root"/deploy/execution-fabric/systemd/*; do
    install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
  done
  systemctl daemon-reload
fi

if [ "$enable" = true ]; then
  activator="$release_root/installers/activate-linux.sh"
  [ -x "$activator" ] || {
    echo "installed release has no governed Linux activator: $activator" >&2
    exit 69
  }
  "$activator" --apply
elif [ "$already_installed" = true ]; then
  echo "release already installed and remains inactive unless explicitly activated: $release_root"
fi
