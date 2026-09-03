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

# Do not overlap the three-item M7A resume. Its report is the hand-off gate.
for _ in $(seq 1 90); do
  test -s "$report_dir/m7a-fetch-resume.json" && break
  sleep 10
done
test -s "$report_dir/m7a-fetch-resume.json"
.venv/bin/python -c '
import json
p=json.load(open("data/m7/runs/m7a-fetch-resume.json"))
assert p.get("attempted") == 3 and p.get("persisted") == 3 and p.get("failed") == 0
'

cycle=0
while true; do
  cycle=$((cycle + 1))
  stamp=$(date -u +%Y%m%d%H%M%S)
  used=$(.venv/bin/python -c '
import datetime, sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
d=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
r=c.execute("select request_count from daily_request_budgets where budget_date=?",(d,)).fetchone()
print(r[0] if r else 0)
')
  if test "$daily_budget" -eq 0; then
    remaining=-1
  else
    remaining=$((daily_budget - used))
    test "$remaining" -gt 0 || break
  fi

  pending=$(.venv/bin/python -c '
import sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
print(c.execute("select count(*) from sources where provider=? and official_status=? and status in (?,?)",("miyoushe","verified","discovered","error")).fetchone()[0])
')
  terminal=$(.venv/bin/python -c '
import os, sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
r=c.execute("select terminal from account_checkpoints where account_uid=?",(os.environ["HKSR_M7_ACCOUNT_UID"],)).fetchone()
print(r[0] if r else 0)
')
  if test "$pending" -eq 0 && test "$terminal" -eq 1; then
    break
  fi

  if test "$pending" -lt 10 && test "$terminal" -eq 0; then
    test "$remaining" -eq -1 || test "$remaining" -ge 2 || break
    discovery_report="$report_dir/m7b-discovery-${cycle}-${stamp}.json"
    .venv/bin/python -m app.cli --database "$database_path" m7-discover \
      --uid "$HKSR_M7_ACCOUNT_UID" --daily-budget "$daily_budget" \
      --output "$discovery_report"
    .venv/bin/python -c '
import json, sys
p=json.load(open(sys.argv[1]))
assert p.get("pages", 0) <= 2 and p.get("requests", 0) <= 2
assert p.get("retries") == 0 and p.get("unverified") == 0
' "$discovery_report"
  fi

  pending=$(.venv/bin/python -c '
import sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
print(c.execute("select count(*) from sources where provider=? and official_status=? and status in (?,?)",("miyoushe","verified","discovered","error")).fetchone()[0])
')
  test "$pending" -gt 0 || continue
  limit=10
  test "$pending" -ge "$limit" || limit=$pending
  used=$(.venv/bin/python -c '
import datetime, sqlite3
c=sqlite3.connect("data/database/hksr.sqlite3")
d=datetime.datetime.now(datetime.timezone.utc).date().isoformat()
r=c.execute("select request_count from daily_request_budgets where budget_date=?",(d,)).fetchone()
print(r[0] if r else 0)
')
  if test "$daily_budget" -eq 0; then
    remaining=-1
  else
    remaining=$((daily_budget - used))
    test "$remaining" -gt 0 || break
    test "$limit" -le "$remaining" || limit=$remaining
  fi

  fetch_report="$report_dir/m7b-fetch-${cycle}-${stamp}.json"
  .venv/bin/python -m app.cli --database "$database_path" m7-fetch \
    --limit "$limit" --daily-budget "$daily_budget" \
    --output "$fetch_report"
  .venv/bin/python -c '
import json, sys
p=json.load(open(sys.argv[1]))
assert p.get("attempted", 0) <= 10
assert p.get("failed") == 0
assert p.get("persisted", 0) + p.get("skipped", 0) == p.get("attempted")
assert p.get("retries") == 0
' "$fetch_report"
  .venv/bin/python -m app.cli --database "$database_path" parse \
    > "$report_dir/m7b-parse-${cycle}-${stamp}.json"
  .venv/bin/python -m app.cli --database "$database_path" m7-report \
    --output "$report_dir/m7b-state-${cycle}-${stamp}.json"
done

.venv/bin/python -m app.cli --database "$database_path" initialize \
  > "$report_dir/m7b-final-index.json"
.venv/bin/python -m app.cli --database "$database_path" m7-report \
  --output "$report_dir/m7b-overnight-final.json"
