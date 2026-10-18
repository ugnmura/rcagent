"""Times MCP tool calls against the extractor over stdio. One JSON line per call.

usage: python driver.py calls.json out.jsonl   (env: SERENEDB_* as for the server; EXTRACTOR_DIR = checkout)
calls.json: [{"tool": ..., "args": {...}, "label": ..., "runs": n}]
"""
import asyncio, json, os, re, sys, time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(calls_path: str, out_path: str) -> None:
    calls = json.load(open(calls_path))
    params = StdioServerParameters(
        command="uv",
        args=["run", "--directory", os.environ["EXTRACTOR_DIR"], "serenedb-extractor"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        with open(out_path, "a") as out:
            for c in calls:
                for run in range(1, c.get("runs", 1) + 1):
                    args = dict(c["args"])
                    t = time.perf_counter()
                    res = await s.call_tool(c["tool"], args)
                    dt = time.perf_counter() - t
                    text = "".join(getattr(x, "text", "") for x in res.content)
                    rec = {"label": c["label"], "run": run, "tool": c["tool"], "args": args,
                           "seconds": round(dt, 3), "ok": not res.isError, "result": text}
                    out.write(json.dumps(rec) + "\n"); out.flush()
                    print(f'{c["label"]} run {run}: {dt:.2f} s ok={not res.isError} | {text[:160]!r}', flush=True)
                    m = re.search(r"confirmed_cost[\"'=: ]+[\"']?([A-Za-z0-9_:.\-]+)", text)
                    if "TOO EXPENSIVE" in text and m and c.get("confirm"):
                        args2 = dict(args, confirmed_cost=m.group(1))
                        t = time.perf_counter()
                        res = await s.call_tool(c["tool"], args2)
                        dt = time.perf_counter() - t
                        text = "".join(getattr(x, "text", "") for x in res.content)
                        out.write(json.dumps({**rec, "label": c["label"] + ":confirmed", "args": args2,
                                              "seconds": round(dt, 3), "ok": not res.isError, "result": text}) + "\n")
                        print(f'{c["label"]}:confirmed run {run}: {dt:.2f} s | {text[:160]!r}', flush=True)


asyncio.run(main(sys.argv[1], sys.argv[2]))
