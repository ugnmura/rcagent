# Huge datasets: 1 billion rows of TextBench, queried in place on S3

The extractor read the brief's TextBench file **`part_000.parquet`** (about **1 billion rows**, the first
30 minutes of the day) in place from the public S3 bucket. A full-text search of the whole file took
**4.18 s**, through a search index that took **69.9 s** to build once and needs over 64 GB of RAM. A search
without an index took **2.88 s** but covered only one minute of the file (00:10 to 00:11 UTC). The two cover
different amounts of data, so they are not a speed comparison.

All numbers come from one Slurm job on a shared HPC node. Raw logs: [`huge-datasets/`](huge-datasets/).

## What ran

| | |
|---|---|
| Data | `https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet`, read in place over HTTPS (no download, no local copy) |
| Rows | about 1,000,000,000 (one TextBench file. The brief: "One file is already a billion rows") |
| Extractor | commit `6cad141`. `main` has since merged further changes (evidence log, teams, `count_logs`, faster remote setup) that were not re-timed on this file |
| SereneDB | 26.10.1 amd64, under apptainer, data directory in `/dev/shm` |
| Machine | one shared HPC `devel` node: 16 CPUs, 128 GB RAM, Slurm job 5113147, 2026-10-18 07:02–07:04 UTC ([`meta.txt`](huge-datasets/meta.txt)) |
| Calls | the extractor's own MCP tools over stdio. Arguments in [`ext_setup.json`](huge-datasets/ext_setup.json) and [`ext_calls.json`](huge-datasets/ext_calls.json), steps in [`run.sh`](huge-datasets/run.sh) |

## Timings

Setup, once ([`ext_setup.jsonl`](huge-datasets/ext_setup.jsonl)):

| Step | What it reads | Time |
|---|---|---|
| `setup_log_table` | Only the source's metadata and 5 sample entries. The table is a view over the S3 file | **1.97 s** |
| `create_index(kind="search")` | Every entry: builds the full-text search index over all ~1B rows | **69.9 s** (index build time) |
| `survey` | Whole row groups as a block sample. Template counts are estimates with a stated margin | **7.84 s** |

Queries, 3 runs each ([`ext_queries.jsonl`](huge-datasets/ext_queries.jsonl)):

| Query | Index | Run 1 | Run 2 | Run 3 | Median |
|---|---|---|---|---|---|
| `search_logs` text `error`, **one minute** (2025-09-23 00:10–00:11 UTC), limit 20 | **without index**: every entry in that minute checked | 2.92 s | 2.88 s | 1.83 s | **2.88 s** |
| `search_logs` text `error`, **whole file** (all ~1B rows), limit 20 | **with index** (`tb_search_idx`, built once in 69.9 s): every entry with the word found | 3.14 s | 4.18 s | 4.23 s | **4.18 s** |

Every call returned `ok` and opens with a "How this was measured" line ("exact search through the search
index" for the whole file, "no index used" for the one minute). Whether the indexed search reads the S3 file
again or only the index was not established.

## The trade-off: index build time against query time

- **Without an index**, a search checks every row in scope. A wider scope costs more, and the cost guard
  predicts it first: a scope over the time budget is answered from a stated block sample, or the tool asks.
- **With the index**, "where does this error occur at all?" is answered across the whole file, at the price
  of the 69.9 s build and over 64 GB of RAM.
- **Break-even not measured.** A whole-file search without the index was never timed, so it is unknown how
  many searches repay the build.
- `create_index` with `dry_run` estimates size and build time first. `drop_index` removes the index afterwards.

## Memory

An earlier run (commit `623dfa0`, local copy of the same file) built the index in 76.5 s, then its database
server was killed for running out of memory at a 64 GB limit
([`oom-run-slurm-excerpt.txt`](huge-datasets/oom-run-slurm-excerpt.txt),
[`oom-run-extractor_setup.jsonl`](huge-datasets/oom-run-extractor_setup.jsonl)). The run above had 128 GB and
finished cleanly. Index builds are capped at the server's maximum query time (600 s by default, see
[Known limits](reference.md#known-limits)).

## Cost

- **Data transfer:** none on our side (public bucket, read in place).
- **Compute:** 99 s of tool time on 16 CPUs, about 0.44 core-hours, on an unpaid academic HPC allocation.
- **No paid services:** no AI functions, embeddings or external APIs inside the database.

## What this does and does not show

- **Shows:** a billion-row remote file registers in 1.97 s and can be searched exactly, with or without
  an index.
- **Does not show:**
  - more than one file. `part_{000..009}` (10 billion rows) works as a source, but no timings were recorded.
  - role answers (engineer, team lead, manager) on TextBench. The worked investigation uses the base corpus.
  - dedicated-machine timings. The `devel` node is shared, so the numbers are indicative.
