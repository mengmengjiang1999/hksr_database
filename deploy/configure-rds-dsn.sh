#!/usr/bin/env bash
set -euo pipefail

config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/hksr"
config_file="${config_dir}/rds.dsn"

umask 077
mkdir -p "${config_dir}"
read -r -s -p "Paste the complete PostgreSQL DSN: " dsn
echo

case "${dsn}" in
  postgresql://*|postgres://*) ;;
  *)
    echo "The value must start with postgresql:// or postgres://" >&2
    exit 2
    ;;
esac

printf '%s\n' "${dsn}" > "${config_file}"
chmod 600 "${config_file}"
unset dsn
echo "RDS DSN saved with mode 600 at ${config_file}"
