#!/usr/bin/env python3
"""MCP stdio driver for the hpc-measurements run (extractor b51daa1).

Starts one server command over stdio, runs a list of steps in order and appends one JSON line per
tool call to --out: {"label", "tool", "args", "run", "seconds", "ok", "result"} with the full
result text (plus "error" when the call raised).

steps.json is a JSON list of {"label", "tool", "args", "runs", "guard", "slow_s"}:
  runs   how many times to run the step (default 1)
  slow_s if the first run took longer than this, the remaining runs are skipped (A4 rule)
  guard  if true and the answer starts with "TOO EXPENSIVE" and offers confirmed_cost=<token>,
         that answer is recorded as its own line and the call is repeated once with
         confirmed_cost=<token> (also recorded). No other retries, ever.

Nothing is retried for a nicer number: a timeout, refusal or error is written as it came back.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

_TOKEN = re.compile(r"confirmed_cost=(~?[0-9]+(?:\.[0-9]+)?\s?(?:B|KB|MB|GB|TB|PB))", re.IGNORECASE)


def _emit(out, rec: dict) -> None:
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out.flush()
    head = rec.get("result", rec.get("error", ""))[:160].replace("\n", " | ")
    print(f"[{time.strftime('%H:%M:%S')}] {rec['label']} run={rec['run']} ok={rec['ok']} {rec['seconds']}s :: {head}",
          file=sys.stderr, flush=True)


async def _call(session, tool: str, args: dict, label: str, run: int, out) -> dict:
    t0 = time.monotonic()
    try:
        res = await session.call_tool(tool, args)
        dt = time.monotonic() - t0
        text = "".join(c.text for c in res.content if hasattr(c, "text"))
        rec = {"label": label, "tool": tool, "args": args, "run": run, "seconds": round(dt, 3),
               "ok": not bool(getattr(res, "isError", False)), "result": text}
    except Exception as exc:  # noqa: BLE001 - record it, never crash the run
        dt = time.monotonic() - t0
        rec = {"label": label, "tool": tool, "args": args, "run": run, "seconds": round(dt, 3),
               "ok": False, "result": "", "error": f"{type(exc).__name__}: {exc}"}
    _emit(out, rec)
    return rec


async def _run(cmd: list[str], steps: list[dict], out) -> None:
    from datetime import timedelta

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        # client-side read timeout well above the server's own 600 s cap (plus the guard's 2x margin)
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=1500)) as session:
            await session.initialize()
            for step in steps:
                label, tool, args = step["label"], step["tool"], step.get("args", {})
                for run in range(1, int(step.get("runs", 1)) + 1):
                    rec = await _call(session, tool, args, label, run, out)
                    total = rec["seconds"]
                    m = _TOKEN.search(rec["result"]) if step.get("guard") else None
                    # the refusal comes after the "How this was measured:" line, so look anywhere in it
                    if m and "TOO EXPENSIVE" in rec["result"]:
                        conf = await _call(session, tool, {**args, "confirmed_cost": m.group(1).replace(" ", "")},
                                           label + ":confirmed", run, out)
                        total = conf["seconds"]
                    slow = step.get("slow_s")
                    if slow is not None and run == 1 and total > slow:
                        print(f"{label}: first run {total}s > {slow}s, 1 run only", file=sys.stderr, flush=True)
                        break


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cmd", required=True)
    p.add_argument("--steps", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    steps = json.loads(a.steps.read_text())
    with a.out.open("a") as out:
        asyncio.run(_run(shlex.split(a.cmd), steps, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
