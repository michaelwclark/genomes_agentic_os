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
[ ! -e "$release_root" ] || {
  echo "release already installed: $release_root" >&2
  exit 73
}

install -d -m 0755 "$release_root/deploy" "$release_root/installers" "$config_root"
cp -R "$source_root/deploy/execution-fabric/." "$release_root/deploy/"
cp -R "$source_root/installers/execution-fabric/." "$release_root/installers/"
find "$release_root/installers/bin" -type f -name '*.sh' -exec chmod 0755 {} +
ln -sfn "$release_root" "$install_root/current"

if [ ! -e "$config_root/runtime.env" ]; then
  install -m 0600 "$source_root/deploy/execution-fabric/runtime.env.example" "$config_root/runtime.env.example"
fi

for unit in "$source_root"/deploy/execution-fabric/systemd/*; do
  install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
systemctl daemon-reload

if [ "$enable" = true ]; then
  systemctl enable --now genomes-agentic-os-execution-fabric-primary.service
  systemctl enable --now genomes-agentic-os-execution-fabric-scheduler.service
  systemctl enable --now genomes-agentic-os-execution-fabric-observer.timer
  systemctl enable --now genomes-agentic-os-execution-fabric-backup.timer
  systemctl enable --now genomes-agentic-os-execution-fabric-artifact-replication.timer
  systemctl enable --now genomes-agentic-os-execution-fabric-candidate-reporter-health.timer
fi
