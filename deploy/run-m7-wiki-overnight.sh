#!/usr/bin/env bash
set -euo pipefail

set -a
. "$HOME/.config/hksr/m7.env"
set +a

project_dir=${HKSR_PROJECT_DIR:-/home/ecs-user/hksr_database}
database_path=${HKSR_DATABASE_PATH:-data/database/hksr.sqlite3}
report_dir=${HKSR_M7_REPORT_DIR:-data/m7/runs}
daily_budget=${HKSR_M7_DAILY_BUDGET:-60}

case "$daily_budget" in
  ''|*[!0-9]*)
    echo "HKSR_M7_DAILY_BUDGET must be a non-negative integer (0 means unlimited)" >&2
    exit 2
    ;;
esac

cd "$project_dir"
mkdir -p "$report_dir"

# Keep the two upstream collectors sequential. Wiki waits for the account inventory service.
while systemctl --user is-active --quiet hksr-m7b-overnight.service; do
  sleep 30
done

terminal=$(.venv/bin/python -c '
import os, sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
r=c.execute("select terminal from account_checkpoints where account_uid=?",(os.environ["HKSR_M7_ACCOUNT_UID"],)).fetchone()
print(r[0] if r else 0)
')
account_pending=$(.venv/bin/python -c '
import sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
print(c.execute("select count(*) from sources where provider=? and status in (?,?)",("miyoushe","discovered","error")).fetchone()[0])
')
test "$terminal" -eq 1
test "$account_pending" -eq 0

.venv/bin/python -m app.cli --database "$database_path" m7-wiki-discover \
  --output "$report_dir/wiki-catalog-refresh.json"

cycle=0
while true; do
  pending=$(.venv/bin/python -c '
import sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
print(c.execute("select count(*) from sources where provider=? and official_status=? and status in (?,?)",("mihoyo_wiki","verified","discovered","error")).fetchone()[0])
')
  test "$pending" -gt 0 || break
  cycle=$((cycle + 1))
  stamp=$(date -u +%Y%m%d%H%M%S)
  limit=10
  test "$pending" -ge "$limit" || limit=$pending
  fetch_report="$report_dir/wiki-fetch-${cycle}-${stamp}.json"

  .venv/bin/python -m app.cli --database "$database_path" m7-wiki-fetch \
    --limit "$limit" --daily-budget "$daily_budget" --output "$fetch_report"
  .venv/bin/python -c '
import json, sys
p=json.load(open(sys.argv[1]))
assert p.get("attempted", 0) <= 10
assert p.get("failed") == 0
assert p.get("persisted", 0) + p.get("skipped", 0) == p.get("attempted")
assert p.get("retries") == 0
' "$fetch_report"
  parse_report="$report_dir/wiki-parse-${cycle}-${stamp}.json"
  .venv/bin/python -m app.cli --database "$database_path" parse --limit "$limit" \
    > "$parse_report"
  .venv/bin/python -c '
import json, sys
fetch=json.load(open(sys.argv[1]))
parsed=json.load(open(sys.argv[2]))
assert parsed.get("failed") == 0
assert parsed.get("attempted") == fetch.get("persisted")
' "$fetch_report" "$parse_report"
done

.venv/bin/python -m app.cli --database "$database_path" initialize \
  > "$report_dir/wiki-final-index.json"
.venv/bin/python -m app.cli --database "$database_path" m7-report \
  --output "$report_dir/wiki-overnight-final.json"
