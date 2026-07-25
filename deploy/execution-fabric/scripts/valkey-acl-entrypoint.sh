#!/bin/sh
set -eu

application_password_file=${FABRIC_VALKEY_PASSWORD_FILE:-/run/secrets/valkey-app-password}
health_password_file=${FABRIC_VALKEY_HEALTH_PASSWORD_FILE:-/run/secrets/valkey-health-password}
for secret_file in "$application_password_file" "$health_password_file"; do
  [ -s "$secret_file" ] || {
    echo "missing Valkey credential secret" >&2
    exit 78
  }
done

application_password=$(cat "$application_password_file")
health_password=$(cat "$health_password_file")
for password in "$application_password" "$health_password"; do
  case "$password" in
    ''|*[!A-Za-z0-9._~-]*)
      echo "Valkey passwords must be URL-safe tokens" >&2
      exit 78
      ;;
  esac
done

acl_dir=${FABRIC_VALKEY_ACL_DIR:-/run/valkey}
acl_file="$acl_dir/users.acl"
mkdir -p "$acl_dir"
umask 077
temporary="${acl_file}.tmp.$$"
{
  printf 'user default off\n'
  printf 'user fabric on >%s ~* &* +@all\n' "$application_password"
  printf 'user health on >%s resetkeys resetchannels -@all +ping\n' "$health_password"
} >"$temporary"
mv "$temporary" "$acl_file"
unset application_password health_password

exec "$@" --aclfile "$acl_file"
