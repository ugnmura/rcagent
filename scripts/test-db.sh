#!/usr/bin/env bash
# Start (or reuse) the SereneDB test container and print SERENEDB_TEST_URL.
# The image has no linux/arm64 manifest, so it runs under amd64 emulation (slow start).
# Default posture needs a password for non-loopback clients; the test container uses trust (no password),
# so it is published on 127.0.0.1 only (never on all interfaces).
# An existing container named sdb-test is reused as-is (start it if stopped); it keeps whatever
# image, port binding and auth it was created with, so config can be stale. To recreate it with
# the settings below:  docker rm -f sdb-test && bash scripts/test-db.sh
set -euo pipefail
NAME=sdb-test
PORT=17890
# Pinned to the digest that scripts/verify_serenedb.py was run against (serenedb/serenedb:latest on 2026-10-18).
IMAGE=serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9
URL="postgresql://postgres@localhost:${PORT}/postgres"

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  docker ps --format '{{.Names}}' | grep -qx "$NAME" || docker start "$NAME" >/dev/null
else
  docker run -d --name "$NAME" --platform linux/amd64 -e SERENEDB_HOST_AUTH_METHOD=trust -p "127.0.0.1:${PORT}:7890" "$IMAGE" >/dev/null
fi

for _ in $(seq 1 120); do
  if uv run python - "$URL" >/dev/null 2>&1 <<'PY'
import sys, psycopg
with psycopg.connect(sys.argv[1], autocommit=True, connect_timeout=5) as c:
    assert c.execute("SELECT 1").fetchone() == (1,)
PY
  then
    echo "SERENEDB_TEST_URL=${URL}"
    exit 0
  fi
  sleep 2
done
echo "SereneDB did not become ready; see: docker logs $NAME" >&2
exit 1
