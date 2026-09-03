#!/usr/bin/env bash
set -euo pipefail

project_dir="${HOME}/hksr_database"
config_file="${XDG_CONFIG_HOME:-${HOME}/.config}/hksr/rds.dsn"

if [[ ! -s "${config_file}" ]]; then
  echo "Missing ${config_file}; run deploy/configure-rds-dsn.sh first" >&2
  exit 2
fi

IFS= read -r HKSR_POSTGRES_DSN < "${config_file}"
export HKSR_POSTGRES_DSN
cd "${project_dir}"

.venv/bin/python -m app.cli cloud-migrate --allow-mutation
.venv/bin/python -m app.cli cloud-import-sqlite \
  --batch-id m6b-real-initial-20260903 \
  --allow-mutation \
  --output data/m6b/runs/real-import-first.json
.venv/bin/python -m app.cli cloud-import-sqlite \
  --batch-id m6b-real-initial-20260903 \
  --allow-mutation \
  --output data/m6b/runs/real-import-second.json
.venv/bin/python -m app.cli cloud-audit \
  --output data/m6b/runs/final-database-audit.json

unset HKSR_POSTGRES_DSN
echo "Cloud migration and final database audit completed."
