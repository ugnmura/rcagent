# Huge datasets: TextBench on S3, 1 and 10 billion rows, queried in place

The brief's OpenTelemetry TextBench files were read **straight from the public S3 bucket, with nothing
downloaded**: one file of **1 billion rows** (`part_000`, 41.0 GB) and ten files of **10 billion rows**
(`part_{000..009}`, 410.2 GB). The results, at commit `b51daa1`:

- **Whole-file search, with the index:** an exact search of the billion-row file takes **2.3 s**, after a **71 s**
  index build (37.5 GB).
- **Whole-file search, without the index:** the same exact search takes **15.4 s** through the extractor, or
  11.5 s in plain SQL. **The index repays its build after about 5 whole-file searches.**
- **10 billion rows:** registered in 0.6 s. Exact searches of a 60-second window take **2.9–3.5 s**, and an exact
  count of all 10 billion rows by service and level takes **32 s**.

All numbers come from Slurm jobs on one shared HPC node, run through the extractor's own MCP tools. The raw
per-call results, SQL output, job accounting and job scripts are in [`huge-datasets/b51daa1/`](huge-datasets/b51daa1/).

## What ran

| | |
|---|---|
| Data | `https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet` (1,000,000,000 entries, 41.0 GB, 2025-09-23 00:00–00:30 UTC) and `…/part_{000..009}.parquet` (10,000,000,000 entries, 410.2 GB, 16,246 row groups, 00:00–05:00 UTC), read in place over HTTPS |
| Extractor | `b51daa1`, a clean checkout (`dirty=0`) driven over stdio by [`drive.py`](huge-datasets/b51daa1/scripts/drive.py), one JSON line per call |
| SereneDB | 26.10.1 amd64 under apptainer, data directory in `/dev/shm`, trust auth on 127.0.0.1 |
| Machine | one shared HPC `devel` node, `r23m0124`: 16 CPUs, 128 GB RAM. Slurm jobs 5120494 (A), 5120974 and 5121278 (exact scans without the index), 5120975 (B), 2026-10-18 16:12–17:47 UTC ([`meta.txt`](huge-datasets/b51daa1/meta.txt)) |
| Summary | [`SUMMARY.md`](huge-datasets/b51daa1/SUMMARY.md), written by the person who ran the jobs, including two script faults and how they were redone |

## One file: 1 billion rows

Setup and searches without an index ([`A.jsonl`](huge-datasets/b51daa1/A.jsonl)):

| Step | What the tool did | Time |
|---|---|---|
| `setup_log_table` | read only the Parquet footer and 5 sample entries. The table is a view over the S3 file | **1.38 s** |
| `survey` | block sample of 5 row groups (99,096 entries), 235 templates, counts stated as estimates | **1.73 s** |
| `search_logs` "error", 60 s window (00:10–00:11 UTC) | exact scan of the window: 2,936,098 matches | **1.71 s** (median of 3) |
| `search_logs` "error", whole file, default | **estimated**, from a block sample of 1 row group (614,400 entries): "≈100,000,000 … rough estimate". The tool explains its choice: "An exact count would read ~26.1 GB (~4 min), so this is estimated from a sample" | **1.01 s** (median of 3) |
| `count_logs` "error" by service, whole file | estimated from the same block sample: frontend 91.2%, payment 7.3%, email 1.1% | **0.65 s** |

Exact search of the whole file without an index (one run each, [`Ax1_psql_substring.txt`](huge-datasets/b51daa1/Ax1_psql_substring.txt), [`Ax3_run_sql.jsonl`](huge-datasets/b51daa1/Ax3_run_sql.jsonl)):

| How | Query | Result | Time |
|---|---|---|---|
| plain SQL in psql, no extractor | `SELECT count(*) FROM extractor.lt_tb WHERE "Body" ILIKE '%error%'` | 94,902,425 (substring) | **11.5 s** |
| the extractor's `run_sql`, the same query | the guard answered TOO EXPENSIVE ("reads up to ~37.7 GB, ~6 min") and offered `confirmed_cost=37.7GB`, then ran again with that confirmation | 94,902,425 | **15.4 s** (0.55 s for the guard's answer) |

With the search index ([`A.jsonl`](huge-datasets/b51daa1/A.jsonl)):

| Step | What the tool did | Time |
|---|---|---|
| `create_index(kind="search", dry_run=true)` | trial build on 1,000,000 entries: "≈38.3 GB on disk, ~6 min" | 0.47 s |
| `create_index(kind="search")` | built over all 1,000,000,000 entries: **37.5 GB** on disk (**index build time**) | **70.7 s** |
| `search_logs` "error", **whole file, with index** | "exact search through the search index extractor."tb_search_idx" … no sampling": 93,638,388 matches (whole words, SQL `"Body" @@ ts_phrase('error')`) | **2.32 s** (median of 3) |
| `search_logs` "error", 60 s window, index present | scan of the window, on purpose: "the search index wasn't needed: a scan of this scope fits the cost budget". 2,936,098 matches | 1.73 s (median of 3) |
| `count_logs` "error" by service, index present | the same block-sample estimate as without the index: `count_logs` doesn't use the search index | 0.67 s |
| `drop_index` | index removed, disk space freed | 0.10 s |

### The trade-off: index build time against query time

- **Break-even:** the index costs 71 s once and saves 15.4 − 2.3 = 13.1 s per exact whole-file search. It repays
  the build after **about 5.4 searches** through the extractor, or 7.7 measured against plain SQL's 11.5 s.
- **What the two searches count differs:** without the index the search is a substring match (94,902,425
  entries contain "error" anywhere). The index matches whole words (93,638,388). A whole-word scan without the
  index wasn't timed: SereneDB rejected the `\m…\M` word-boundary regex ([`Ax2_psql_wholeword.txt`](huge-datasets/b51daa1/Ax2_psql_wholeword.txt)).
- **Without the index, the default is a stated estimate:** for a whole-file search the tool answers in about
  1 s from a sample, and says so. It doesn't offer to run the exact search. That took the `run_sql` call above.
- **Time windows don't need the index:** a 60-second window is a scan of about 3 million entries in under 2 s,
  with or without it.
- **When to drop it:** `drop_index` frees the 37.5 GB after the investigation.

## Ten files: 10 billion rows, no index

There is no index here: one file's index is 37.5 GB and its build peaked at 98 GB of RAM, so ten files won't fit on
a 128 GB node. That was not tried. Results from [`B.jsonl`](huge-datasets/b51daa1/B.jsonl):

| Step | What the tool did | Time |
|---|---|---|
| `inspect_source` `part_{000..009}` | metadata only: 10 files, 10,000,000,000 entries, 410.2 GB, 16,246 row groups | 2.40 s |
| `setup_log_table` as `textbench10` | a view over the ten S3 files, nothing downloaded | **0.57 s** |
| `survey`, all 10 files | **refused**: "TOO EXPENSIVE: needs ~113.3 GB read, ~19 min … more than the server's maximum query time (600 s)". Nothing ran | 0.57 s |
| `search_logs` "error", 60 s window at 00:10 UTC (file 0) | exact: 2,936,098 matches | **2.87 s** (median of 3) |
| `search_logs` "error", 60 s window at 02:30 UTC (file 5) | exact: 2,960,892 matches | **3.05 s** (median of 3) |
| `search_logs` "error", 60 s window at 04:50 UTC (file 9) | exact: 2,795,044 matches | **3.49 s** (median of 3) |
| `count_logs` "error" by service, 5 minutes (02:30–02:35 UTC) | exact: 15,211,837 matches. frontend 13,785,160 (90.6%), payment 1,206,121, email 189,420 | **4.39 s** (median of 3) |
| `count_logs` by service and level, **all 10 billion entries** | the guard asked first ("~5.3 GB, ~53 s", `confirmed_cost=5.3GB`), then ran exact: 62 groups, e.g. frontend·error 1,063,483,297 | **31.8 s** (+0.59 s for the guard's answer) |

A 60 s window costs about the same in the first file as in the last: 2.9 s against 3.5 s, over ten times the data
of one file.

## Role answers on 10 billion rows

Three live Claude sessions asked an engineer's, a team lead's and a manager's question about `textbench10`. The
agent picked its own tools. All three answered with evidence, exact counts where they could be afforded, and stated
estimates where they couldn't. See [live-session-textbench.md](live-session-textbench.md). For example, the team-lead
session:

- **Asked before a 27.1 GB count:** the cost guard predicted it would read about 27.1 GB, so the agent asked first
  and was told to go ahead.
- **Exact numbers:** it then gave exact error counts per service and team over all 10 billion entries.
- **Recommendation:** it pointed the team at Checkout & Payments, because most frontend errors repeat payment's
  "Visa cache full" failure.

## How good the cost guard's predictions were

The guard predicts a query's cost before running it, and then samples, asks or refuses. Here its byte estimates
were close, but its **time estimates were too high, by about 1.7 to 23 times**:

| Query | Predicted | Measured |
|---|---|---|
| exact whole-file search, `part_000` | ~26.1 GB, ~4 min | 11.5 s (plain SQL) |
| the same through `run_sql` | ~37.7 GB, ~6 min | 15.4 s |
| exact count of 10 billion entries by service and level | ~5.3 GB, ~53 s | 31.8 s |
| search index build, `part_000` (`dry_run`) | ~38.3 GB, ~6 min | 37.5 GB, 70.7 s |
| survey of all 10 files | ~113.3 GB, ~19 min | refused, so not measured |

So on this node the guard sampled, asked or refused more often than it needed to. Every answer still says which it
was: exact, estimated from a stated sample, or refused, with the reason.

## Memory and cost

- **Memory:** the index build over 1 billion rows peaked at **98 GB** (`MaxRSS` of job 5120494, which includes
  SereneDB). An earlier build at a 64 GB limit was killed for running out of memory
  ([`oom-run-slurm-excerpt.txt`](huge-datasets/oom-run-slurm-excerpt.txt)). The ten-file job without an index
  peaked at 13.9 GB.
- **Compute:** the four jobs took 38 CPU-minutes in total (`TotalCPU` 20:45 + 4:04 + 3:05 + 10:09, the
  `sacct-*.txt` files), about **0.63 core-hours**. The longest job ran for 2 minutes. That was an academic HPC
  allocation with no money charged.
- **Data transfer:** none on our side. The bucket is public and read in place.
- **No paid services** were used: no AI functions, embeddings or external APIs inside the database.

## Earlier run at `6cad141`

The first measurement (Slurm job 5113147, 2026-10-18 07:02 UTC, same node type and SereneDB) ran at `6cad141` and
covered one file only:

- setup 1.97 s
- index build 69.9 s
- whole-file search with the index 4.18 s
- 60 s window without the index 2.88 s
- survey 7.8 s.

Its raw logs are in [`huge-datasets/`](huge-datasets/) ([`run.sh`](huge-datasets/run.sh)). At `b51daa1`, setup,
survey and both searches are faster, and the index build takes about the same time.

## What this does and does not show

- **Shows:**
  - one billion rows and ten billion rows, registered from S3 in about a second and searched exactly within
    time windows
  - engineer, team-lead and manager answers on ten billion rows, from live sessions
  - the whole-file trade-off measured on both sides: 15.4 s exact without the index, 2.3 s with it, 71 s to build
  - every answer saying how it was measured.
- **Does not show:**
  - an index over all ten files: it won't fit in 128 GB
  - a survey of all ten files: the guard refused it as longer than the 600 s query limit
  - a whole-word scan without the index: the regex was rejected
  - timings at the current `main`: these ran at `b51daa1`
  - timings on a dedicated machine: the node is shared, so treat the numbers as indicative.
