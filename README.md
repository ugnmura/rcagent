# serenedb-extractor

**Ask your logs a question in plain words. Get an answer that fits your role, with every number linked to the
query that produced it.**

Built for *Making Sense of Logs* (National AI Hackathon 2026, SereneDB track).

<p align="center">
  <img src="docs/img/flow.svg" alt="You ask Claude a question; Claude calls a serenedb-extractor tool; the tool runs SQL in SereneDB. Counts come back with an evidence ID (Q46), Claude answers citing it, and every query is saved so you can check any number." width="100%">
</p>

SereneDB does the searching and counting. Claude only sees the results, never the raw logs. Every query is saved
under an ID like `Q46`; the answer cites it, and `show_evidence` shows the exact SQL behind any number.

**Demo video:** _link to come_ · **Worked investigation:** [docs/worked-investigation.md](docs/worked-investigation.md)

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

Another SereneDB instance, passwords, or the supplied team-ownership table: see [docs/reference.md](docs/reference.md).

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
- **Every number is cited.** `[Q46]` next to a number means "run `show_evidence(['Q46'])` to see the query".
- **Facts and guesses are kept apart.** Causes are labelled as hypotheses, and each answer says what the logs do
  not show.
- **Checked against ground truth.** A full-text count of "data TLB error interrupt" over all of BGL gives 152,734,
  exactly the number of lines BGL's own labels mark as that alert.

## Limitations

- Counts are log entries, not incidents.
- The shipped team-ownership table is a fictional stand-in until the real one is imported.
- Log tables are snapshots; they are not refreshed.
- Timings were measured under emulation (arm64 Mac); real S3 timings for the large TextBench data were not measured.

Full list: [docs/reference.md](docs/reference.md#known-limits).

## More

- [docs/worked-investigation.md](docs/worked-investigation.md): one question per role, every number cited
  ([full transcript](docs/worked-investigation-transcript.md))
- [docs/reference.md](docs/reference.md): all tools, configuration, security, large datasets, tests

Data: Loghub (Zhu et al., ISSRE 2023; BGL: Oliner & Stearley, DSN 2007), research use only.
