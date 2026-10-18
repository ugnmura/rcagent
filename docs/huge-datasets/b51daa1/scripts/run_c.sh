#!/usr/bin/env bash
# Part C: the three live role sessions, run on the Mac (claude is not installed on the cluster).
# The MCP server is the extractor at b51daa1 inside Slurm job $1 (SereneDB on port $2), reached over stdio:
#   ssh rwth -> via_srun.sh <job> <port> -> srun --overlap -> serve.sh (sets the three SERENEDB_ vars there).
# Same flags as the plan, plus --allowedTools "mcp__serenedb-extractor" (as in the Mac-side run.sh; without
# it headless -p cannot call the tools). Usage: run_c.sh <jobid> <port> <outdir>
set -u
JOB=$1; PORT=$2; OUT=$3
mkdir -p "$OUT"; cd "$OUT"
cat > extractor.json <<JSON
{"mcpServers": {"serenedb-extractor": {"command": "ssh", "args": ["-T", "-o", "BatchMode=yes", "rwth", "$HPCWORK/hpc-b51daa1/src/via_srun.sh $JOB $PORT"]}}}
JSON
FLAGS=(--model claude-opus-5-5 --strict-mcp-config --mcp-config extractor.json --setting-sources ""
       --allowedTools "mcp__serenedb-extractor" --output-format stream-json --verbose --max-turns 40)
run() { # n role question
  printf '%s\n' "/mcp__serenedb-extractor__$2 $3" > "C$1.prompt.txt"
  date -u +%FT%TZ > "C$1.start"
  claude -p "/mcp__serenedb-extractor__$2 $3" "${FLAGS[@]}" > "C$1.jsonl" 2> "C$1.err"
  echo "exit $? end $(date -u +%FT%TZ)" > "C$1.end"
}
run 1 engineer "On the TextBench logs (table textbench10), what is the most frequent error between 02:30 and 02:35 UTC on 2025-09-23, which service logs it, and what happens right before one occurrence? Show the evidence." &
run 2 team-lead "On textbench10, which services produce the most error entries in the first five hours of 2025-09-23, and which of those should my team look at first? Say how exact the numbers are." &
run 3 manager "Give me a short status on textbench10: the biggest reliability risk in these five hours, how sure we are, and what to prioritise." &
wait
