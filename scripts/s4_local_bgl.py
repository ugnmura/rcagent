"""S4 local check: template grouping accuracy on a Loghub *_2k dataset vs the gold EventIds.

Runs OUR pipeline over the Content column: masking in SereneDB (mask_sql, the SQL the survey
runs), grouping of identical masked strings, then drain.merge_groups. Each line gets the
template its masked string was merged into. Scores, the standard Loghub way:
  GA  = share of lines whose predicted group equals their gold group as a set of lines;
  FGA = F1 over groups (a predicted group is correct iff it equals a gold group).
Lists the gold events that were merged with others or split, with examples.

Run (loghub cloned with `gh repo clone logpai/loghub <dir> -- --depth 1`):
  uv run python scripts/s4_local_bgl.py <loghub>/BGL/BGL_2k.log_structured.csv [more.csv ...]
Uses SERENEDB_TEST_URL (default the local test container); creates database s4_bgl and drops it.
"""

from __future__ import annotations

import csv
import os
import sys
from collections import Counter, defaultdict

import psycopg
import psycopg.conninfo

from rcagent.templating.drain import MaskedGroup, merge_groups
from rcagent.templating.masking import mask_sql

URL = os.environ.get("SERENEDB_TEST_URL", "postgresql://postgres@localhost:17890/postgres")
DB = "s4_bgl"
SHOW = int(os.environ.get("S4_SHOW", "15"))


def _connect(dbname: str) -> psycopg.Connection:
    info = psycopg.conninfo.conninfo_to_dict(URL)
    info["dbname"] = dbname
    return psycopg.connect(psycopg.conninfo.make_conninfo("", **info), autocommit=True, cursor_factory=psycopg.ClientCursor)


def _load(path: str) -> tuple[list[str], list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r["Content"] for r in rows], [r["EventId"] for r in rows]


def _mask_in_serenedb(contents: list[str]) -> list[str]:
    with _connect(DB) as conn:
        conn.execute("DROP TABLE IF EXISTS s4_lines")
        conn.execute("CREATE TABLE s4_lines (id INTEGER, content VARCHAR)")
        with conn.cursor() as cur:
            for start in range(0, len(contents), 500):
                chunk = list(enumerate(contents))[start : start + 500]
                values = ", ".join(["(%s, %s)"] * len(chunk))
                cur.execute(f"INSERT INTO s4_lines VALUES {values}", [v for pair in chunk for v in pair])
        rows = conn.execute(f"SELECT id, {mask_sql('content')} FROM s4_lines ORDER BY id").fetchall()
        conn.execute("DROP TABLE s4_lines")
    return [m for _, m in rows]


def _predict(contents: list[str], masked: list[str]) -> list[str]:
    counts = Counter(masked)
    example: dict[str, str] = {}
    for c, m in zip(contents, masked, strict=True):
        example.setdefault(m, c)
    groups = [MaskedGroup(masked=m, count=n, example=example[m]) for m, n in counts.items()]
    sim_th = os.environ.get("S4_SIM_TH")  # optional override of merge_groups' default
    merged = merge_groups(groups, sim_th=float(sim_th)) if sim_th else merge_groups(groups)
    template_of = {mask: t.template for t in merged for mask in t.masks}
    return [template_of[m] for m in masked]


def _score(pred: list[str], gold: list[str]) -> tuple[float, float, int, int]:
    p_sets: dict[str, set[int]] = defaultdict(set)
    g_sets: dict[str, set[int]] = defaultdict(set)
    for i, (p, g) in enumerate(zip(pred, gold, strict=True)):
        p_sets[p].add(i)
        g_sets[g].add(i)
    gold_frozen = {frozenset(s) for s in g_sets.values()}
    correct_groups = [s for s in p_sets.values() if frozenset(s) in gold_frozen]
    ga = sum(len(s) for s in correct_groups) / len(pred)
    prec = len(correct_groups) / len(p_sets)
    rec = len(correct_groups) / len(g_sets)
    fga = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
    return ga, fga, len(p_sets), len(g_sets)


def _report(contents: list[str], masked: list[str], pred: list[str], gold: list[str]) -> None:
    by_pred: dict[str, set[str]] = defaultdict(set)
    by_gold: dict[str, Counter[str]] = defaultdict(Counter)
    for p, g in zip(pred, gold, strict=True):
        by_pred[p].add(g)
        by_gold[g][p] += 1
    first: dict[str, int] = {}
    for i, g in enumerate(gold):
        first.setdefault(g, i)
    print(f"\n-- predicted templates fusing several gold events (top {SHOW} by lines)")
    fused = sorted((p for p, gs in by_pred.items() if len(gs) > 1), key=lambda p: -sum(by_gold[g][p] for g in by_pred[p]))
    for p in fused[:SHOW]:
        print(f"  [{len(by_pred[p])} events] {p[:140]}")
        for g in sorted(by_pred[p])[:4]:
            print(f"      {g} x{by_gold[g][p]}: {contents[first[g]][:120]}")
    print(f"\n-- gold events split over several predicted templates (top {SHOW} by lines)")
    split = sorted((g for g, ps in by_gold.items() if len(ps) > 1), key=lambda g: -sum(by_gold[g].values()))
    for g in split[:SHOW]:
        print(f"  {g} ({sum(by_gold[g].values())} lines, {len(by_gold[g])} templates): {contents[first[g]][:110]}")
        for p, n in by_gold[g].most_common(4):
            print(f"      x{n}: {p[:130]}")
    print(f"  ({len(fused)} fusing templates, {len(split)} split events)")


def main(paths: list[str]) -> None:
    with _connect("postgres") as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {DB}")
        admin.execute(f"CREATE DATABASE {DB}")
    try:
        results = []
        for path in paths:
            contents, gold = _load(path)
            masked = _mask_in_serenedb(contents)
            pred = _predict(contents, masked)
            ga, fga, n_pred, n_gold = _score(pred, gold)
            name = os.path.basename(path).split(".")[0]
            print(f"== {name}: GA {ga:.3f}  FGA {fga:.3f}  ({n_pred} predicted / {n_gold} gold templates)")
            if os.environ.get("S4_QUIET") != "1":
                _report(contents, masked, pred, gold)
            results.append((name, ga, fga))
        print("\nSUMMARY " + "  ".join(f"{n}: GA {ga:.3f} FGA {fga:.3f}" for n, ga, fga in results))
    finally:
        with _connect("postgres") as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {DB}")


if __name__ == "__main__":
    main(sys.argv[1:] or sys.exit(__doc__))
