"""S6 probe: Timestamp column type, generated time SQL, and search_logs / count_logs timings over a
60-second window of TextBench (3 warm runs). Run inside the bench environment with SERENEDB_READER_URL set."""
import os
import sys
import time

import serenedb_extractor
from serenedb_extractor.config import Settings
from serenedb_extractor.context import AppContext
from serenedb_extractor.query import stats
from serenedb_extractor.query.filters import parse_time_range, time_clause
from serenedb_extractor.setup.sniff import relation_columns
from serenedb_extractor.tools.aggregate import count_logs
from serenedb_extractor.tools.lookup import search_logs

print("module", serenedb_extractor.__file__)
ctx = AppContext.from_settings(Settings.from_env(os.environ))
db = ctx.db
lt = ctx.store.get_log_table("textbench")
print("source", lt.mode, lt.source_format, "tz", lt.timezone, "ts role", lt.roles.timestamp)
cols = dict(relation_columns(db, lt.relation, lt.source, True))
print("type of Timestamp:", repr(cols.get("Timestamp")))
S, E = os.environ.get("S6_START", "2025-09-23T00:10:00Z"), os.environ.get("S6_END", "2025-09-23T00:11:00Z")
tr = parse_time_range(S, E, "UTC")
sql, p = time_clause(lt, tr, cols)
print("time_clause:", sql, p)

orig = db.read
log: list[tuple[float, str]] = []


def read(q, params=None, *a, **k):  # type: ignore[no-untyped-def]
    t = time.perf_counter()
    try:
        return orig(q, params, *a, **k)
    finally:
        log.append((time.perf_counter() - t, " ".join(q.split())[:300]))


db.read = read  # type: ignore[method-assign]


def run(name, fn):  # type: ignore[no-untyped-def]
    ts = []
    for _ in range(4):
        log.clear()
        t = time.perf_counter()
        with stats.per_call():  # one tool call, as the server wraps it
            out = fn()
        ts.append(time.perf_counter() - t)
    print(f"== {name}: warm runs {', '.join(f'{x:.2f}' for x in ts[1:])} s (cold {ts[0]:.2f})")
    for d, q in log:
        print(f"   {d:6.3f}  {q}")
    print("   out:", " ".join(out.split())[:300])


run("search_logs text=error limit=20 (S6 call)", lambda: search_logs(ctx, "textbench", start=S, end=E, text="error", limit=20, timezone="UTC"))
run("search_logs no text", lambda: search_logs(ctx, "textbench", start=S, end=E, timezone="UTC"))
run("count_logs", lambda: count_logs(ctx, ["textbench"], start=S, end=E, timezone="UTC"))
if len(sys.argv) > 1:
    for row in orig(f"EXPLAIN SELECT count(*) FROM {lt.relation} WHERE {sql}", p).rows:
        print(row[-1])
