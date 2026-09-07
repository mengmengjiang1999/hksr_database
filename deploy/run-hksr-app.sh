#!/usr/bin/env bash
set -euo pipefail

project_dir=${HKSR_PROJECT_DIR:-/home/ecs-user/hksr_database}
backend_file=${HKSR_BACKEND_FILE:-${HOME}/.config/hksr/read-backend}
rds_file=${HKSR_RDS_FILE:-${HOME}/.config/hksr/rds.dsn}

backend=sqlite
if [[ -f "$backend_file" ]]; then
    IFS= read -r backend < "$backend_file"
fi
if [[ "$backend" != "sqlite" && "$backend" != "postgres" ]]; then
    echo "read backend must be sqlite or postgres" >&2
    exit 2
fi

export HKSR_READ_BACKEND=$backend
export HKSR_M9_ENTITY_QA_ENABLED=1
unset HKSR_MODEL_PROVIDER HKSR_MODEL_API_KEY

if [[ "$backend" == "postgres" ]]; then
    if [[ ! -r "$rds_file" ]]; then
        echo "protected PostgreSQL configuration is unavailable" >&2
        exit 2
    fi
    rds_mode=$(stat -c '%a' "$rds_file")
    if [[ "$rds_mode" != "600" && "$rds_mode" != "400" ]]; then
        echo "protected PostgreSQL configuration permissions must be 0600 or 0400" >&2
        exit 2
    fi
    IFS= read -r HKSR_POSTGRES_DSN < "$rds_file"
    export HKSR_POSTGRES_DSN
fi

cd "$project_dir"
exec .venv/bin/python -m app.cli serve --host 127.0.0.1 --port 8000
