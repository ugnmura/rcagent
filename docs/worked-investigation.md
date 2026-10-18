# Worked investigation: one corpus, three roles

The same agent (Claude Code connected to this MCP server) answers one question per role over the base
corpus: Loghub **BGL** (4,747,963 entries, 2005-06-03 to 2006-01-04) and **OpenStack** (207,636 entries,
2017-05-14 to 2017-05-17), loaded with `scripts/load_base_corpus.py`. Teams come from the **stand-in** ownership
table (`src/serenedb_extractor/data/ownership.csv`, a fictional organisation we wrote, see the README); with the
challenge's own table imported (`edit_team_ownership`), the same steps give its team names.

Every number below cites a step of the **transcript**, [docs/worked-investigation-transcript.md](worked-investigation-transcript.md).
The transcript holds each tool call, its result and the exact queries that ran. Regenerate it with
`scripts/worked_investigation.py`. In a live session the same citations appear as evidence handles (`[Q12]`)
that `show_evidence` resolves. BGL times are US Pacific local time, the zone BGL logs were written in
(PDT, UTC-7, in June; PST, UTC-8, in December), with UTC added where it matters; OpenStack times are UTC.
"Exact" means counted over every entry in scope inside SereneDB. "≈ … ±" is an estimate from a stated sample.

The three answers use different evidence and recommend different kinds of action:

| | Engineer | Team lead | Manager |
|---|---|---|---|
| Question | What failed, where, and what happened just before? | What recurs, how often, which teams, what first? | What deserves attention first, and what happens next? |
| Evidence | Quoted messages, one node's timeline, nearby events | Whole-corpus counts by team and level, weekly and hourly trends, spread over nodes | A measured ranking (severity, change, persistence, spread, share), severity counts by team, month-over-month trend |
| Tools used | count_logs, search_logs (full text), get_context | count_logs, survey, locate_occurrences, trend, run_sql | rank_problems, count_logs, survey, trend |
| Recommendation | The next diagnostic check, with what each outcome means | What to investigate first, assigned to a team, with runners-up | A ranked list with an owning team and a next action each |

---

## 1. Engineer: "What failed on BGL, and what happened just before it?"

**Scope assumed:** log table `bgl`, all time, FATAL entries, US Pacific time (the log's own).

### What failed

A single compute node, **R30-M0-N9-C:J16-U01** (owned by **Node OS**, component KERNEL), produced
**152,229 of the 855,501 FATAL entries** in the whole log: 17.8%, more than any other node by a factor of
100. The next node has 1,567 [step 2]. Almost all of them are one message:

> `data TLB error interrupt`: **152,182 entries** (exact) [step 3], every one on this node [step 12]

These arrived as one continuous run on **11 June 2005, from 17:17:44 to 23:39:32 PDT** (00:17:44 to 06:39:32 UTC on 12 June),
at about 24,000 entries per hour [step 4].

### What happened just before and after

- On the node itself (±60 min, same host), only one entry precedes the run, in the same second [step 5]:
  `machine check interrupt (bit=0x10): L2 DCU read error`. Then the TLB errors start at 17:17:44.
- Across the whole machine (±10 min, all nodes), nothing else was logged before it [step 6]. The run
  starts on this node alone.
- "L2 DCU read error" is rare. It appears **3 times in the whole corpus**: twice on this node (11 June
  17:17:44 and 13 June 04:47:27 PDT) and once on another node on 6 August [step 7].
- On 13 June, after the second L2 error, the node logged **46 more FATAL entries**. It logged no other
  severe entries in the whole period [step 8].

### Possible cause (hypothesis, not established by the logs)

An L2 data-cache fault on this node's processor. A failing cache read would explain why the kernel then
loops on data TLB errors: it cannot resolve the faulting memory reference. The evidence fits: the
machine-check line comes first, the same rare error recurs on the same node 35 hours later, and no other
node or event is involved. The logs do **not** show the hardware state, so this stays a hypothesis.

### Next check

Pull the RAS and hardware-diagnostic history for **R30-M0-N9-C:J16-U01** (and its node card) for 11-13 June,
and run the processor/L2 diagnostics on it.
- If the diagnostics fail or show cache errors, take the node out of the scheduler and replace the card.
- If they pass, look at the job that ran on the node at 17:17 PDT on 11 June. A software fault that corrupts page
  tables would point to the application instead.

### What the logs do not establish

They don't show whether a job was lost or how long the node was unavailable. 152,182 entries is one
incident logging repeatedly, not 152,182 incidents.

---

## 2. Team lead: "Which problems keep recurring, and what should the team look at first?"

**Scope assumed:** the whole base corpus (both log tables, all time), each in its own time zone (BGL US Pacific,
OpenStack UTC). Counts are per log table and are reported together, not merged.

### The numbers

| Team (ownership table) | BGL entries by level [step 9] | OpenStack entries by level [step 9] |
|---|---|---|
| Node OS | 626,756 FATAL, 3,698,211 INFO | — |
| HPC Applications | 228,536 FATAL | — |
| Control System | 88,529 ERROR, 49 FAILURE, 3 FATAL | — |
| Hardware Reliability | 23,825 ERROR, 19,213 SEVERE, 23,356 WARNING, 1,665 FAILURE | — |
| Virtualization | — | 3,071 WARNING |
| Compute Service | — | 45 WARNING, 8 ERROR |
| Identity & Access | — | 2 CRITICAL, 2 ERROR, 2 WARNING |

### Recurring problems, ranked by presence, frequency and change

1. **Application launch and I/O-daemon failures on BGL (HPC Applications).** These recur throughout the period.
   In December, "Error reading message prefix on CioStream socket … Link has been severed" appeared on
   **22 of 31 days** (14,616 entries, +4% against November). "Error loading … invalid or missing program image,
   Permission denied" rose **+91%** (7,296 → 13,952), but appeared on only 3 days [step 21]. Together
   they make up most of December's FATAL entries: 36,064 of 44,888 come from the APP component [step 22].
2. **Kernel fault storms on BGL (Node OS).** These are rare but huge. 62% of all BGL FATAL entries
   (531,058 of 855,501) fall in the seven days from 9 to 15 June [step 11]; by calendar week (Monday to Sunday),
   the week of 13 June alone holds 380,987, 45% [step 10]. Two different shapes:
   - a **single node** on 11 June: 152,182 data TLB errors on R30-M0-N9-C:J16-U01 [step 12];
   - a **machine-wide event** on 14 June between 09:00 and 12:00 PDT (16:00-19:00 UTC), with 344,064 FATAL
     entries in those three hours [step 13]. "data storage interrupt" (63,488) and "instruction address" (47,110) are each spread
     over about **22,500 different nodes**, a few entries per node [step 12].
3. **The image-cache warning on OpenStack (Virtualization).** "Unknown base file: <path>" makes up 3,059 of the
   3,130 warnings and errors (98%) [step 14]. It appears in **every hour** the logs cover, at a steady
   ~125-135 per hour [step 16]. No change is given: the logs have a gap (no entries at all on 15 May
   or from 07:00 to 15:00 on 16 May [step 15]), and the tool refuses to compare across it.
4. **Cloud API 404s (Cloud API).** 3,969 of the 102,868 nova-api entries are 404 responses (2,064 POST,
   1,905 GET) [step 17]; with the two 503s, 3,971 of the 98,733 timed requests returned an error status [step 18]. API latency is p50 0.26 s, p95 0.38 s, max 4.16 s over 98,733 timed requests [step 18].

### Investigate first

**HPC Applications: the CioStream "Link has been severed" failures.** It is the most persistent FATAL
problem (22 of 31 days in December) and is not falling (+4%) [step 21]. The kernel storms are larger, but
they are two concentrated incidents with a clear owner and next step (see the engineer answer and the
manager list). Second: **Node OS** to confirm the 14 June event was a planned or machine-wide restart,
since it touched about 22,500 nodes in three hours [step 12, step 13]. Third: **Virtualization** to decide
whether the image-cache warning is benign noise to silence or a real cache leak. It is steady, so not urgent.

### What the counts do not tell

They count entries, not incidents. Many recurring BGL messages arrive in bursts of 512 or 1,024 entries,
probably one per node of a partition. Cause and user impact are not in the logs.

---

## 3. Manager: "What should we prioritise, and what happens next?"

**Scope assumed:** the whole base corpus. The ranking covers BGL's most recent full month, December 2005,
against November (Pacific calendar days); the June incidents are added from the all-time evidence.

The order comes from `rank_problems` [step 23]: every warning-and-worse problem of December, counted exactly
and scored on measured severity, change against November, persistence (days present), spread (nodes) and
share of December's severe entries. The score orders what to look at first; it is not a risk or cost figure.

1. **Persistent broken links between compute and I/O nodes** (owner: **HPC Applications**). Ranked 1st
   (15 of 18, tied with the next three and first by entries). It is FATAL, on 22 of 31 days in December, on
   1,024 nodes, and holds 31% of December's severe entries (14,616). It is not falling (+4% against November) [step 23, step 21]. **Next action:** HPC
   Applications with Interconnect to trace which I/O-node links drop, since this is the most persistent fatal
   problem.
2. **Failing job launches, rising** (owner: **HPC Applications**). Ranked 2nd (15 of 18). FATAL, up 91% for
   one cause: "permission denied" when loading a program, 7,296 → 13,952 entries, on 1,024 nodes, but on only
   3 days [step 23, step 21]. The applications team accounts for 80% of December's fatal entries (36,064 of
   44,888) [step 22]. **Next action:** HPC Applications to review program-image permissions and job-submission
   checks for the paths in these errors.
3. **Lustre file-system mounts failing on compute nodes, sharply up** (owner: **Node OS**). Ranked 4th
   (15 of 18, after a related "program image not found" error of the applications team). FATAL, 230 → 1,877
   entries (+716%), on 924 nodes over 4 days [step 23]. **Next action:** Node OS to check the Lustre mounts and
   their servers for those 4 days. A failed mount is one possible explanation (a hypothesis) for the missing
   program images ranked 3rd.
4. **One faulty compute node in June** (owner: **Node OS**). Outside the December ranking, and a ranking would
   place it low on spread (one node), but it produced 17.8% of all fatal entries in the log (152,229) in one
   6-hour storm, after a rare cache hardware error that recurred 35 hours later [step 2, step 7, step 8].
   **Next action:** Node OS to run hardware diagnostics on node R30-M0-N9-C:J16-U01 and keep it out of service
   until it passes.
5. **A machine-wide fault burst on 14 June** (owner: **Node OS**). FATAL, 344,064 entries in three hours
   (09:00-12:00 PDT) across about 22,500 nodes [step 12, step 13]. It is a single burst, not a trend.
   **Next action:** Node OS to confirm whether it was a planned restart. If it was not, run a post-incident review.

Lower priority: on OpenStack, warnings only. An image-cache warning repeats every hour (3,059 entries) and 3.9%
of API calls return 404 [step 14, step 17]; Virtualization and Cloud API to confirm both are expected behaviour.

These logs do not measure customer impact, downtime or cost; the counts above are log entries, not incidents.

---

## What the data does and does not establish

- **Established (exact counts over the whole corpus):** where the fatal entries are, by team, node,
  day and hour; that one node produced 17.8% of them; that the run on 11 June followed an L2
  machine-check line; that the "Unknown base file" warning is steady; the 404 share of API calls.
- **Estimated:** only the survey's per-template counts for the week of 9 June (≈ with ±1-4% from a random
  sample of 100,000 of 531,058 entries) [step 11]. Every other number above is exact.
- **Not established:** root causes (each cause above is a hypothesis), incident counts, downtime, user or
  customer impact, and anything on OpenStack during its gaps (15 May; 16 May 07:00-15:00).
- **A check against ground truth:** a full-text count of "data TLB error interrupt" over all of BGL gives
  **152,734** entries [step 24], exactly the number of lines BGL's own alert labels mark as `KERNDTLB`
  [step 25]. 152,182 of them are the 11 June run on one node. The survey's sampled estimate for the
  template was ≈153,000 ±1% [step 11].
