#!/usr/bin/env bash
set -euo pipefail

project_dir=${HKSR_PROJECT_DIR:-/home/ecs-user/hksr_database}
database_path=${HKSR_DATABASE_PATH:-data/database/hksr.sqlite3}
report_dir=${HKSR_M7_REPORT_DIR:-data/m7/runs}

cd "$project_dir"
mkdir -p "$report_dir"
set -a
. "$HOME/.config/hksr/m7.env"
set +a

.venv/bin/python -m app.cli --database "$database_path" m7-fetch \
  --limit 3 \
  --output "$report_dir/m7a-fetch-resume.json"
.venv/bin/python -m app.cli --database "$database_path" parse \
  > "$report_dir/m7a-parse.json"
.venv/bin/python -m app.cli --database "$database_path" initialize \
  > "$report_dir/m7a-index.json"
.venv/bin/python -m app.cli --database "$database_path" m7-report \
  --output "$report_dir/m7a-after-resume.json"
