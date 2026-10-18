#!/usr/bin/env bash
# Part A: one file (part_000, ~1B rows) at extractor b51daa1, including the no-index vs
# with-index break-even. A1-A5 run before any index exists; if A4 timed out, the same scan is timed
# with plain SQL in psql (still no index); then A6-A10 build, use and drop the search index.
#SBATCH --job-name=hpc-A
#SBATCH --partition=devel
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=00:59:00
#SBATCH --output=$HPCWORK/hpc-b51daa1/results/%x-%j.out

source $HPCWORK/hpc-b51daa1/src/common.sh
cd "$EXT"

cat > "$OUT/A_noindex.json" <<JSON
[
  {"label": "A1", "tool": "setup_log_table", "args": {"name": "tb", "source": "$PART000", "build_search_index": false}},
  {"label": "A2", "tool": "survey", "args": {"log_table": "tb"}, "guard": true},
  {"label": "A3", "tool": "search_logs", "args": {"log_table": "tb", "text": "error", "start": "2025-09-23T00:10:00", "end": "2025-09-23T00:11:00", "timezone": "UTC", "limit": 20}, "runs": 3, "guard": true},
  {"label": "A4", "tool": "search_logs", "args": {"log_table": "tb", "text": "error", "fuzzy": false, "limit": 20}, "runs": 3, "slow_s": 120, "guard": true},
  {"label": "A5", "tool": "count_logs", "args": {"log_tables": ["tb"], "text": "error", "group_by": ["service"]}, "guard": true}
]
JSON
$DRIVE --steps "$OUT/A_noindex.json" --out "$OUT/A.jsonl" || echo "driver A1-A5 exited $?" | tee -a "$OUT/meta.txt"

# psql fallback for the break-even: only if A4 hit the timeout (no index exists yet).
if grep '"label": "A4' "$OUT/A.jsonl" | grep -q 'TIMEOUT after'; then
  psql_ -c '\d extractor.lt_tb' > "$OUT/A4_psql_columns.txt" 2>&1 || true
  COL=$(psql_ -Atc "SELECT column_name FROM information_schema.columns WHERE table_schema='extractor' AND table_name='lt_tb' AND lower(column_name) IN ('message','msg','body','text','log','line') ORDER BY ordinal_position LIMIT 1")
  SQL="SELECT count(*) FROM extractor.lt_tb WHERE \"$COL\" ILIKE '%error%';"
  echo "$SQL" > "$OUT/A4_psql.sql"
  t0=$(date +%s.%N)
  { echo '\timing on'; echo "$SQL"; } | psql_ > "$OUT/A4_psql.txt" 2>&1 || echo "psql exited $?" >> "$OUT/A4_psql.txt"
  t1=$(date +%s.%N)
  echo "A4_psql wall_s $(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.3f", b-a}')" | tee -a "$OUT/A4_psql.txt"
fi

cat > "$OUT/A_index.json" <<'JSON'
[
  {"label": "A6:dry_run", "tool": "create_index", "args": {"log_table": "tb", "kind": "search", "dry_run": true}},
  {"label": "A6:build", "tool": "create_index", "args": {"log_table": "tb", "kind": "search"}},
  {"label": "A7", "tool": "search_logs", "args": {"log_table": "tb", "text": "error", "fuzzy": false, "limit": 20}, "runs": 3, "guard": true},
  {"label": "A8", "tool": "count_logs", "args": {"log_tables": ["tb"], "text": "error", "group_by": ["service"]}, "guard": true},
  {"label": "A9", "tool": "search_logs", "args": {"log_table": "tb", "text": "error", "start": "2025-09-23T00:10:00", "end": "2025-09-23T00:11:00", "timezone": "UTC", "limit": 20}, "runs": 3, "guard": true},
  {"label": "A10", "tool": "drop_index", "args": {"log_table": "tb", "kind": "search"}}
]
JSON
$DRIVE --steps "$OUT/A_index.json" --out "$OUT/A.jsonl" || echo "driver A6-A10 exited $?" | tee -a "$OUT/meta.txt"
echo done > "$OUT/status.txt"
