# Worked investigation: one corpus, three roles

Claude Code, connected to this MCP server, answers one question per role over the base corpus:
Loghub **BGL** (4,747,963 entries, 2005-06-03 to 2006-01-04) and **OpenStack** (207,636 entries,
2017-05-14 to 2017-05-17), loaded with `scripts/load_base_corpus.py`. Teams come from the **stand-in** ownership
table (`src/rcagent/data/ownership.csv`), a fictional organisation. Import the challenge's table
with `edit_team_ownership` to get its team names.

Every number cites a step of the [transcript](worked-investigation-transcript.md): each tool call, its result
and its queries (regenerate with `scripts/worked_investigation.py`). Live, citations are evidence handles
(`[Q12]`) for `show_evidence`. BGL times are US Pacific, the log's own zone (PDT = UTC-7 in June, PST = UTC-8 in December).
OpenStack times are UTC. "Exact" means every entry in scope was counted. "≈ … ±" is a sample estimate.

| | Engineer | Team lead | Manager |
|---|---|---|---|
| Question | What failed, where, and what happened just before? | What recurs, how often, which teams, what first? | What deserves attention first, and what happens next? |
| Evidence | Quoted messages, one node's timeline, nearby events | Whole-corpus counts by team and level, weekly and hourly trends, spread over nodes | A measured ranking (severity, change, persistence, spread, share), severity counts by team, month-over-month trend |
| Tools used | count_logs, search_logs (full text), get_context | count_logs, survey, locate_occurrences, trend, run_sql | rank_problems, count_logs, survey, trend |
| Recommendation | The next diagnostic check, with what each outcome means | What to investigate first, assigned to a team, with runners-up | A ranked list with an owning team and a next action each |

---

## 1. Engineer: "What failed on BGL, and what happened just before it?"

**Scope assumed:** log table `bgl`, all time, FATAL entries, US Pacific time.

### What failed

Node **R30-M0-N9-C:J16-U01** (owner **Node OS**, component KERNEL) produced **152,229 of the 855,501
FATAL entries** (17.8%). The next node has 1,567 [step 2]. Almost all are one message:

> `data TLB error interrupt`: **152,182 entries** (exact) [step 3], all on this node [step 12]

They form one run on **11 June 2005**. It starts at **17:17:44 PDT** (00:17:44 UTC on 12 June) [step 3] and lasts
through the 23:00 hour, at up to about 24,000 entries per hour [step 4].

### What happened just before and after

- On the node (±60 min), one entry comes first, in the same second [step 5]:
  `machine check interrupt (bit=0x10): L2 DCU read error`.
- On all nodes (±10 min), nothing else comes before it [step 6].
- "L2 DCU read error" appears **3 times in the whole corpus**: twice on this node (11 June 17:17:44 and
  13 June 04:47:27 PDT) and once on another node on 6 August [step 7].
- On 13 June, after the second L2 error, the node logged **46 more FATAL entries**. It logged no other
  severe entries [step 8].

### Possible cause (hypothesis, not established by the logs)

An L2 data-cache fault in this node's processor. A failing cache read would explain the kernel looping on
data TLB errors: it cannot resolve the faulting memory reference. The machine-check line comes first, the
rare error recurs on the node 35 hours later, and no other node is involved. The logs do **not** show
hardware state.

### Next check

Pull the RAS and hardware-diagnostic history for **R30-M0-N9-C:J16-U01** and its node card for 11-13 June,
and run the processor and L2 diagnostics.
- If they fail or show cache errors, take the node out of the scheduler and replace the card.
- If they pass, check the job running there at 17:17 PDT on 11 June. A software fault corrupting page
  tables would point to the application.

### What the logs do not establish

Whether a job was lost, or how long the node was down. 152,182 entries is one incident, logged repeatedly.

---

## 2. Team lead: "Which problems keep recurring, and what should the team look at first?"

**Scope assumed:** both log tables, all time, each in its own time zone. Counts are per log table, not merged.

### The numbers

| Team (ownership table) | BGL entries by level [step 9] | OpenStack entries by level [step 9] |
|---|---|---|
| Node OS | 626,756 FATAL, 3,698,211 INFO | |
| HPC Applications | 228,536 FATAL | |
| Control System | 88,529 ERROR, 49 FAILURE, 3 FATAL | |
| Hardware Reliability | 23,825 ERROR, 19,213 SEVERE, 23,356 WARNING, 1,665 FAILURE | |
| Virtualization | | 3,071 WARNING |
| Compute Service | | 45 WARNING, 8 ERROR |
| Identity & Access | | 2 CRITICAL, 2 ERROR, 2 WARNING |

### Recurring problems, ranked by presence, frequency and change

1. **Application launch and I/O-daemon failures on BGL (HPC Applications).** In December, "Error reading
   message prefix on CioStream socket … Link has been severed" appeared on **22 of 31 days** (14,616 entries,
   +4% against November). "Error loading … invalid or missing program image, Permission denied" rose **+91%**
   (7,296 → 13,952), but on only 3 days [step 21]. The APP component holds 36,064 of December's 44,888 FATAL
   entries [step 22].
2. **Kernel fault storms on BGL (Node OS).** Rare but huge. 62% of all BGL FATAL entries (531,058 of 855,501)
   fall in 9 to 15 June [step 11]. The calendar week of 13 June alone holds 380,987 (44.5%) [step 10]. Two shapes:
   - **one node** on 11 June: 152,182 data TLB errors on R30-M0-N9-C:J16-U01 [step 12].
   - **a machine-wide event** on 14 June, 09:00 to 12:00 PDT (16:00-19:00 UTC): 344,064 FATAL entries in
     three hours [step 13]. That week, "data storage interrupt" (63,488) and "instruction address" (47,110)
     each spread over **about 22,500 nodes** (22,528 and 22,530), at most 3 entries per node [step 12].
3. **The image-cache warning on OpenStack (Virtualization).** "Unknown base file: <path>" is 3,059 of the
   3,130 warnings and errors (98%) [step 14]. It appears in all 15 hours from 16 May 15:00 to 17 May 06:00 UTC,
   at 97 to 136 per hour [step 16]. No change is given: the logs have no entries on 15 May or from 07:00 to
   15:00 on 16 May [step 15], and the tool refuses to compare across the gap.
4. **Cloud API 404s (Cloud API).** 3,969 of the 102,868 nova-api entries are 404s (2,064 POST, 1,905 GET)
   [step 17]. With two 503s, 3,971 of 98,733 timed requests returned an error status. Latency is p50 0.26 s,
   p95 0.38 s, max 4.16 s [step 18].

### Investigate first

1. **HPC Applications: the CioStream "Link has been severed" failures.** The most persistent FATAL problem
   (22 of 31 days in December), not falling (+4%) [step 21]. The kernel storms are larger, but they are two
   concentrated incidents with a clear owner and next step.
2. **Node OS:** confirm whether the 14 June event was a planned restart [step 12, step 13].
3. **Virtualization:** decide whether the image-cache warning is noise or a cache leak. It is steady, so not urgent.

### What the counts do not tell

They count entries, not incidents. Many BGL messages arrive in bursts of 512 or 1,024, probably one per node
of a partition. Cause and user impact are not in the logs.

---

## 3. Manager: "What should we prioritise, and what happens next?"

**Scope assumed:** the whole base corpus. The ranking compares BGL's last full month, December 2005, with
November. The June incidents come from the all-time evidence.

`rank_problems` sets the order [step 23]. It counts every December problem at warning level or worse exactly
and scores severity, change, persistence (days present), spread (nodes) and share of ranked entries. The
score orders attention. It is not a risk or cost figure.

1. **Persistent broken links between compute and I/O nodes** (owner: **HPC Applications**). Ranked 1st
   (15 of 18, tied with the next three, first by entries). FATAL, on 22 of 31 days, on 1,024 nodes, 31% of
   the ranked entries (14,616), +4% against November [step 23, step 21]. **Next action:** HPC Applications
   with Interconnect to trace which I/O-node links drop.
2. **Failing job launches, rising** (owner: **HPC Applications**). Ranked 2nd (15 of 18). FATAL,
   "permission denied" when loading a program, up 91% (7,296 → 13,952), on 1,024 nodes, but on only 3 days
   [step 23, step 21]. The team holds 80% of December's fatal entries (36,064 of 44,888) [step 22].
   **Next action:** HPC Applications to review program-image permissions and job-submission checks.
3. **Lustre mounts failing on compute nodes, sharply up** (owner: **Node OS**). Ranked 4th (15 of 18), after
   a related "program image not found" error. FATAL, 230 → 1,877 entries (+716%), on 924 nodes over 4 days
   [step 23]. **Next action:** Node OS to check the Lustre mounts and servers for those days. A failed mount
   may explain the missing program images ranked 3rd (a hypothesis).
4. **One faulty compute node in June** (owner: **Node OS**). Outside the December ranking, where it would
   score low on spread. It produced 17.8% of all fatal entries (152,229) in one storm of about 6 hours,
   after a rare cache error that recurred 35 hours later [step 2, step 4, step 7, step 8].
   **Next action:** Node OS to run hardware diagnostics on R30-M0-N9-C:J16-U01 and keep it out of service
   until it passes.
5. **A machine-wide fault burst on 14 June** (owner: **Node OS**). FATAL, 344,064 entries in three hours
   (09:00-12:00 PDT) [step 13]. Its main messages that week each reach about 22,500 nodes [step 12]. One
   burst, not a trend. **Next action:** Node OS to confirm whether it was a planned restart. If not, run a
   post-incident review.

Lower priority: OpenStack shows warnings only. The image-cache warning repeats hourly (3,059 entries) and
3.9% of API calls return 404 [step 14, step 16, step 17]. Virtualization and Cloud API to confirm both are
expected. The logs do not measure customer impact, downtime or cost.

---

## What the data does and does not establish

- **Established (exact counts over the whole corpus):** where the fatal entries are, by team, node, day and
  hour. That one node produced 17.8% of them. That the 11 June run followed an L2 machine-check line. That
  the "Unknown base file" warning is steady. The 404 share of API calls.
- **Estimated:** only the survey's per-template counts for the week of 9 June (≈, ±1-4%, from a random
  sample of 100,000 of 531,058 entries) [step 11]. Every other number is exact.
- **Not established:** root causes (each cause above is a hypothesis), incident counts, downtime, user or
  customer impact, and anything on OpenStack during its gaps (15 May, 16 May 07:00-15:00).
- **A check against ground truth:** a full-text count of "data TLB error interrupt" over all of BGL gives
  **152,734** entries [step 24], exactly the number of lines BGL's own alert labels mark `KERNDTLB`
  [step 25]. 152,182 of them are the 11 June run. The survey estimated ≈153,000 ±1% [step 11].
