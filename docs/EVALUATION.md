# Evaluation: how well the agent answers with this server

On 30 sealed, held-out questions, Claude Opus 5.5 with this MCP server scored **96.9%** on a blind rubric and
**98%** on objective exact values, at **$0.117 per answer**. That is the best of the team's three designs. Weak
spots are at the end.

## Method

- **Questions.**
    - A separate Opus subagent wrote them: engineer, team lead, manager and adversarial. It saw only the brief,
      the raw schema, about 50 sample lines per dataset and the role descriptions. No database, repository or
      tool lists.
    - A separate Sonnet checker ran every golden answer's SQL on a neutral DuckDB copy of the raw corpus.
      Alternative golden values were accepted where loader conventions differ (local time against UTC, merged
      continuation lines).
- **Trials.** Opus 5.5 at high effort answered each question 5 times (k=5), 150 trials per design on two machines.
  None of the 450 trials hit an infrastructure error. Each nested `claude -p` session had only the server under
  test (`--strict-mcp-config`, no other tools) and the same prompt, role line, turn limit, timeout and server name.
- **Grading.** A blind Sonnet grader scored each answer on a fixed rubric, with tool names, terms and citations
  redacted. "Exact" compares objective values with the golden values. Intervals are bootstrap over questions
  (rubric) and Wilson (exact).
- **Designs.** This server and the team's two earlier designs, "18 fixed tools" (v1 in the benchmark repo) and
  "7 fixed tools" (v2), each in the setup its README documents. See
  [The three designs compared](#the-three-designs-compared).

## Results

Finals (Opus 5.5, high effort, k=5, 30 sealed questions):

| Measure | **Drain3 + 18 tools** (`6cad141`) | 18 fixed tools | 7 fixed tools |
|---|---|---|---|
| Blind rubric | **96.9%** [94.6–98.7] | 92.9% [87.6–96.8] | 93.5% [88.8–96.8] |
| Paired rubric difference against the extractor | – | −4.0 pts [−8.8, −0.3] | −3.4 pts [−8.1, +0.1] |
| Objective exact values (125 trials) | **98%** [93–99] | 94% [89–97] | 96% [91–98] |
| Key facts (mechanical match, noisy) | 54% [46–62] | **67%** [59–74] | 63% [55–70] |
| USD per answer | **0.117** [0.111–0.122] | 0.459 [0.436–0.481] | 0.259 [0.243–0.276] |
| Tool calls per answer | **5.9** | 9.2 | 6.6 |
| Wall time per answer, median (indicative) | 35 s | 66 s | 38 s |

Other suites at the same commit:

| Measure | Drain3 + 18 tools | 18 fixed tools | 7 fixed tools |
|---|---|---|---|
| Localisation: right node and time at the first answer (Sonnet, k=3, 42 trials) | **100%** [92–100] | 100% | 86% |
| Templating accuracy, BGL (GA / FGA) | 0.929 / **0.745** | 0.939 / 0.694 | 0.939 / 0.694 |
| Templating accuracy, OpenStack (GA / FGA) | **0.355** / 0.682 | 1.000 / 1.000 | 1.000 / 1.000 |
| TextBench, 1 billion rows: search in a 60 s window | 2.88 s, plus a whole-file search in 4.18 s after a 69.9 s index build (at `6cad141`). At `b51daa1`: 1.71 s and 2.32 s ([HUGE_DATASETS.md](HUGE_DATASETS.md)) | not supported | 0.82 s, 60 s windows only |

## The current `main`

The finals ran at `6cad141`. `main` (`b022894`) adds the evidence log, teams and `count_logs`. It was rerun on
the screening set (Sonnet 5.5, k=3, 30 questions plus 14 localisation questions, SereneDB 26.09.2 arm64):

| Measure | `6cad141` | **`b022894`** |
|---|---|---|
| Blind rubric | 93.3% [91.3–95.3] | **94.4%** [88.7–97.8] |
| Objective exact values | 96% | **99%** |
| Localisation at the first answer | 100% | **100%** |
| USD per answer (Sonnet) | 0.036 | 0.064 |

Cost per answer rose 77%. Each tool result now carries an evidence footer (`Evidence [Qn]` and its SQL), which
makes results 2.6 times longer, and there are 15 tools instead of 12. There is no Opus finals run at `b022894`.

## The three designs compared

All three are MCP servers over the same SereneDB data, built by the same team:

| | **Drain3 + 18 tools** (this server) | **18 fixed tools** ([serenedb-log-mcp](https://github.com/OrFrederick/serenedb-log-mcp)) | **7 fixed tools** ([serenedb-log-mcp-v2](https://github.com/OrFrederick/serenedb-log-mcp-v2)) |
|---|---|---|---|
| Data | Parquet/JSON read in place, also from S3, raw text copied once | copied into tables at load | copied into tables at load, TextBench read in place |
| Templates | at question time: SQL masking, then Drain, kept as stable IDs `T1, T2, …` | at load time: Loghub template regexes, then a regex mask chain | at load time: the regex mask chain only |
| Tools Claude sees | 12 tools at `6cad141` (26 now), including `run_sql` and setup | 18 tools: incidents, precursors, patterns, baselines, … | 7 tools, each extra tool had to win a benchmark |
| Evidence | every query saved as `Q<n>`, with its SQL | evidence ledger `[E<n>]` plus `verify_answer` | evidence ledger `[E<n>]` |
| Roles | prompts and slash commands | `role` parameter on every tool | `role` parameter on every tool |

## Templating: better grouping than Drain on the full Loghub-2.0 data

How well log lines are grouped into templates, over every labelled line of Loghub-2.0's full BGL (4,631,261 lines,
320 templates) and OpenStack (207,632 lines, 48 templates). GA is the share of lines in exactly the right group. FGA
is the F1 score over groups and punishes splitting one template into many. Higher is better.

| Approach | BGL GA | BGL FGA | OpenStack GA | OpenStack FGA |
|---|---|---|---|---|
| **Drain3 + 18 tools** (this server, `6cad141`) | 0.929 | **0.745** | 0.355 | 0.682 |
| 18 / 7 fixed tools (regex mask chain¹) | **0.939** | 0.694 | **1.000** | **1.000** |
| Drain (the standard parser), Loghub-2.0's tuned settings | 0.919 | 0.624 | 0.752 | 0.007 |
| *AEL (published)* | *0.915* | *0.587* | *0.743* | *0.682* |
| *IPLoM (published)* | *0.896* | *0.692* | *0.375* | *0.029* |
| *UniParser (published, trained model)* | *0.549* | *0.641* | *1.000* | *1.000* |
| *LogPPT (published, trained model)* | *0.311* | *0.519* | *0.534* | *0.929* |

We ran the plain rows with one scorer on 2026-10-18 (drain3 0.9.11 for Drain). Italic rows are copied from the
Loghub-2.0 paper
([`effectiveness_results.csv`](https://github.com/logpai/loghub-2.0/blob/ac4aad2ea86f561e5a0acbc6587fa28b487259f9/RQs_experiments/RQ2/effectiveness_results.csv),
full-dataset column), not rerun. They are comparable: our Drain run with Loghub's settings matches the paper's
Drain numbers to three decimals (BGL 0.919 / 0.624, OpenStack 0.752 / 0.007).

The extractor has the best BGL FGA here, trained models included: more of its templates match the real ones one
to one. On OpenStack it ties AEL, the best untrained published parser, on FGA. Its GA is low because GET, POST and
DELETE request lines fall into one template.

¹ By default the 18-tool server also matches regexes built from the Loghub-2.0 templates, which would score the
labels against themselves. That tier is off here, so both fixed-tool servers score the same.

## RCAEval: logs, metrics and traces

The metric and trace tools were tested on [RCAEval](https://github.com/phamquiluan/RCAEval): microservice failures
in Online Boutique, Sock Shop and Train Ticket, with logs, metrics and traces and a known faulty service. The agent
answers "which service is the root cause?" and ends with a ranking. AC@1 counts a first pick that is right, AC@3 a
right service in the top three. The hypotheses were fixed before the first scored run.

| Set | Tools | k | Trials | AC@1 | AC@3 |
|---|---|---|---|---|---|
| **Held-out** (116 cases, primary) | **logs, metrics, traces** (no `run_sql`) | 3 | 348 | **96.3%** (335/348) | 99.1% (345/348) |
| Held-out | same plus `run_sql` | 1 | 116 | 97.4% (113/116) | 100% |
| Held-out | BARO (RCAEval's non-LLM method) | | 116 | 21% | 90% |
| Test (48 cases of issue #23) | logs only (`b022894`) | 1 | 48 | 56% (27/48) | 58% |
| Test | **logs, metrics, traces** | 1 | 48 | **100%** (48/48) | 100% |
| Test | same plus `run_sql` | 1 | 48 | 100% (48/48) | 100% |
| Test | BARO | | 48 | 23% | 92% |

Held-out, logs, metrics and traces, by subset:

| Subset | Trials | AC@1 | AC@3 |
|---|---|---|---|
| Online Boutique, resource faults | 90 | 100% | 100% |
| Sock Shop, resource faults | 87 | 95.4% | 100% |
| Train Ticket, resource faults | 84 | 95.2% | 96.4% |
| Sock Shop, code faults | 87 | 94.3% | 100% |

- **Pre-registered hypothesis H1** (held-out resource faults, AC@1 at least 0.90): confirmed at 96.9% (253/261).
- **Logs alone miss resource faults.** On the test set AC@1 rose from 56% to 100%, all of it on CPU, memory, disk
  and network faults (Online Boutique resource faults: 30% to 100%). Code faults were already at 100% with logs.
  The metric and trace tools were also cheaper per answer ($0.30 against $0.54).
- **Misses** are mostly network-loss faults (Sock Shop and Train Ticket, 11 of 15 each) and Sock Shop code faults.
- **No regression for log users:** all 627 tests passed at the frozen build. The log benchmark was not rerun on it.

Comparability: extractor `785b7ba` (tag `metrics-traces-freeze-1`), Sonnet 5.5, no effort override, 40 turns,
1,200 s timeout, a fresh SereneDB 26.10.1 container per trial holding only that case, scored with RCAEval's
`score_rca` on the last `RANKING:` line. Case IDs are new (seed 20261018) and a leak scan found nothing. The held-out
set is RE2 (resource faults) for all three systems plus RE3 (code faults) for Sock Shop. Not comparable with the
7-tool design's earlier 1.00 (Opus, k=1, other case IDs). The test set is at its ceiling (bare SQL also scored 1.00
there), so its 100% shows parity only. BARO reads raw metric names and ranks every service, so it is a reference,
not a contestant. The trials and report are in the team's private benchmark repository.

## Weak spots and threats to validity

- **Key facts:** 54% against 63–67% for the other designs, despite higher rubric and exact scores.
- **OpenStack templating is too coarse** (GA 0.355). See [Templating](#templating-better-grouping-than-drain-on-the-full-loghub-20-data).
- **Windowed TextBench search** is slower than a plain in-place view (2.88 s against 0.82 s).
- **Teams were not benchmarked:** `6cad141` had no ownership table, so team questions named components.
- **Engine versions differ:** on Apple Silicon each design ran on the newest arm64 SereneDB image supporting its features
  (26.09.2 for the extractor, 26.09.1.3 for the others).
- **The benchmark is the team's own:** the extractor's author ran the coordinating machine. Question writing,
  grading, briefs and budgets were blind and identical for all designs. Raw trials and grading files are in the
  team's private benchmark repository.
- **The held-out sets are spent:** further claims need a fresh blind set.
