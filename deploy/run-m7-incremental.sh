#!/usr/bin/env bash
set -euo pipefail

project_dir=${HKSR_PROJECT_DIR:-/home/ecs-user/hksr_database}
database_path=${HKSR_DATABASE_PATH:-data/database/hksr.sqlite3}
report_dir=${HKSR_M7_REPORT_DIR:-data/m7/runs}
account_uid=${HKSR_M7_ACCOUNT_UID:?HKSR_M7_ACCOUNT_UID is required}
run_stamp=$(date -u +%Y%m%d%H%M%S)
rds_file=${XDG_CONFIG_HOME:-${HOME}/.config}/hksr/rds.dsn

if [[ ! -s "$rds_file" ]]; then
  echo "Missing private RDS configuration" >&2
  exit 2
fi
IFS= read -r HKSR_POSTGRES_DSN < "$rds_file"
export HKSR_POSTGRES_DSN

cd "$project_dir"
mkdir -p "$report_dir"
.venv/bin/python -m app.cli cloud-migrate --allow-mutation \
  > "$report_dir/rds-migrations-$run_stamp.json"

.venv/bin/python -m app.cli --database "$database_path" m7-discover \
  --uid "$account_uid" \
  --output "$report_dir/discovery-$run_stamp.json"
.venv/bin/python -m app.cli --database "$database_path" m7-fetch \
  --output "$report_dir/fetch-$run_stamp.json"
.venv/bin/python -m app.cli --database "$database_path" m7-wiki-discover \
  --output "$report_dir/wiki-discovery-$run_stamp.json"
.venv/bin/python -m app.cli --database "$database_path" m7-wiki-fetch \
  --output "$report_dir/wiki-fetch-$run_stamp.json"

refresh_start=$(.venv/bin/python -c '
import sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
r=c.execute("select terminal from wiki_refresh_checkpoints where catalog_key=?",("game_catalog:17",)).fetchone()
print(1 if r is None or r[0] else 0)
')
refresh_args=()
if test "$refresh_start" -eq 1; then
  refresh_args+=(--start-new-cycle)
fi
.venv/bin/python -m app.cli --database "$database_path" m7-wiki-refresh \
  "${refresh_args[@]}" --output "$report_dir/wiki-refresh-$run_stamp.json"
.venv/bin/python -m app.cli --database "$database_path" parse
.venv/bin/python -m app.cli --database "$database_path" initialize
.venv/bin/python -m app.cli --database "$database_path" cloud-import-sqlite \
  --batch-id "m7-real-incremental-$run_stamp" \
  --allow-mutation \
  --output "$report_dir/rds-$run_stamp.json"
.venv/bin/python -m app.cli --database "$database_path" m7-report \
  --output "$report_dir/completion-$run_stamp.json"
unset HKSR_POSTGRES_DSN
