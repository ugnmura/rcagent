#!/usr/bin/env bash
# The extractor's half of the 1-billion-row TextBench run (Slurm job 5113147, 2026-10-18, extractor 6cad141).
# One node: 16 CPUs, 128 GB RAM (--mem=128G), SereneDB 26.10.1 amd64 under apptainer, data dir in /dev/shm.
# SereneDB was started on 127.0.0.1:$PORT with trust auth; then the extractor's own MCP server was driven
# over stdio with the calls in ext_setup.json (once) and ext_calls.json (3 times each).
# The driver (an MCP stdio client that times each call and writes one JSON line per call) is not part of
# this repo; any MCP client that calls the same tools with the same arguments reproduces the run.
set -euo pipefail
PARQUET_URL="https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet"
export SERENEDB_READER_URL="postgresql://postgres@127.0.0.1:${PORT:?}/postgres"
export SERENEDB_WRITER_URL="$SERENEDB_READER_URL"
export SERENEDB_ALLOW_SQL=1
# setup: register the S3 file in place (no download), build the search index over every entry, survey
#   setup_log_table {"name": "tb", "source": "$PARQUET_URL", "build_search_index": false}
#   create_index    {"log_table": "tb", "kind": "search"}
#   survey          {"log_table": "tb"}
# queries, 3 runs each:
#   search_logs {"log_table": "tb", "text": "error", "start": "2025-09-23T00:10:00", "end": "2025-09-23T00:11:00", "timezone": "UTC", "limit": 20}
#   search_logs {"log_table": "tb", "text": "error", "fuzzy": false, "limit": 20}
