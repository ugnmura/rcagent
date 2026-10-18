#!/usr/bin/env bash
# Part A extra (follow-up of 2026-10-18T16:18Z): exact no-index whole-file numbers for the break-even.
# Fresh setup_log_table tb (no index), then one run each, in this order:
#   1. plain SQL, no extractor (psql): substring  ILIKE '%error%'
#   2. plain SQL, no extractor (psql): whole word ~* '\merror\M', stopped at 15 min (statement_timeout)
#   (3, extractor run_sql, was measured once in job 5120974 and is not repeated here)
# Rerun of 1-2 only: in job 5120974 they ran as `psql -f <path>`, a path the container cannot see,
# so psql exited before any query. Now the SQL goes in on stdin.
#SBATCH --job-name=hpc-Axb
#SBATCH --partition=devel
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=00:59:00
#SBATCH --output=$HPCWORK/hpc-b51daa1/results/%x-%j.out

source $HPCWORK/hpc-b51daa1/src/common.sh
cd "$EXT"
cat > "$OUT/Ax_setup.json" <<JSON
[{"label": "Ax:setup", "tool": "setup_log_table", "args": {"name": "tb", "source": "$PART000", "build_search_index": false}}]
JSON
$DRIVE --steps "$OUT/Ax_setup.json" --out "$OUT/Ax.jsonl"

timed_psql() {  # $1 label, $2 file with SQL
  local t0 t1
  t0=$(date +%s.%N)
  psql_ < "$2" > "$OUT/$1.txt" 2>&1 || echo "psql exited $?" >> "$OUT/$1.txt"
  t1=$(date +%s.%N)
  echo "$1 wall_s $(awk -v a="$t0" -v b="$t1" 'BEGIN{printf "%.3f", b-a}')" | tee -a "$OUT/$1.txt"
}
printf '%s\n' '\timing on' "SELECT count(*) FROM extractor.lt_tb WHERE \"Body\" ILIKE '%error%';" > "$OUT/Ax1_psql_substring.sql"
timed_psql Ax1_psql_substring "$OUT/Ax1_psql_substring.sql"
printf '%s\n' "SET statement_timeout = '15min';" '\timing on' "SELECT count(*) FROM extractor.lt_tb WHERE \"Body\" ~* '\\merror\\M';" > "$OUT/Ax2_psql_wholeword.sql"
timed_psql Ax2_psql_wholeword "$OUT/Ax2_psql_wholeword.sql"

echo done > "$OUT/status.txt"
