#!/usr/bin/env bash
# Run on c23ms instead of devel: devel (1 node up, shared) would not start it before ~21:42 UTC; the user asked to run C now.
# C records the role answers; no timing in C is compared with A or B.
# Part C: one devel job per live role session. The job starts SereneDB, registers textbench10
# (part_{000..009}, no index) through the extractor, writes "ready" and then keeps the database up.
# The claude -p session itself runs on the Mac; its MCP server (serenedb-extractor at b51daa1) runs
# inside this job over stdio: ssh rwth -> src/via_srun.sh <jobid> <port> -> srun --overlap -> src/serve.sh.
#SBATCH --job-name=hpc-C23
#SBATCH --partition=c23ms
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=00:59:00
#SBATCH --output=$HPCWORK/hpc-b51daa1/results/%x-%j.out

source $HPCWORK/hpc-b51daa1/src/common.sh
cd "$EXT"
cat > "$OUT/C_setup.json" <<JSON
[{"label": "C:setup", "tool": "setup_log_table", "args": {"name": "textbench10", "source": "$PART10", "build_search_index": false}}]
JSON
$DRIVE --steps "$OUT/C_setup.json" --out "$OUT/C_setup.jsonl"
echo "$PORT" > "$OUT/ready"
sleep 3500
