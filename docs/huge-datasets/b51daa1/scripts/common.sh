# Sourced by the hpc-measurements job scripts (extractor b51daa1). Starts SereneDB 26.10.1
# under apptainer with its data directory in /dev/shm, on 127.0.0.1:$PORT with trust auth (same setup
# as Slurm job 5113147), and exports the extractor's environment.
set -euo pipefail
export LC_ALL=C
module load Python/3.12.3  # without it the CVMFS interpreter segfaults importing C extensions
W=$HPCWORK/hpc-b51daa1
SIF=$HPCWORK/night-run-2/sdb-26.10.1.sif
EXT="$W/src/extractor"
PY="$EXT/.venv/bin/python"
SERVER_CMD="$EXT/.venv/bin/serenedb-extractor"
DRIVE="$PY $W/src/drive.py --cmd $SERVER_CMD"
PART000="https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet"
PART10="https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_{000..009}.parquet"
PORT=${PORT:-57895}
DATA=/dev/shm/$USER-sdb-$SLURM_JOB_ID
OUT="$W/results/$SLURM_JOB_ID"
mkdir -p "$OUT" "$DATA/db" "$DATA/etc"

export SERENEDB_READER_URL="postgresql://postgres@127.0.0.1:$PORT/postgres"
export SERENEDB_WRITER_URL="$SERENEDB_READER_URL"
export SERENEDB_ALLOW_SQL=1

{
  echo "job $SLURM_JOB_ID ($SLURM_JOB_NAME) node $(hostname) start $(date -u +%FT%TZ)"
  echo "image $SIF sha256 $(sha256sum "$SIF" | cut -d' ' -f1)"
  echo "extractor $(git -C "$EXT" rev-parse HEAD) dirty=$(git -C "$EXT" status --porcelain | wc -l)"
} | tee "$OUT/meta.txt"

printf -- '--server_directory=/var/lib/serenedb\n--listen=postgres://127.0.0.1:%s\n--log_storage=stdout\n--hba_config=/var/lib/serenedb-etc/pg_hba.conf\n' "$PORT" > "$DATA/etc/serened.conf"
echo "host all all 127.0.0.1/32 trust" > "$DATA/etc/pg_hba.conf"
apptainer exec --bind "$DATA/db:/var/lib/serenedb" --bind "$DATA/etc:/var/lib/serenedb-etc" "$SIF" \
    serened --flagfile=/var/lib/serenedb-etc/serened.conf > "$OUT/serened.log" 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; rm -rf "$DATA"; echo "end $(date -u +%FT%TZ)" >> "$OUT/meta.txt"; }
trap cleanup EXIT
for _ in $(seq 120); do
  apptainer exec "$SIF" psql -h 127.0.0.1 -p "$PORT" -U postgres -Atc "SELECT 1" >/dev/null 2>&1 && break
  sleep 1
done
apptainer exec "$SIF" psql -h 127.0.0.1 -p "$PORT" -U postgres -Atc "SELECT version()" | tee -a "$OUT/meta.txt"

psql_() { apptainer exec "$SIF" psql -h 127.0.0.1 -p "$PORT" -U postgres "$@"; }
