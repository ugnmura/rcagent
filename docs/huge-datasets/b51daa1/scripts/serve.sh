#!/usr/bin/env bash
# Runs the extractor (b51daa1, unchanged) over stdio against the SereneDB of the current job on port $1.
module load Python/3.12.3 >/dev/null 2>&1
export SERENEDB_READER_URL="postgresql://postgres@127.0.0.1:$1/postgres"
export SERENEDB_WRITER_URL="$SERENEDB_READER_URL"
export SERENEDB_ALLOW_SQL=1
cd $HPCWORK/hpc-b51daa1/src/extractor
exec .venv/bin/serenedb-extractor
