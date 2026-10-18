"""S4 template-grouping score (GA / FGA) of the extractor in the current checkout, on Loghub-2.0 2k samples.

A fast local stand-in for serenedb-bench `harness/s4` (extractor_catalog.py + score_templates.py),
same method, smaller data:
  1. a fresh scratch database (default `s4_base`) on the SereneDB at --dsn;
  2. this checkout's MCP server (stdio) runs `setup_log_table` for `openstack` and `bgl` on the raw
     Loghub-2.0 `<DS>_2k.log` files;
  3. the catalog is built with `survey` (sample_size=1000000, limit=300), repeated with every known
     template in `exclude` until a round adds nothing (harness extractor_catalog.py);
  4. each gold `Content` of `<DS>_2k.log_structured_corrected.csv` goes to the first template, in
     template-ID order, whose stored regex full-matches it (`regexp_full_match` in SereneDB); lines
     no template matches form `__unmatched__`, never correct (harness score_templates.py);
  5. GA / PGA / RGA / FGA as in Jiang et al. ISSTA 2024; the database is dropped (unless --keep).

The full-size night run uses `<DS>_full.log_structured.csv`; numbers here are on the 2k samples,
so they are comparable between commits, not to the night run's absolute values.

Usage (from the extractor checkout):
  uv run python scripts/s4_score.py                      # scores only
  uv run python scripts/s4_score.py --diagnose           # + merged / split gold events with examples
  uv run python scripts/s4_score.py --datasets openstack --json out.json
Options: --dsn (default postgresql://postgres@localhost:17890/postgres), --db s4_base,
--data <dir> (2k files are downloaded there from github.com/logpai/loghub-2.0 when missing).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import psycopg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DATASETS = {"openstack": "OpenStack", "bgl": "BGL"}
RAW_URL = "https://raw.githubusercontent.com/logpai/loghub-2.0/main/2k_dataset/{ds}/{f}"
TOKEN = re.compile(r"confirmed_cost=(\S+?)[\s.,;)]*(?:\s|$)")
SAMPLE_MAX = 1_000_000
LIMIT_MAX = 300
UNMATCHED = "__unmatched__"
csv.field_size_limit(sys.maxsize)


def fetch(data: Path, ds: str) -> tuple[Path, Path]:
    name = DATASETS[ds]
    data.mkdir(parents=True, exist_ok=True)
    out = []
    for f in (f"{name}_2k.log", f"{name}_2k.log_structured_corrected.csv"):
        p = data / f
        if not p.exists():
            urllib.request.urlretrieve(RAW_URL.format(ds=name, f=f), p)
        out.append(p)
    return out[0], out[1]


def with_db(dsn: str, db: str) -> str:
    u = urllib.parse.urlsplit(dsn)
    return urllib.parse.urlunsplit(u._replace(path=f"/{db}"))


def recreate(admin_dsn: str, db: str, drop_only: bool = False) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{db}"')
        if not drop_only:
            c.execute(f'CREATE DATABASE "{db}"')


def tool_text(res) -> str:
    return "\n".join(getattr(x, "text", "") for x in res.content)


def is_error(res) -> bool:
    return bool(getattr(res, "is_error", getattr(res, "isError", False)))


def template_ids(dsn: str, table: str) -> list[str]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return [
            r[0]
            for r in c.execute(
                "SELECT template_id FROM extractor.templates WHERE log_table = %s",
                (table,),
            )
        ]


async def build_catalog(
    repo: str, dsn: str, sources: dict[str, Path], rounds: int, verbose: bool
) -> None:
    env = {**os.environ, "SERENEDB_READER_URL": dsn}
    env.pop("SERENEDB_WRITER_URL", None)
    params = StdioServerParameters(
        command="uv", args=["run", "--directory", repo, "serenedb-extractor"], env=env
    )
    errlog = sys.stderr if verbose else open(os.devnull, "w")  # noqa: SIM115, ASYNC230
    async with stdio_client(params, errlog=errlog) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for table, src in sources.items():
            t0 = time.monotonic()
            res = await s.call_tool(
                "setup_log_table", {"name": table, "source": str(src)}
            )
            setup_text = tool_text(res)
            if is_error(res):
                raise SystemExit(f"setup_log_table {table} failed:\n{setup_text}")
            if verbose:
                print(
                    f"[setup {table}] {time.monotonic() - t0:.1f}s\n{setup_text[:600]}",
                    file=sys.stderr,
                )
            for rnd in range(1, rounds + 1):
                before = template_ids(dsn, table)
                args: dict[str, object] = {
                    "log_table": table,
                    "sample_size": SAMPLE_MAX,
                    "limit": LIMIT_MAX,
                }
                if before:
                    args["exclude"] = sorted(before)
                res = await s.call_tool("survey", args)
                text = tool_text(res)
                if (m := TOKEN.search(text)) and "run it anyway" in text:
                    res = await s.call_tool(
                        "survey", {**args, "confirmed_cost": m.group(1)}
                    )
                    text = tool_text(res)
                after = template_ids(dsn, table)
                if verbose:
                    print(
                        f"[survey {table} r{rnd}] {len(before)} -> {len(after)} templates",
                        file=sys.stderr,
                    )
                if is_error(res) or len(after) <= len(before):
                    if not after:
                        raise SystemExit(
                            f"no templates for {table}; setup said:\n{setup_text}\nsurvey said:\n{text}"
                        )
                    break


def load_gold(path: Path) -> Counter[tuple[str, str]]:
    gold: Counter[tuple[str, str]] = Counter()
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            gold[(row["Content"], row["EventId"])] += 1
    return gold


def _tid_key(tid: str) -> tuple[int, str]:
    m = re.fullmatch(r"T(\d+)", tid)
    return (int(m.group(1)), tid) if m else (sys.maxsize, tid)


def map_extractor(
    dsn: str, table: str, contents: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    with psycopg.connect(dsn, autocommit=True) as c:
        templates = sorted(
            c.execute(
                "SELECT template_id, regex, template FROM extractor.templates WHERE log_table = %s",
                (table,),
            ).fetchall(),
            key=lambda r: _tid_key(r[0]),
        )
        c.execute("CREATE TEMPORARY TABLE s4_content (content VARCHAR, tid VARCHAR)")
        with c.cursor().copy("COPY s4_content (content) FROM STDIN") as cp:
            for s in contents:
                cp.write_row((s,))
        for tid, rx, _ in templates:
            c.execute(
                "UPDATE s4_content SET tid = %s WHERE tid IS NULL AND regexp_full_match(content, %s)",
                (tid, rx),
            )
        rows = c.execute(
            "SELECT content, tid FROM s4_content WHERE tid IS NOT NULL"
        ).fetchall()
    return {s: t for s, t in rows}, {tid: tpl for tid, _, tpl in templates}


def score(
    gold: Counter[tuple[str, str]], pred: dict[str, str]
) -> dict[str, float | int]:
    """Verbatim metric of serenedb-bench harness/s4/score_templates.py."""
    cont: Counter[tuple[str, str]] = Counter()
    for (content, eid), n in gold.items():
        cont[(pred.get(content, UNMATCHED), eid)] += n
    pred_tot: Counter[str] = Counter()
    gold_tot: Counter[str] = Counter()
    golds_of: dict[str, set[str]] = defaultdict(set)
    for (p, g), n in cont.items():
        pred_tot[p] += n
        gold_tot[g] += n
        golds_of[p].add(g)
    lines = sum(pred_tot.values())
    correct = [
        p
        for p, gs in golds_of.items()
        if p != UNMATCHED
        and len(gs) == 1
        and (g := next(iter(gs))) is not None
        and cont[(p, g)] == gold_tot[g] == pred_tot[p]
    ]
    unmatched = pred_tot.get(UNMATCHED, 0)
    pred_groups = len(pred_tot) - (1 if unmatched else 0)
    ga = sum(pred_tot[p] for p in correct) / lines
    pga = len(correct) / pred_groups if pred_groups else 0.0
    rga = len(correct) / len(gold_tot)
    fga = 2 * pga * rga / (pga + rga) if pga + rga else 0.0
    return {
        "lines": lines,
        "gold_groups": len(gold_tot),
        "pred_groups": pred_groups,
        "unmatched_lines": unmatched,
        "correct_groups": len(correct),
        "GA": round(ga, 4),
        "PGA": round(pga, 4),
        "RGA": round(rga, 4),
        "FGA": round(fga, 4),
    }


def diagnose(
    gold: Counter[tuple[str, str]],
    pred: dict[str, str],
    tpl: dict[str, str],
    gold_tpl: dict[str, str],
) -> str:
    cont: Counter[tuple[str, str]] = Counter()
    ex: dict[tuple[str, str], list[str]] = defaultdict(list)
    for (content, eid), n in gold.items():
        p = pred.get(content, UNMATCHED)
        cont[(p, eid)] += n
        if len(ex[(p, eid)]) < 2:
            ex[(p, eid)].append(content)
    golds_of: dict[str, Counter[str]] = defaultdict(Counter)
    preds_of: dict[str, Counter[str]] = defaultdict(Counter)
    for (p, g), n in cont.items():
        golds_of[p][g] += n
        preds_of[g][p] += n
    out = []
    merged = sorted(
        (p for p in golds_of if len(golds_of[p]) > 1),
        key=lambda p: -sum(golds_of[p].values()),
    )
    out.append(
        f"MERGED predicted templates ({len(merged)}): several gold EventIds in one template"
    )
    for p in merged:
        out.append(
            f"  {p} [{sum(golds_of[p].values())} lines]  {tpl.get(p, '(no template matched)')}"
        )
        for g, n in golds_of[p].most_common():
            out.append(f"     {g} x{n}  gold: {gold_tpl.get(g, '')}")
            for e in ex[(p, g)]:
                out.append(f"         | {e}")
    split = sorted(
        (g for g in preds_of if len(preds_of[g]) > 1),
        key=lambda g: -sum(preds_of[g].values()),
    )
    out.append(
        f"SPLIT gold events ({len(split)}): one EventId across several predicted templates"
    )
    for g in split:
        out.append(
            f"  {g} [{sum(preds_of[g].values())} lines]  gold: {gold_tpl.get(g, '')}"
        )
        for p, n in preds_of[g].most_common():
            out.append(f"     {p} x{n}  {tpl.get(p, '(no template matched)')}")
            for e in ex[(p, g)]:
                out.append(f"         | {e}")
    return "\n".join(out)


def gold_templates(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        return {row["EventId"]: row["EventTemplate"] for row in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--dsn",
        default="postgresql://postgres@localhost:17890/postgres",
        help="admin DSN (any database)",
    )
    ap.add_argument(
        "--db", default="s4_base", help="scratch database, dropped and recreated"
    )
    ap.add_argument(
        "--repo", default=".", help="extractor checkout (default: current directory)"
    )
    ap.add_argument(
        "--data",
        type=Path,
        default=Path(
            os.environ.get("S4_DATA", Path(tempfile.gettempdir()) / "s4-lh2k")
        ),
    )
    ap.add_argument("--datasets", default="openstack,bgl")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument(
        "--diagnose",
        action="store_true",
        help="print merged / split gold events with examples",
    )
    ap.add_argument("--json", type=Path, help="also write the scores here")
    ap.add_argument("--keep", action="store_true", help="keep the scratch database")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    datasets = [d.strip() for d in a.datasets.split(",") if d.strip()]
    files = {ds: fetch(a.data, ds) for ds in datasets}
    db_dsn = with_db(a.dsn, a.db)
    t0 = time.monotonic()
    recreate(a.dsn, a.db)
    results = []
    try:
        asyncio.run(
            build_catalog(
                str(Path(a.repo).resolve()),
                db_dsn,
                {ds: files[ds][0].resolve() for ds in datasets},
                a.rounds,
                a.verbose,
            )
        )
        for ds in datasets:
            gold = load_gold(files[ds][1])
            contents = sorted({c for c, _ in gold})
            pred, tpl = map_extractor(db_dsn, ds, contents)
            r = {"dataset": ds, **score(gold, pred)}
            results.append(r)
            print(json.dumps(r), flush=True)
            if a.diagnose:
                print(
                    f"\n=== {ds} ===\n"
                    + diagnose(gold, pred, tpl, gold_templates(files[ds][1]))
                    + "\n",
                    flush=True,
                )
    finally:
        if not a.keep:
            recreate(a.dsn, a.db, drop_only=True)
    print(f"({time.monotonic() - t0:.1f}s)", file=sys.stderr)
    if a.json:
        a.json.write_text(json.dumps(results, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
