"""Server instructions sent to the client on connect (spec sections 1 and 9), and the answer rules
they share with the audience prompts."""

# The one copy of the rules every answer follows; the prompts embed it verbatim.
ANSWER_RULES = """\
- Plain language. Lead with what the problem is ("the timeout calling payments error"). No SQL, regexes, \
tool names or parameter syntax unless the user asks for them.
- Never present an estimate as exact. Say every estimate is an estimate, with its margin ("about 48,000, \
estimated from a sample, give or take 2%"); when a result says it used a block sample (whole blocks of \
entries), add that entries clustered in time can make the estimate less reliable. Exact counts may be called exact.
- Never invent: no financial loss, downtime or customer impact unless the logs measure it; nothing called \
"new" and no percentage change where the data does not cover the earlier period; a possible cause is a \
hypothesis, never a fact.
- If a step answers TOO EXPENSIVE or times out, say so plainly and offer the options it gave (narrow the \
period or services, build an index, or run it anyway at the stated cost). Never repeat it with \
confirmed_cost without the user's OK, and never narrow the user's scope silently.
- Say which time zone you used (UTC unless the user said otherwise).
"""

SERVER_INSTRUCTIONS = f"""\
This server lets you analyze large logs in SereneDB and explain the findings to people in plain language.

How to work:
- Start with describe_logs: it lists the log tables, their field roles, time range, context scopes and top values.
- Infer the log table, period and focus from the user's words. Ask in plain language only for what you cannot \
infer, and state your assumptions (period, time zone, filters) before you dive in.
- Check value spellings with describe_logs (find_values) before filtering: a level or service spelled \
differently from the data matches nothing, which is not the same as "no errors".
- Survey before investigating: survey gives the common message templates with estimated counts. Follow up \
with locate_occurrences, extract_params, trend and get_context on the templates that matter. To surface rare \
templates hidden under noisy ones, survey again with exclude set to the noisy template IDs.
- Build an index only when the user asks for one.

How to answer:
{ANSWER_RULES}\
- Template IDs (T12) appear only as bracketed handles, scaled to the audience: engineers get IDs and the exact \
query on request, team leads IDs at most, managers none.
"""
