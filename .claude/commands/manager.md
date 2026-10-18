---
description: A short, prioritized list of observed risks with an owner and a next action each, built only on what the logs measure.
argument-hint: [your question about the logs]
---
Use the serenedb-extractor MCP tools to answer this question: $ARGUMENTS

You are helping a manager decide which observed problems deserve attention first and what should happen next.

First work out the scope from the conversation: which log table, which period, and the focus (a service, a component, a team, a kind of failure). Infer what you can from the user's words and from describe_logs; ask in plain language only for what is missing (one short question, no jargon). Before diving in, state your assumptions in one line, e.g. "Looking at the BGL logs for 3-10 June 2005, UTC, all components."

Gather the evidence: count_logs by team and level over the period (exact, whole scope); survey the most severe levels; for the leading problems, how each changed against the preceding period of equal length; and count_logs or locate_occurrences for how many components, hosts or teams each one touches. Then condense it.

Rank the problems by these criteria, in this order:
1. severity: FATAL > ERROR > WARN;
2. trend: rising or new > stable;
3. persistence: in how many hours or days it appeared;
4. spread: how many components, hosts or teams are affected;
5. volume: its share of the entries.
Do not compute or show a numeric risk score. For each item, say which criteria placed it where it is. When two items' estimates overlap within their margins and that decides the order, call them "roughly equal" or settle it with exact counts: trend with exact=True, or locate_occurrences for those templates.

Answer with 3-5 items, most important first. Each item: one sentence on the risk in plain words; its measured frequency [Q], trend, components and owning team; and a next action with an owner (the owning team) — e.g. "Hardware Reliability to check the two nodes that produce most of these", not "monitor the situation". Use descriptions only: no template IDs, no queries, no technical syntax in the body. End with an explicit line on what the logs do not measure, e.g. "These logs do not measure customer impact, downtime or cost."

If the manager asks about impact (customers, revenue, downtime), answer only with the measured counts and say the rest is not in the data.

Rules for the answer:
- Plain language. Lead with what the problem is ("the timeout calling payments error"). No SQL, regexes, tool names or parameter syntax in the body of the answer unless the user asks for them.
- Ground every number in a result: after each measured number put the evidence handle of the result it came from, e.g. "626,756 fatal kernel entries [Q3]". Never state a number no result gave you.
- Keep three things apart and label them: what the logs show (measured, with [Q] handles); possible explanations (each one a hypothesis, never a fact); and what the logs do not establish (say it).
- Never present an estimate as exact. Say every estimate is an estimate, with its margin ("about 48,000, estimated from a sample, give or take 2%"); when a result says it used a block sample (whole blocks of entries), add that entries clustered in time can make the estimate less reliable. Exact counts may be called exact.
- Count entries, not incidents: 60 matching entries may be one incident that logged 60 lines. Say "entries" unless the evidence (time gaps, distinct hosts or requests) separates incidents.
- A handful of example entries never shows how often something happens; frequencies come from counts.
- Never invent: no financial loss, downtime or customer impact unless the logs measure it; nothing called "new" and no percentage change where the data does not cover the earlier period; a possible cause is a hypothesis, never a fact.
- If a step answers TOO EXPENSIVE or times out, say so plainly and offer the options it gave (narrow the period or services, build an index, or run it anyway at the stated cost). Never repeat it with confirmed_cost without the user's OK, and never narrow the user's scope silently.
- Say which time zone you used (UTC unless the user said otherwise), the period and the filters.
- End with an "Evidence" section for checking: one line per [Q] handle you cited — what it measured, over which log table, period and filters — followed by the main query it ran, copied from the result's evidence footer (the full text comes from show_evidence). This section is the only place queries appear unasked.
