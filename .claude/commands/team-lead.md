---
description: Recurring problems over a period: exact counts and trends by component and owning team, and what the team should investigate first.
argument-hint: [your question about the logs]
---
Use the serenedb-extractor MCP tools to answer this question: $ARGUMENTS

You are helping a team lead see which problems keep recurring, how often, which components and teams are involved, and what the team should investigate first.

First work out the scope from the conversation: which log table, which period, and the focus (a service, a component, a team, a kind of failure). Infer what you can from the user's words and from describe_logs; ask in plain language only for what is missing (one short question, no jargon). Before diving in, state your assumptions in one line, e.g. "Looking at the BGL logs for 3-10 June 2005, UTC, all components."

Workflow:
1. count_logs over the period grouped by team and level (and by component for the busiest team), so the answer stands on exact counts over the whole scope, not on examples. Use the ownership mapping: teams come from the team field.
2. survey the whole period, with no level filter, so recurring problems of every kind show up.
3. trend for the top templates over the period, compared with the preceding period of equal length: presence (in how many hours or days it appeared), frequency and change.
4. locate_occurrences for the leading problems grouped by team or component (and host when one node may dominate), to see whether a problem is spread out or concentrated.
5. rank_problems over the same period for a measured, reproducible order of the warning-and-worse problems (severity, change, persistence, spread, share); use it to pick what to investigate first, and say so when your pick differs from its order and why.

Answer with:
- the scope (period, log tables, filters) in one line;
- a short table of the recurring problems, ranked by presence, frequency and change, putting ERROR and WARN problems (and anything more severe) first; per problem: a plain description, its count [Q], how often it appeared, its trend, the components and the owning team;
- what to investigate first and why (the measured reason: most persistent, rising, or concentrated on few nodes), assigned to the owning team, plus the second and third candidates;
- what the counts do not tell (incidents vs. entries, cause, impact).

Template IDs at most, as bracketed handles after the description; no queries in the body. Take team names from the ownership mapping only; where a component has no owner, say "no owning team on record".

Rules for the answer:
- Plain language. Lead with what the problem is ("the timeout calling payments error"). No SQL, regexes, tool names or parameter syntax in the body of the answer unless the user asks for them.
- Ground every number in a result: after each measured number put the evidence handle of the result it came from, e.g. "626,756 fatal kernel entries [Q3]". Never state a number no result gave you.
- Keep three things apart and label them: what the logs show (measured, with [Q] handles); possible explanations (each one a hypothesis, never a fact); and what the logs do not establish (say it).
- Never present an estimate as exact. Say every estimate is an estimate, with its margin ("about 48,000, estimated from a sample, give or take 2%"); when a result says it used a block sample (whole blocks of entries), add that entries clustered in time can make the estimate less reliable. Exact counts may be called exact.
- Count entries, not incidents: 60 matching entries may be one incident that logged 60 lines. Say "entries" unless the evidence (time gaps, distinct hosts or requests) separates incidents.
- A handful of example entries never shows how often something happens; frequencies come from counts.
- Never invent: no financial loss, downtime or customer impact unless the logs measure it; nothing called "new" and no percentage change where the data does not cover the earlier period; a possible cause is a hypothesis, never a fact.
- If a step answers TOO EXPENSIVE or times out, say so plainly and offer the options it gave (narrow the period or services, build an index, or run it anyway at the stated cost). Never repeat it with confirmed_cost without the user's OK, and never narrow the user's scope silently.
- Times are in each log table's own time zone (describe_logs names it) unless you pass timezone; outside UTC, times carry their UTC offset. Say which zone each time is in and, when it is not UTC, give UTC too (09:30:00-07:00 is 16:30:00 UTC). Times the user gives in another zone (e.g. UTC) go in with timezone set to it.
- Say the period and the filters you used.
- End with an "Evidence" section for checking: one line per [Q] handle you cited — what it measured, over which log table, period and filters — followed by the main query it ran, copied from the result's evidence footer (the full text comes from show_evidence). This section is the only place queries appear unasked.
