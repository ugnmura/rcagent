# Evaluation: how well the agent answers with this server

On a sealed set of 30 held-out questions, Claude Opus 5.5 with this MCP server scored **96.9%** on a blind rubric
and **98%** on objective exact values, at **$0.117 per answer**. The questions cover the three roles plus
adversarial cases. That is the best of three designs the team built and compared. The weak spots are listed
below as well.

## Method

- **Questions.**
    - A separate Opus subagent wrote the sealed final set of 30 questions: engineer, team lead, manager and
      adversarial.
    - It saw only the brief, the raw schema, about 50 sample lines per dataset and the role descriptions. It had
      no database, no repository and no tool lists.
    - A separate Sonnet checker ran every golden answer's SQL against a neutral DuckDB copy of the raw corpus.
    - Alternative golden values were accepted where loader conventions differ: local time against UTC, and
      merged continuation lines.
- **Trials.**
    - Claude Opus 5.5 at high effort answered every question 5 times (k=5), 150 trials per design, split over
      two machines. All 450 trials ran without an infrastructure error.
    - Each nested `claude -p` session had only the server under test (`--strict-mcp-config`, no other tools)
      and the same prompt, role line, turn limit, timeout and server name for every design.
- **Grading.**
    - A blind Sonnet grader scored each answer against a fixed rubric. Tool names, terms and citations were
      redacted before grading.
    - "Exact" checks the answer's objective values against the golden values.
    - Confidence intervals are bootstrap over questions (rubric) and Wilson (exact).
- **Designs compared.** This server (the "extractor") and two earlier designs by the same team (v1 and v2),
  each in the setup its own README documents.

## Results

Finals, Opus 5.5 high effort, k=5, sealed set of 30 questions:

| Measure | **extractor** (`6cad141`) | v1 | v2 |
|---|---|---|---|
| Blind rubric | **96.9%** [94.6–98.7] | 92.9% [87.6–96.8] | 93.5% [88.8–96.8] |
| Paired rubric difference against the extractor | – | −4.0 pts [−8.8, −0.3] | −3.4 pts [−8.1, +0.1] |
| Objective exact values (125 trials) | **98%** [93–99] | 94% [89–97] | 96% [91–98] |
| Key facts (mechanical match, noisy) | 54% [46–62] | **67%** [59–74] | 63% [55–70] |
| USD per answer | **0.117** [0.111–0.122] | 0.459 [0.436–0.481] | 0.259 [0.243–0.276] |
| Tool calls per answer | **5.9** | 9.2 | 6.6 |
| Wall time per answer, median (indicative) | 35 s | 66 s | 38 s |

Other suites at the same commit:

| Measure | extractor | v1 | v2 |
|---|---|---|---|
| Localisation: right node and time at the first answer (Sonnet, k=3, 42 trials) | **100%** [92–100] | 100% | 86% |
| Templating accuracy, BGL (GA / FGA) | 0.929 / **0.745** | 0.939 / 0.694 | 0.939 / 0.694 |
| Templating accuracy, OpenStack (GA / FGA) | **0.355** / 0.682 | 1.000 / 1.000 | 1.000 / 1.000 |
| TextBench, 1 billion rows: search in a 60 s window | 2.88 s, plus a whole-file search in 4.2 s after a 70 s index build (at `6cad141`; at `b51daa1`: 1.71 s and 2.32 s, [HUGE_DATASETS.md](HUGE_DATASETS.md)) | not supported | 0.82 s, 60 s windows only |

## The current `main`

The finals ran at `6cad141`. `main` (`b022894`) adds the evidence log, teams and `count_logs`. It was rerun on
the screening set (Sonnet 5.5, k=3, 30 questions plus 14 localisation questions, SereneDB 26.09.2 arm64):

| Measure | `6cad141` | **`b022894`** |
|---|---|---|
| Blind rubric | 93.3% [91.3–95.3] | **94.4%** [88.7–97.8] |
| Objective exact values | 96% | **99%** |
| Localisation at the first answer | 100% | **100%** |
| USD per answer (Sonnet) | 0.036 | 0.064 |

Cost per answer rose 77%. Each tool result now carries its evidence footer (`Evidence [Qn]` and its SQL), so
results are 2.6 times longer, and there are 15 tools instead of 12. There is no Opus finals run at `b022894`.

## Weak spots and threats to validity

- **Key facts:** the mechanical key-fact match is lower than for the other two designs (54% against 63–67%),
  even though the rubric and exact scores are higher.
- **OpenStack templating is too coarse:** GET, POST and DELETE request lines fall into one template (GA 0.355).
- **Windowed TextBench search** is slower than a plain in-place view (2.88 s against 0.82 s).
- **Teams were not benchmarked:** at `6cad141` the extractor had no ownership table, so team questions were
  phrased by component.
- **Engine versions differ:** on Apple Silicon each design ran on the newest arm64 SereneDB image that supports
  its features (26.09.2 for the extractor, 26.09.1.3 for the others).
- **The benchmark is the team's own:** the extractor's author operated the coordinating machine. The question
  writing, grading, briefs and budgets were blind and identical for all three designs. The raw trial results
  and grading files are in the team's benchmark repository, which is private.
- **The held-out sets are spent:** both have now been run, so any further claim needs a fresh blind set.
