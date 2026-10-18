<div align="center">

# serenedb-extractor

<h3>Ask your logs in plain words. Every number in the answer links to the SQL that produced it.</h3>

[![MCP server](https://img.shields.io/badge/MCP-server-2a78d6?style=for-the-badge)](https://modelcontextprotocol.io)
[![Built on SereneDB](https://img.shields.io/badge/built%20on-SereneDB-9865e8?style=for-the-badge)](https://serenedb.com)
[![National AI Hackathon 2026](https://img.shields.io/badge/National%20AI%20Hackathon-2026-fbe5f5?style=for-the-badge)](#)

</div>

An MCP server that lets Claude investigate millions of log lines for three people: an **engineer** chasing an
error, a **team lead** looking for recurring problems, and a **manager** deciding what comes first. SereneDB does
the searching and counting; Claude explains the results. Built for *Making Sense of Logs* (SereneDB track).

**Demo video:** _link to come_ · **Worked investigation:** [docs/worked-investigation.md](docs/worked-investigation.md)

## Benchmarks

### 96.9% on 30 sealed held-out questions, at $0.117 per answer

<img src="docs/img/bench-quality.svg" alt="Answer quality on 30 sealed held-out questions: this server scores 96.9% on a blind rubric (v1 92.9%, v2 93.5%), 98% on exact values (94%, 96%), costs $0.117 per answer ($0.459, $0.259) and uses 5.9 tool calls per answer (9.2, 6.6)." width="100%">

A separate model wrote the questions without seeing this repository; a blind grader scored the answers. These
finals ran at commit `6cad141`. The current version, rerun on the screening set with Sonnet 5.5, scored 94.4% on
the rubric and 99% on exact values. Method, confidence intervals and weak spots: [docs/EVALUATION.md](docs/EVALUATION.md).

### 1 billion rows on S3, queried in place

<img src="docs/img/bench-textbench.svg" alt="TextBench, 1 billion rows read in place on S3: search of the whole file with the index 4.18 s, exact search of a 60-second window without an index 2.88 s, survey 7.8 s; registering the S3 file 1.97 s, building the search index 69.9 s." width="100%">

One TextBench file (`part_000.parquet`) straight from the public bucket, nothing downloaded, at commit `6cad141`
on one shared HPC node. The search index over a billion rows needs more than 64 GB of RAM. Raw per-call logs:
[docs/HUGE_DATASETS.md](docs/HUGE_DATASETS.md).

### The base corpus: 25 tool calls, median 0.25 s

In the worked investigation over BGL and OpenStack (4,955,599 entries, no index), every one of the 25 tool calls
took between 0.02 s and 1.97 s, 0.25 s at the median, including exact counts over the whole corpus. Each timing is
in the [transcript](docs/worked-investigation-transcript.md); the machine it ran on was not recorded.

## How it works

<p align="center">
  <img src="docs/img/flow.svg" alt="You ask Claude a question; Claude calls a serenedb-extractor tool; the tool runs SQL in SereneDB. Counts come back with an evidence ID (Q46), Claude answers citing it, and every query is saved so you can check any number." width="100%">
</p>

Claude only sees query results, never the raw logs. Every query is saved under an ID like `Q46`; the answer cites
it, and `show_evidence` shows the exact SQL behind any number.

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

- **Apple Silicon:** use `serenedb/serenedb:26.09.2` (native arm64) and leave out `--platform`; the pinned image
  is slow and may crash under emulation.
- **Why a local SereneDB and our own loader:** the organisers' guidance says there is no pre-built loader, schema,
  ownership table or shared instance, so the quick start runs all of it locally.
- Passwords, reader and writer roles, other options: [docs/reference.md](docs/reference.md).

## Three roles, three kinds of answer

| role | asks | gets |
|---|---|---|
| **Engineer** | What failed, and what happened around it? | the error messages, nearby events, a possible cause (labelled as a hypothesis) and the next check |
| **Team lead** | What keeps recurring? | counts by team, trends over a stated period, and what to investigate first |
| **Manager** | What should we prioritise? | 3-5 ranked risks, each with an owning team and a next action |

For example, the engineer answer from the worked investigation:

> One node, R30-M0-N9-C:J16-U01, produced 152,229 of BGL's 855,501 FATAL entries (17.8%) in one run on 11 June
> 2005. Just before it, the node logged a rare `L2 DCU read error`. **Hypothesis:** a faulty L2 cache. **Next
> check:** run hardware diagnostics on that node.

## Tools

Claude picks these from their descriptions. Every result says how it was measured and when it was cut.

| tool | what it does |
|---|---|
| `describe_logs` | lists the log tables, their fields and time ranges; the starting point |
| `search_logs` | full-text search in a time window; returns matching entries |
| `get_context` | the events just before and after one entry |
| `count_logs` | exact counts by team, component, level or time, over one log table or all of them |
| `survey` | the most common kinds of message |
| `trend` | what is rising, falling or new compared with the period before |
| `rank_problems` | what to look at first, ranked by a stated, measured score |
| `show_evidence` | the exact SQL and result behind any cited number |

There are 18 tools in total, including setup, indexes and team ownership. Each one's inputs and outputs are listed in
[docs/reference.md](docs/reference.md#tools).

## Why the numbers can be trusted

- **Counted in the database.** Counts cover every entry in scope, not a handful of examples. An estimate is
  labelled with its margin.
- **No evidence, no claim.** Every statement about the logs is cited: `[Q46]` next to a number, time or message means "run `show_evidence(['Q46'])` to see the query".
- **Facts and guesses are kept apart.** Causes are labelled as hypotheses, and each answer says what the logs do
  not show.
- **Checked against ground truth.** A full-text count of "data TLB error interrupt" over all of BGL gives 152,734,
  exactly the number of lines BGL's own labels mark as that alert.

## Limitations

- Counts are log entries, not incidents.
- The team-ownership table is fictional: the organisers supplied none.
- Log tables are snapshots; they are not refreshed.
- The benchmarks above ran at commit `6cad141`; later changes were only rerun on the smaller screening set.

Full list: [docs/reference.md](docs/reference.md#known-limits).

## More

- [docs/worked-investigation.md](docs/worked-investigation.md): one question per role, every number cited
  ([full transcript](docs/worked-investigation-transcript.md))
- [docs/EVALUATION.md](docs/EVALUATION.md) and [docs/HUGE_DATASETS.md](docs/HUGE_DATASETS.md): how the benchmarks
  were run
- [docs/live-session.md](docs/live-session.md): live, unscripted Claude sessions, one question per role, with every
  tool call the agent chose and the raw sessions
- [docs/INDEX_TIMINGS.md](docs/INDEX_TIMINGS.md): base-corpus queries with and without a search index, and the
  index build times
- [docs/reference.md](docs/reference.md): the requirements checklist, all tools, configuration, security, tests

Data: Loghub (Zhu et al., ISSRE 2023; BGL: Oliner & Stearley, DSN 2007), research use only.
