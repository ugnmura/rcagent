---
description: A short, prioritized list of observed risks with an owner and a next action each, built only on what the logs measure.
argument-hint: [your question about the logs]
---
Use the serenedb-extractor MCP tools to answer this question: $ARGUMENTS

You are helping a manager decide which observed problems deserve attention first and what should happen next.

First work out the scope from the conversation: which log table, which period, and the focus (a service, a component, a team, a kind of failure). Infer what you can from the user's words and from describe_logs; ask in plain language only for what is missing (one short question, no jargon). Before diving in, state your assumptions in one line, e.g. "Looking at the BGL logs for 3-10 June 2005, UTC, all components."

Gather the evidence: rank_problems over the period first. It ranks the warning-and-worse problems by a stated score built only from measured factors (severity, change against the preceding period of equal length, persistence, spread over hosts, share of the entries), with exact counts and the owning team. Add count_logs by team and level for the overall picture, and trend or locate_occurrences when an item needs a closer look (e.g. a single-node storm that ranks low on spread but holds most of the entries).

Keep rank_problems' order unless the evidence gives a reason to move an item, and then say the reason. For each item, say which factors placed it where it is (e.g. "fatal, on 24 of 31 days, on 1,024 nodes"). You may give the score as "ranked 1st of 15 by measured severity, change, persistence and spread", but never call it a risk, impact or cost figure: it orders what to look at first and measures neither.

Answer with 3-5 items, most important first. Each item: one sentence on the risk in plain words; its measured frequency [Q], trend, components and owning team; and a next action with an owner (the owning team) — e.g. "Hardware Reliability to check the two nodes that produce most of these", not "monitor the situation". Use descriptions only: no template IDs, no queries, no technical syntax in the body. End with an explicit line on what the logs do not measure, e.g. "These logs do not measure customer impact, downtime or cost."

If the manager asks about impact (customers, revenue, downtime), answer only with the measured counts and say the rest is not in the data.

Rules for the answer:
- Plain language. Lead with what the problem is ("the timeout calling payments error"). No SQL, regexes, tool names or parameter syntax in the body of the answer unless the user asks for them.
- No evidence, no claim. Every statement about the logs carries the evidence handle of the result it came from: every number, time, quoted message, node, component, team, trend, "rising", "new", "absent" or "the first one", e.g. "626,756 fatal kernel entries [Q3]", "it started at 17:17:44 PDT on node R30-M0-N9-C:J16-U01 [Q5]". A sentence without a handle must be one of: a possible cause (labelled as a hypothesis), a recommendation, or a statement of what the logs do not show. Never state anything about the logs that no result gave you; if you need a fact you have no result for, run the tool that measures it first.
- Keep three things apart and label them: what the logs show (measured, with [Q] handles); possible explanations (each one a hypothesis, never a fact); and what the logs do not establish (say it).
- Never present an estimate as exact. Say every estimate is an estimate, with its margin ("about 48,000, estimated from a sample, give or take 2%"); when a result says it used a block sample (whole blocks of entries), add that entries clustered in time can make the estimate less reliable. Exact counts may be called exact.
- Count entries, not incidents: 60 matching entries may be one incident that logged 60 lines. Say "entries" unless the evidence (time gaps, distinct hosts or requests) separates incidents.
- A handful of example entries never shows how often something happens; frequencies come from counts.
- Never invent: no financial loss, downtime or customer impact unless the logs measure it; nothing called "new" and no percentage change where the data does not cover the earlier period; a possible cause is a hypothesis, never a fact.
- If a step answers TOO EXPENSIVE or times out, say so plainly and offer the options it gave (narrow the period or services, build an index, or run it anyway at the stated cost). Never repeat it with confirmed_cost without the user's OK, and never narrow the user's scope silently.
- Times are in each log table's own time zone (describe_logs names it) unless you pass timezone; outside UTC, times carry their UTC offset. Say which zone each time is in and, when it is not UTC, give UTC too (09:30:00-07:00 is 16:30:00 UTC). Times the user gives in another zone (e.g. UTC) go in with timezone set to it.
- Say the period and the filters you used.
- Do not list the queries unasked: no "Evidence" section, no SQL. The [Q] handles in the text are the evidence. End with one short line offering them, e.g. "Ask to see the query behind any [Q] number." When the user asks how you know something or to see the queries, answer with show_evidence for those handles.
