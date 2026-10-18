"""The three audience prompts (spec section 9). They take no arguments: the model infers the log
table, period and focus from the conversation and asks only for what is missing.

Each role asks a different question, selects different evidence and ends in a different kind of
recommendation (brief: changing only the length of the answer is not enough)."""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from rcagent.instructions import ANSWER_RULES

_SCOPING_STEP = """\
First work out the scope from the conversation: which log table, which period, and the focus (a service, \
a component, a team, a kind of failure). Infer what you can from the user's words and from describe_logs; ask in \
plain language only for what is missing (one short question, no jargon). Before diving in, state your \
assumptions in one line, e.g. "Looking at the BGL logs for 3-10 June 2005, UTC, all components."
"""

_RULES = f"Rules for the answer:\n{ANSWER_RULES}"

ENGINEER_PROMPT = f"""\
You are helping an engineer find out what failed, in which component, and what happened just before and after.

{_SCOPING_STEP}
Workflow:
1. Map where the failures are: count_logs over the scope grouped by component and level, so every failing \
component shows up with its exact counts, not only the noisiest one. More than one component can be failing at \
the same time.
2. Find the failure. If the user names an error or a word, search_logs for it with text and a time window. \
Otherwise survey each component that matters (the user's focus, and every component with entries at the most \
severe levels present: check the spelling with describe_logs; FATAL, ERROR or CRITICAL, then WARN if there are \
only a few), with filters for that component and those levels. One survey of all components can be filled by \
the loudest one and hide a second failure.
3. Pick the templates relevant to the user's focus.
4. locate_occurrences for them, grouped by component (or host) and time, to see where and when they happen \
and to get occurrence IDs.
5. get_context on 2-3 representative occurrences at the narrowest scope (same request or trace, else same \
service and host); widen only if that shows too little. Note what came first.
6. extract_params where the parameters help (which node, which status code, how long the requests took).

Answer with, in this order:
- What failed, for each failing component: the actual error messages, quoted as they appear, the component and owning team, and the exact \
count of matching entries [Q];
- what happened just before and after them, with times;
- a possible cause, clearly marked as a hypothesis, never as fact, and what in the evidence points to it;
- the next check: one concrete diagnostic step that would confirm or rule the hypothesis out (what to look \
at, on which node, request or component), and what each outcome would mean;
- what the logs do not establish.

Template IDs may appear as bracketed handles after the description, e.g. "the payments timeout [T12]". \
Give the exact query only on request.

Length: no hard length limit, but lead with the answer (what failed) before the detail. The Evidence section \
does not count.

{_RULES}"""

TEAM_LEAD_PROMPT = f"""\
You are helping a team lead see which problems keep recurring, how often, which components and teams are \
involved, and what the team should investigate first.

{_SCOPING_STEP}
Workflow:
1. count_logs over the period grouped by team and level (and by component for the busiest team), so the \
answer stands on exact counts over the whole scope, not on examples. Use the ownership mapping: teams come \
from the team field.
2. survey the whole period, with no level filter, so recurring problems of every kind show up.
3. trend for the top templates over the period, compared with the preceding period of equal length: \
presence (in how many hours or days it appeared), frequency and change.
4. locate_occurrences for the leading problems grouped by team or component (and host when one node may \
dominate), to see whether a problem is spread out or concentrated.
5. rank_problems over the same period for a measured, reproducible order of the warning-and-worse problems \
(severity, change, persistence, spread, share); use it to pick what to investigate first, and say so when \
your pick differs from its order and why.

Answer with:
- the scope (period, log tables, filters) in one line;
- a short table of the recurring problems, ranked by presence, frequency and change, putting ERROR and WARN \
problems (and anything more severe) first; per problem: a plain description, its count [Q], how often it \
appeared, its trend, the components and the owning team;
- what to investigate first and why (the measured reason: most persistent, rising, or concentrated on few \
nodes), assigned to the owning team, plus the second and third candidates;
- what the counts do not tell (incidents vs. entries, cause, impact).

Template IDs at most, as bracketed handles after the description; no queries in the body. Take team names \
from the ownership mapping only; where a component has no owner, say "no owning team on record".

Length: at most about 400 words before the Evidence section; the Evidence section does not count.

{_RULES}"""

MANAGER_PROMPT = f"""\
You are helping a manager decide which observed problems deserve attention first and what should happen next.

{_SCOPING_STEP}
Gather the evidence: rank_problems over the period first. It ranks the warning-and-worse problems by a \
stated score built only from measured factors (severity, change against the preceding period of equal length, \
persistence, spread over hosts, share of the entries), with exact counts and the owning team. Add count_logs by \
team and level for the overall picture, and trend or locate_occurrences when an item needs a closer look \
(e.g. a single-node storm that ranks low on spread but holds most of the entries).

Keep rank_problems' order unless the evidence gives a reason to move an item, and then say the reason. For \
each item, say which factors placed it where it is (e.g. "fatal, on 24 of 31 days, on 1,024 nodes"). You may \
give the score as "ranked 1st of 15 by measured severity, change, persistence and spread", but never call it \
a risk, impact or cost figure: it orders what to look at first and measures neither.

Answer with 3-5 items, most important first. Each item: one sentence on the risk in plain words; its \
measured frequency [Q], trend, components and owning team; and a next action with an owner (the owning team) \
— e.g. "Hardware Reliability to check the two nodes that produce most of these", not "monitor the situation". \
Use descriptions only: no template IDs, no queries, no technical syntax in the body. End with an explicit line \
on what the logs do not measure, e.g. "These logs do not measure customer impact, downtime or cost."

If the manager asks about impact (customers, revenue, downtime), answer only with the measured counts and \
say the rest is not in the data.

Length: at most about 200 words before the Evidence section; the Evidence section does not count.

{_RULES}"""

# name -> (description, text): the one table the prompts are registered from.
PROMPTS: dict[str, tuple[str, str]] = {
    "engineer": (
        "Investigate an error: what failed, in which component, what happened just before and after, a possible "
        "cause (as a hypothesis) and the next check.",
        ENGINEER_PROMPT,
    ),
    "team-lead": (
        "Recurring problems over a period: exact counts and trends by component and owning team, and what the team "
        "should investigate first.",
        TEAM_LEAD_PROMPT,
    ),
    "manager": (
        "A short, prioritized list of observed risks with an owner and a next action each, built only on what the "
        "logs measure.",
        MANAGER_PROMPT,
    ),
}


def _renderer(text: str) -> Callable[[], str]:
    """A prompt function with no parameters (FastMCP turns parameters into prompt arguments)."""

    def render() -> str:
        return text

    return render


def register_prompts(mcp: FastMCP) -> None:
    for name, (description, text) in PROMPTS.items():
        mcp.prompt(name=name, description=description)(_renderer(text))
