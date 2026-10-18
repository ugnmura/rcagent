#!/usr/bin/env bash
# Part B (table name textbench10, per the request of 2026-10-18T15:32Z): ten files part_{000..009} (~10B rows, 00:00-05:00 UTC) at extractor b51daa1, no
# index (one file's index already needed more than 64 GB of RAM; ten won't fit in 128 GB, not tried).
#SBATCH --job-name=hpc-B
#SBATCH --partition=devel
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=00:59:00
#SBATCH --output=$HPCWORK/hpc-b51daa1/results/%x-%j.out

source $HPCWORK/hpc-b51daa1/src/common.sh
cd "$EXT"

win() {  # $1 label, $2 start HH:MM
  local end
  end=$(date -u -d "2025-09-23T$2:00Z + 1 minute" +%H:%M)
  printf '{"label": "%s", "tool": "search_logs", "args": {"log_table": "textbench10", "text": "error", "start": "2025-09-23T%s:00", "end": "2025-09-23T%s:00", "timezone": "UTC", "limit": 20}, "runs": 3, "guard": true}' "$1" "$2" "$end"
}

cat > "$OUT/B.json" <<JSON
[
  {"label": "B1", "tool": "inspect_source", "args": {"source": "$PART10"}},
  {"label": "B2", "tool": "setup_log_table", "args": {"name": "textbench10", "source": "$PART10", "build_search_index": false}},
  {"label": "B3", "tool": "survey", "args": {"log_table": "textbench10"}, "guard": true},
  $(win B4@00:10 00:10),
  $(win B4@02:30 02:30),
  $(win B4@04:50 04:50),
  {"label": "B5", "tool": "count_logs", "args": {"log_tables": ["textbench10"], "text": "error", "group_by": ["service"], "start": "2025-09-23T02:30:00", "end": "2025-09-23T02:35:00", "timezone": "UTC"}, "runs": 3, "guard": true},
  {"label": "B6", "tool": "count_logs", "args": {"log_tables": ["textbench10"], "group_by": ["service", "level"]}, "guard": true}
]
JSON
$PY -m json.tool "$OUT/B.json" > /dev/null
$DRIVE --steps "$OUT/B.json" --out "$OUT/B.jsonl" || echo "driver B exited $?" | tee -a "$OUT/meta.txt"
echo done > "$OUT/status.txt"
