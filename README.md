<div align="center">

# serenedb-extractor

<h3>Ask your logs in plain words. Every number in the answer links to the SQL that produced it.</h3>

[![MCP server](https://img.shields.io/badge/MCP-server-2a78d6?style=for-the-badge)](https://modelcontextprotocol.io)
[![Built on SereneDB](https://img.shields.io/badge/built%20on-SereneDB-9865e8?style=for-the-badge)](https://serenedb.com)
[![National AI Hackathon 2026](https://img.shields.io/badge/National%20AI%20Hackathon-2026-fbe5f5?style=for-the-badge)](#)

</div>

An MCP server that lets Claude investigate millions of log lines for three people: an **engineer** chasing an
error, a **team lead** looking for recurring problems, and a **manager** deciding what comes first. SereneDB does
the searching and counting. Claude explains the results. Built for *Making Sense of Logs* (SereneDB track).

**Demo video:** _link to come_ · **Worked investigation:** [below](#worked-investigation-one-corpus-three-roles) ·
**Requirements checklist:** [docs/reference.md](docs/reference.md#requirements-checklist)

## Optional features

Besides the required workflow, the server covers these optional parts of the brief, plus one addition of our own:

| feature | what it does | measured |
|---|---|---|
| **Polished MCP server** | 18 tools that say when to use them, what they take and what they return. Results are capped and say when they were cut. Role prompts `/engineer`, `/team-lead`, `/manager` | **96.9%** on 30 sealed held-out questions, blind-graded, **$0.117** per answer ([evaluation](docs/EVALUATION.md)) |
| **Huge datasets** | Reads one TextBench file, **1 billion rows**, in place from the public S3 bucket. Nothing is downloaded | one minute searched without an index: **2.88 s**. Whole file searched with an index: **4.18 s**, after a **69.9 s** build needing over 64 GB of RAM ([timings](docs/HUGE_DATASETS.md)) |
| **Agent-managed indexes** | `create_index` (with a `dry_run` size and time estimate) and `drop_index`. The agent builds an index for an investigation and removes it after | build time against query time in [docs/HUGE_DATASETS.md](docs/HUGE_DATASETS.md#the-trade-off-index-build-time-against-query-time) |
| **Phrase and fuzzy search** | `search_logs` matches words in order, or with `fuzzy` each word within a typo or two, through the search index | |
| **Template mining** (our own) | Groups log lines into message templates at question time (SQL masking, then Drain), kept as stable IDs `T1, T2, …` | best BGL grouping score (FGA 0.745) of every approach compared, published parsers included ([table](docs/EVALUATION.md#templating-better-grouping-than-drain-on-the-full-loghub-20-data)) |

<img src="docs/img/bench-quality.svg" alt="Answer quality on 30 sealed held-out questions: this server scores 96.9% on a blind rubric (18 fixed tools 92.9%, 7 fixed tools 93.5%), 98% on exact values (94%, 96%), costs $0.117 per answer ($0.459, $0.259) and uses 5.9 tool calls per answer (9.2, 6.6)." width="100%">

The team built three MCP server designs over the same data and kept the best. The chart compares them
([how they differ](docs/EVALUATION.md#the-three-designs-compared)). A separate model wrote the questions without
seeing this repository, and a blind grader scored the answers. These finals ran at commit `6cad141`. The current
version, rerun on the screening set with Sonnet 5.5, scored 94.4% on the rubric and 99% on exact values.

<img src="docs/img/bench-textbench.svg" alt="TextBench, 1 billion rows read in place on S3: search of the whole file with the index 4.18 s, exact search of a 60-second window without an index 2.88 s, survey 7.8 s, registering the S3 file 1.97 s, building the search index 69.9 s." width="100%">


## How it works

<p align="center">
  <img src="docs/img/flow.svg" alt="You ask Claude a question. Claude calls a serenedb-extractor tool, and the tool runs SQL in SereneDB. Counts come back with an evidence ID (Q46), Claude answers citing it, and every query is saved so you can check any number." width="100%">
</p>

Claude only sees query results, never the raw logs. Every query is saved under an ID like `Q46`. The answer cites
it, and `show_evidence` shows the exact SQL behind any number.


### SereneDB features we use

- **Files read in place:** views over `read_parquet`, `read_json` and `read_csv`, local or over HTTPS and S3
- **Parquet statistics:** `parquet_metadata` to skip row groups outside the time window and to predict a query's cost
- **Inverted index:** `CREATE INDEX … USING inverted(…)`, searched with `@@`, `ts_phrase` and `ts_levenshtein`
- **Query plans:** `EXPLAIN` before each query, so an expensive one is narrowed or sampled instead of run blind
- **Sampling:** `USING SAMPLE reservoir(…) REPEATABLE` for estimates that state their margin
- **Aggregation:** exact `count(*)` by group and time bucket, `quantile_cont` for latency percentiles
- **Roles:** a read-only reader and a writer that owns only the `extractor` schema, enforced by SereneDB when both are set

## Quick start

You need Docker, [uv](https://docs.astral.sh/uv/) and Claude Code.

```sh
git clone https://github.com/ugnmura/serenedb-extractor && cd serenedb-extractor
uv sync

# 1. start SereneDB (drop --platform on an x86-64 host)
mkdir -p ~/logs
docker run -d --name serenedb --platform linux/amd64 -e SERENEDB_HOST_AUTH_METHOD=trust \
  -p 127.0.0.1:7890:7890 -v ~/logs:/logs:ro \
  serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9

# 2. load BGL + OpenStack (downloads ~60 MB, takes about a minute)
export SERENEDB_READER_URL=postgresql://postgres@localhost:7890/postgres
export LOGS_HOST_DIR=~/logs LOGS_CONTAINER_DIR=/logs
uv run python scripts/load_base_corpus.py

# 3. connect Claude Code
claude mcp add serenedb-extractor \
  -e SERENEDB_READER_URL=$SERENEDB_READER_URL -e SERENEDB_ALLOW_SQL=1 \
  -e LOGS_HOST_DIR=$HOME/logs -e LOGS_CONTAINER_DIR=/logs \
  -- uv run --directory "$PWD" serenedb-extractor
```

Then run `claude` in this folder and ask:

```text
/engineer What failed on BGL on 11 June 2005, and what happened just before?
/team-lead Which problems keep recurring, and what should we look at first?
/manager What should we prioritise from these logs?
```

- **Apple Silicon:** use `serenedb/serenedb:26.09.2` (native arm64) and leave out `--platform`. The pinned image
  is slow and may crash under emulation.
- **Why a local SereneDB and our own loader:** the organisers' guidance says there is no pre-built loader, schema,
  ownership table or shared instance, so the quick start runs all of it locally.
- Passwords, reader and writer roles, other options: [docs/reference.md](docs/reference.md).


## Worked investigation: one corpus, three roles

The same agent answers one question per role over the base corpus: BGL (4,747,963 entries) and OpenStack
(207,636 entries). Each role gets different evidence and a different kind of action. All 25 tool calls took
0.02 s to 1.97 s each (median 0.25 s) with no index. `[step n]` points to the
[transcript](docs/worked-investigation-transcript.md), which holds every tool call, its result and the SQL that
ran. The full write-up is [docs/worked-investigation.md](docs/worked-investigation.md). BGL times are US Pacific,
the zone the log was written in.

### Engineer: "What failed on BGL, and what happened just before it?"

- **Found by:** `count_logs` on FATAL entries by node, full-text `search_logs`, `get_context`.
- **What failed:** one compute node, **R30-M0-N9-C:J16-U01**, produced **152,229 of BGL's 855,501 FATAL entries**
  (17.8%). The next node has 1,567 [step 2]. Almost all of them are `data TLB error interrupt`
  (152,182) [step 3], in one run on 11 June 2005 from 17:17:44 to 23:39:32 PDT [step 4].
- **Just before:** in the same second, the node logged `machine check interrupt (bit=0x10): L2 DCU read error`
  [step 5]. Nothing else on the machine was logged in the 10 minutes before [step 6]. That error appears only 3 times in the whole log,
  twice on this node [step 7].
- **Possible cause (hypothesis):** a faulty L2 data cache on the node's processor.
- **Next check:** run the processor and L2 diagnostics on that node. If they fail, take it out of the scheduler
  and replace the card. If they pass, look at the job that ran there at 17:17.

### Team lead: "Which problems keep recurring, and what should the team look at first?"

- **Found by:** `count_logs` over the whole corpus by team and level, `trend` by week and day, `survey`.
- **Whole-corpus counts by team** (fictional stand-in ownership table) [step 9]: Node OS 626,756 FATAL and HPC
  Applications 228,536 FATAL on BGL, Virtualization 3,071 WARNING on OpenStack.
- **Recurring:** "Link has been severed" (CioStream socket) on **22 of 31 days** in December, 14,616 entries, +4%
  against November [step 21]. Kernel fault storms are rarer but huge: 62% of all BGL FATAL entries fall in 9-15
  June [step 11]. On OpenStack, an image-cache warning appears in every hour at a steady rate [step 16].
- **Investigate first:** **HPC Applications**, the "Link has been severed" failures: the most persistent fatal
  problem, and not falling. Then Node OS, to confirm whether the 14 June event on about 22,500 nodes was a planned
  restart [steps 12, 13].

### Manager: "What should we prioritise, and what happens next?"

- **Found by:** `rank_problems` for December 2005 against November, scored on measured severity, change,
  persistence, spread and share [step 23]. The score orders the list. It is not a cost figure.

| # | risk (measured) | owner | next action |
|---|---|---|---|
| 1 | Broken links between compute and I/O nodes: FATAL, 22 of 31 days, 1,024 nodes, 31% of December's severe entries | HPC Applications | trace which I/O-node links drop |
| 2 | Failing job launches ("permission denied"), up 91% (7,296 → 13,952) | HPC Applications | review program-image permissions |
| 3 | Lustre mounts failing, up 716% (230 → 1,877) on 924 nodes | Node OS | check the mounts and their servers for those 4 days |
| 4 | One faulty node in June: 17.8% of all FATAL entries | Node OS | hardware diagnostics, out of service until it passes |

### What the data does and does not establish

Every number above is an exact count over every entry in scope. The counts are log entries, not incidents. Causes
are hypotheses. Downtime, cost and customer impact are not in the logs. A check against ground truth: a full-text
count of "data TLB error interrupt" over all of BGL gives **152,734**, exactly the number of lines BGL's own
labels mark as `KERNDTLB` [steps 24, 25].

### A second engineer finding: two 503s at 06:25 (OpenStack)

OpenStack's only 2 CRITICAL entries are failed token checks after Keystone answered `503`: at **06:25:02 on 16 May**
and **06:25:03 on 17 May**, the same minute a day apart. After the one on 17 May, polling of `servers/detail` fell
from about 2,830 to 12 requests an hour, and no VM finished starting from 07:00 to the end of the log. The
anomaly labels don't mark either one. **Hypothesis:** Ubuntu's daily cron job at 06:25 reloads Apache, which hosts
Keystone, and the client gives up instead of retrying. **Next check:** Keystone's Apache log and `/etc/crontab` on
the controller. Eight tool calls, all in [docs/keystone-503-transcript.md](docs/keystone-503-transcript.md).

## Tools

Claude picks these from their descriptions. Every result says how it was measured and when it was cut.

| tool | what it does |
|---|---|
| `describe_logs` | lists the log tables, their fields and time ranges. The starting point |
| `search_logs` | full-text search in a time window, returns matching entries |
| `get_context` | the events just before and after one entry |
| `count_logs` | exact counts by team, component, level or time, over one log table or all of them |
| `survey` | the most common kinds of message |
| `trend` | what is rising, falling or new compared with the period before |
| `rank_problems` | what to look at first, ranked by a stated, measured score |
| `show_evidence` | the exact SQL and result behind any cited number |

There are 18 tools in total, including setup, indexes and team ownership. Each one's inputs and outputs are listed in
[docs/reference.md](docs/reference.md#tools).


## Evidence

- **Counted in the database.** Counts cover every entry in scope, not a handful of examples. An estimate is
  labelled with its margin.
- **Every number is cited.** `[Q46]` next to a number means "run `show_evidence(['Q46'])` to see the query".
- **Facts and guesses are kept apart.** Causes are labelled as hypotheses, and each answer says what the logs do
  not show.
- **Checked against ground truth.** A full-text count of "data TLB error interrupt" over all of BGL gives 152,734,
  exactly the number of lines BGL's own labels mark as that alert.


## Limitations

- Counts are log entries, not incidents.
- The team-ownership table is a fictional stand-in. `edit_team_ownership` imports a real one.
- Log tables are snapshots and are not refreshed.
- The benchmarks ran at commit `6cad141`. Later changes were only rerun on the smaller screening set.

Full list: [docs/reference.md](docs/reference.md#known-limits).

## More

- [docs/worked-investigation.md](docs/worked-investigation.md): the full worked investigation
- [docs/EVALUATION.md](docs/EVALUATION.md): benchmark method, the three designs, templating scores
- [docs/HUGE_DATASETS.md](docs/HUGE_DATASETS.md): TextBench at 1 billion rows
- [docs/reference.md](docs/reference.md): requirements checklist, all tools, configuration, security, tests

Data: Loghub (Zhu et al., ISSRE 2023. BGL: Oliner & Stearley, DSN 2007), research use only.
