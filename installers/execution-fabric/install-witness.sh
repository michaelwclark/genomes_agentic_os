#!/bin/sh
set -eu

apply=false
enable=false
source_root=
release=
install_root=/opt/genomes-agentic-os/execution-fabric-witness
environment_file=/etc/genomes-agentic-os/execution-fabric-witness/witness.env
systemd_root=/etc/systemd/system

while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply=true ;;
    --enable) enable=true ;;
    --source-root) shift; source_root=${1:?missing source root} ;;
    --release) shift; release=${1:?missing release} ;;
    --install-root) shift; install_root=${1:?missing install root} ;;
    --environment-file) shift; environment_file=${1:?missing environment file} ;;
    --systemd-root) shift; systemd_root=${1:?missing systemd root} ;;
    *)
      echo "usage: install-witness.sh [--apply] [--enable] --source-root PATH --release ID [--install-root PATH] [--environment-file PATH] [--systemd-root PATH]" >&2
      exit 64
      ;;
  esac
  shift
done

: "${source_root:?--source-root is required}"
: "${release:?--release is required}"
source_assets="$source_root/deploy/execution-fabric/witness"
[ -f "$source_assets/manifest.yml" ] && [ -x "$source_assets/bin/run.sh" ] || {
  echo "portable witness deployment assets are incomplete" >&2
  exit 66
}

target="$install_root/releases/$release"
current="$install_root/current"
printf '%s\n' "witness release: $target"
printf '%s\n' "operator environment: $environment_file"
if [ "$apply" != true ]; then
  printf '%s\n' "dry-run: no files copied and no container started"
  exit 0
fi

if [ -e "$target" ]; then
  [ -f "$target/manifest.yml" ] || {
    echo "existing witness release is incomplete: $target" >&2
    exit 73
  }
else
  mkdir -p "$target"
  cp -R "$source_assets/." "$target/"
fi
ln -sfn "$target" "$current"

if [ ! -e "$environment_file" ]; then
  mkdir -p "$(dirname "$environment_file")"
  install -m 0600 "$target/witness.env.example" "${environment_file}.example"
fi

mkdir -p "$systemd_root"
for unit in \
  genomes-agentic-os-execution-fabric-witness-monitor.service \
  genomes-agentic-os-execution-fabric-witness-monitor.timer
do
  sed \
    -e "s|@@INSTALL_ROOT@@|$install_root|g" \
    -e "s|@@ENVIRONMENT_FILE@@|$environment_file|g" \
    "$target/systemd/$unit" >"$systemd_root/$unit"
  chmod 0644 "$systemd_root/$unit"
done

if [ "$enable" = true ]; then
  WITNESS_ENV_FILE="$environment_file" \
    "$current/bin/run.sh"
  command -v systemctl >/dev/null 2>&1 || {
    echo "systemctl is required to supervise the witness monitor" >&2
    exit 69
  }
  systemctl daemon-reload
  systemctl enable --now genomes-agentic-os-execution-fabric-witness-monitor.timer
fi
printf '%s\n' "installed inert witness release $release"
