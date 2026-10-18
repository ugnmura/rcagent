#!/usr/bin/env bash
# One-command setup: start (or reuse) SereneDB in Docker, load the base corpus, check it, print the next step.
#
#   ./scripts/up.sh             full base corpus (BGL + OpenStack, ~63 MB download, a few minutes to convert)
#   ./scripts/up.sh --sample    the first SAMPLE_LINES lines of each log (default 50000), for a fast try
#   ./scripts/up.sh --replace   any other option is passed to scripts/load_base_corpus.py (here: switch the
#                               log tables from the sample to the full corpus)
#
# A second run is a no-op: the container is reused and every loader step is skipped when its output exists.
#
# Settings (environment variables, with defaults):
#   SERENEDB_CONTAINER=serenedb   container name
#   SERENEDB_PORT=7890            port on 127.0.0.1 (the server is never published on other interfaces)
#   LOGS_HOST_DIR=~/logs          folder mounted read-only into the container; the corpus goes under it
#   LOGS_CONTAINER_DIR=/logs      where the container sees that folder
#   SERENEDB_IMAGE                override the image chosen below
#   SAMPLE_LINES=50000            lines per log file with --sample
#
# Image: on an x86-64 Docker host, 26.10.1 (the digest the project was verified against). On an arm64 host
# (Apple Silicon), 26.10.1 crashes under amd64 emulation before it listens, so 26.09.2 runs natively instead.
set -euo pipefail

IMAGE_AMD64=serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9 # 26.10.1
IMAGE_ARM64=serenedb/serenedb@sha256:f9681a19f7f1290836e8ab200f0b1907dbe2c8380102a09f043a5c44e3ffa2b2 # 26.09.2
ZENODO="https://zenodo.org/records/8196385/files"

NAME=${SERENEDB_CONTAINER:-serenedb}
PORT=${SERENEDB_PORT:-7890}
HOST_DIR=${LOGS_HOST_DIR:-$HOME/logs}
HOST_DIR=${HOST_DIR/#\~/$HOME}
CONTAINER_DIR=${LOGS_CONTAINER_DIR:-/logs}
SAMPLE_LINES=${SAMPLE_LINES:-50000}

sample=0
loader_args=()
for arg in "$@"; do
  case "$arg" in
    --sample) sample=1 ;;
    -h | --help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) loader_args+=("$arg") ;;
  esac
done

cd "$(dirname "$0")/.."
say() { printf '==> %s\n' "$*"; }
die() { printf 'up.sh: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker is not installed"
command -v uv >/dev/null || die "uv is not installed (https://docs.astral.sh/uv/)"
docker info >/dev/null 2>&1 || die "Docker is not running"

mkdir -p "$HOST_DIR"
HOST_DIR=$(cd "$HOST_DIR" && pwd)
export SERENEDB_READER_URL="postgresql://postgres@localhost:${PORT}/postgres"
export LOGS_HOST_DIR="$HOST_DIR" LOGS_CONTAINER_DIR="$CONTAINER_DIR"
unset SERENEDB_WRITER_URL  # single-role mode, as in the README quick start

# ---------------------------------------------------------------- container

if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  say "reusing running container '$NAME' ($(docker inspect -f '{{.Config.Image}}' "$NAME"))"
elif docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  say "starting existing container '$NAME' ($(docker inspect -f '{{.Config.Image}}' "$NAME"))"
  docker start "$NAME" >/dev/null
else
  arch=$(docker info --format '{{.Architecture}}' 2>/dev/null || uname -m)
  if [[ -n "${SERENEDB_IMAGE:-}" ]]; then
    image=$SERENEDB_IMAGE why="SERENEDB_IMAGE is set"
  elif [[ "$arch" == aarch64 || "$arch" == arm64 ]]; then
    image=$IMAGE_ARM64
    why="arm64 Docker host: SereneDB 26.09.2 runs natively (26.10.1 crashes under amd64 emulation)"
  else
    image=$IMAGE_AMD64 why="$arch Docker host: SereneDB 26.10.1"
  fi
  say "starting '$NAME' from $image"
  say "  why: $why"
  docker run -d --name "$NAME" -e SERENEDB_HOST_AUTH_METHOD=trust \
    -p "127.0.0.1:${PORT}:7890" -v "${HOST_DIR}:${CONTAINER_DIR}:ro" "$image" >/dev/null
fi

say "waiting for SereneDB on 127.0.0.1:${PORT}"
ready=0
for _ in $(seq 1 90); do
  if uv run --quiet python - "$SERENEDB_READER_URL" >/dev/null 2>&1 <<'PY'
import sys, psycopg
with psycopg.connect(sys.argv[1], autocommit=True, connect_timeout=5) as c:
    assert c.execute("SELECT 1").fetchone() == (1,)
PY
  then ready=1; break; fi
  sleep 2
done
[[ $ready == 1 ]] || die "SereneDB did not answer on port ${PORT}; see: docker logs $NAME"

# ---------------------------------------------------------------- corpus

if [[ $sample == 1 ]]; then
  # Fetch the archives, keep only the first SAMPLE_LINES lines of each log, and let the loader convert
  # those (it skips its own download because the unpacked files exist).
  data_dir="$HOST_DIR/loghub-sample"
  if [[ ! -s "$data_dir/BGL/BGL.log" || ! -s "$data_dir/OpenStack/openstack_normal1.log" ]]; then
    say "preparing a sample of ${SAMPLE_LINES} lines per log in $data_dir"
    mkdir -p "$data_dir/BGL" "$data_dir/OpenStack"
    curl -fsSL "$ZENODO/BGL.zip?download=1" -o "$data_dir/BGL.zip"
    unzip -p "$data_dir/BGL.zip" BGL.log | head -n "$SAMPLE_LINES" > "$data_dir/BGL/BGL.log" || true
    curl -fsSL "$ZENODO/OpenStack.tar.gz?download=1" -o "$data_dir/OpenStack.tar.gz"
    tar -xzf "$data_dir/OpenStack.tar.gz" -C "$data_dir/OpenStack"
    for f in "$data_dir"/OpenStack/openstack_*.log; do
      head -n "$SAMPLE_LINES" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    done
    rm -f "$data_dir/BGL.zip" "$data_dir/OpenStack.tar.gz"
    [[ -s "$data_dir/BGL/BGL.log" ]] || die "could not extract BGL.log from the sample download"
  fi
else
  data_dir="$HOST_DIR/loghub"
fi
say "loading the base corpus from $data_dir"
uv run python scripts/load_base_corpus.py --data-dir "$data_dir" ${loader_args[@]+"${loader_args[@]}"}

# ---------------------------------------------------------------- smoke check

say "smoke check"
uv run --quiet python - <<'PY'
import os, sys
sys.path.insert(0, "src")
from serenedb_extractor.config import Settings
from serenedb_extractor.context import AppContext

ctx = AppContext.from_settings(Settings.from_env(os.environ))
try:
    tables = {lt.name: lt for lt in ctx.store.list_log_tables()}
    missing = {"bgl", "openstack"} - tables.keys()
    if missing:
        sys.exit(f"smoke check failed: log tables not set up: {', '.join(sorted(missing))}")
    for name in ("bgl", "openstack"):
        n = ctx.db.read(f"SELECT count(*) FROM {tables[name].relation}", {}).scalar()
        if not n:
            sys.exit(f"smoke check failed: log table '{name}' has no entries")
        print(f"    {name}: {n:,} entries ({tables[name].source})")
finally:
    ctx.db.close()
PY

cat <<EOF

Ready. Next step: start Claude Code in this folder and approve the project MCP server 'serenedb-extractor'
(from .mcp.json), then ask, for example:

    claude
    /engineer What failed on BGL on 11 June 2005, and what happened just before?

run_sql is off by default: this local setup uses one superuser connection, so SereneDB does not enforce
read-only for it (only the server's own SQL guard does). To turn it on anyway: export SERENEDB_ALLOW_SQL=1
EOF
if [[ "$PORT" != 7890 || "$HOST_DIR" != "$HOME/logs" || "$CONTAINER_DIR" != /logs ]]; then
  cat <<EOF

You changed the port or the logs folder, so export these before starting claude (.mcp.json reads them):

    export SERENEDB_READER_URL=$SERENEDB_READER_URL
    export LOGS_HOST_DIR=$HOST_DIR LOGS_CONTAINER_DIR=$CONTAINER_DIR
EOF
fi
if [[ $sample == 1 ]]; then
  echo
  echo "This is a sample. For the full corpus: ./scripts/up.sh --replace"
fi
