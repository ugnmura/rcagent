# Huge datasets: 1 billion rows of TextBench, queried in place on S3

The extractor set up the brief's OpenTelemetry TextBench file **`part_000.parquet`** (about **1 billion rows**,
the first 30 minutes of the day) straight from the public S3 bucket, with nothing downloaded. It then built a
full-text search index over every one of those rows in **70 s**. With the index, a full-text search of the whole
billion-row file took **4.2 s**. Without the index, an exact search of a 60-second window took **2.9 s**.

All numbers below come from one Slurm job on a shared HPC node. The raw per-call logs are in
[`huge-datasets/`](huge-datasets/).

## What ran

| | |
|---|---|
| Data | `https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet`, read in place over HTTPS (no download, no local copy) |
| Rows | about 1,000,000,000 (one TextBench file; the brief: "One file is already a billion rows") |
| Extractor | commit `6cad141`. `main` has since merged further changes (evidence log, teams, `count_logs`, faster remote setup) that were not re-timed on this file |
| SereneDB | 26.10.1 amd64, under apptainer, data directory in `/dev/shm` |
| Machine | one shared HPC `devel` node: 16 CPUs, 128 GB RAM, Slurm job 5113147, 2026-10-18 07:02–07:04 UTC ([`meta.txt`](huge-datasets/meta.txt)) |
| Calls | the extractor's own MCP tools over stdio; arguments in [`ext_setup.json`](huge-datasets/ext_setup.json) and [`ext_calls.json`](huge-datasets/ext_calls.json); steps in [`run.sh`](huge-datasets/run.sh) |

## Timings

Setup, once ([`ext_setup.jsonl`](huge-datasets/ext_setup.jsonl)):

| Step | What it reads | Time |
|---|---|---|
| `setup_log_table` | Only the Parquet footer and 5 sample entries; the table is a view over the S3 file | **1.97 s** |
| `create_index(kind="search")` | Every entry: builds the full-text search index over all ~1B rows | **69.9 s** (index build time) |
| `survey` | Whole row groups as a block sample; template counts are estimates with a stated margin | **7.8 s** |

Queries, 3 runs each ([`ext_queries.jsonl`](huge-datasets/ext_queries.jsonl)):

| Query | Index | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|---|
| `search_logs` text `error`, 60 s window (2025-09-23 00:10–00:11 UTC), limit 20 | **without index**: exact scan of every entry in the window | 2.92 s | 2.88 s | 1.83 s | **2.88 s** |
| `search_logs` text `error`, **whole file** (all ~1B rows), limit 20 | **with index** (`tb_search_idx`): every entry with the word is found | 3.14 s | 4.18 s | 4.23 s | **4.18 s** |

Every call returned `ok`. Each result starts with the tool's own "How this was measured" line. For example, the
whole-file search says "exact search through the search index … every entry whose message has the words was
found; period: all time … no sampling", and the window search says "exact search: every entry in scope was
checked … no sampling; no index used".

## The trade-off: index build time against query time

- **Without an index**, a search is an exact scan of the rows in scope. For a 60-second window this costs
  about 3 s. A wider window costs more, and the cost guard predicts it before running: a scope over the time
  budget is answered from a stated block sample, or the tool asks first.
- **With the index**, the whole billion-row file is searchable in about 4 s, after a one-off 70 s build. That
  is the only way to ask "where does this error occur at all?" over the whole file in seconds.
- **The break-even point.** A whole-file scan without the index was not timed, so we can't give an exact
  count of searches. At 2.9 s per minute of data, a scan of the whole 30-minute file without the index
  would take about 90 s per search. The 70 s build is then repaid on the first or second whole-file search. That rate is
  indicative only: the node was shared and a scan does not scale exactly linearly.
- **When to drop it.** `drop_index` removes the index after the investigation, and `create_index` with
  `dry_run` estimates the size and the build time before building.

## Memory

The search index over 1B rows needs more than 64 GB of RAM. An earlier run at commit `623dfa0` reading a
local copy of the same file built the index in 76.5 s. Its database server was then
killed for running out of memory at a 64 GB limit
([`oom-run-slurm-excerpt.txt`](huge-datasets/oom-run-slurm-excerpt.txt),
[`oom-run-extractor_setup.jsonl`](huge-datasets/oom-run-extractor_setup.jsonl)). The run above used 128 GB and
finished cleanly. Index builds are also capped at the server's maximum query time (600 s by default; see
[Known limits](../README.md#known-limits)).

## Cost

- **Data transfer:** none on our side. The bucket is public and read in place; nothing was copied to local storage.
- **Compute:** the extractor's setup and queries took about 100 s of tool time on 16 CPUs, roughly 0.45
  core-hours. That was an academic HPC allocation with no money charged.
- **No paid services** were used: no AI functions, embeddings or external APIs inside the database.

## What this does and does not show

- **Shows:** a billion-row remote file can be registered in 2 s and searched exactly, both in a time window
  without an index and over the whole file with one. Every result states how it was measured.
- **Does not show:**
  - more than one file: `part_{000..009}` (10 billion rows) works as a source, but no timings were recorded;
  - role answers (engineer, team lead, manager) on TextBench; the worked investigation uses the base corpus;
  - timings on a dedicated machine: the `devel` node is shared, so treat the numbers as indicative.
