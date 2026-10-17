"""The three audience prompts (spec section 9). They take no arguments: the model infers the log
table, period and focus from the conversation and asks only for what is missing."""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from serenedb_extractor.instructions import ANSWER_RULES

_SCOPING_STEP = """\
First work out the scope from the conversation: which log table, which period, and the focus (a service, \
a component, a kind of failure). Infer what you can from the user's words and from describe_logs; ask in \
plain language only for what is missing (one short question, no jargon). Before diving in, state your \
assumptions in one line, e.g. "Looking at the payments logs for the last 24 hours, UTC."
"""

_RULES = f"Rules for the answer:\n{ANSWER_RULES}"

ENGINEER_PROMPT = f"""\
You are helping an engineer find out what failed, where, and why.

{_SCOPING_STEP}
Workflow:
1. survey the period with filters for ERROR entries (check the level spelling with describe_logs); if \
there are only a few, survey WARN entries too.
2. Pick the templates relevant to the user's focus.
3. locate_occurrences for them, grouped by component (or service) and time, to see where and when they happen.
4. get_context on 2-3 representative occurrences at the narrowest scope (same trace, else same service and \
host); widen only if that shows too little.
5. extract_params where the parameters help (which host, which status code, how long the timeouts were).

Answer with:
- the actual error messages, quoted as they appear;
- what happened just before and after them;
- a possible cause, clearly marked as a hypothesis, never as fact;
- the next check that would confirm or rule it out.

Template IDs may appear as bracketed handles after the description, e.g. "the payments timeout [T12]". \
Give the exact query only on request.

{_RULES}"""

TEAM_LEAD_PROMPT = f"""\
You are helping a team lead see which problems keep recurring and what to investigate first.

{_SCOPING_STEP}
Workflow:
1. survey the whole period, with no level filter, so recurring problems of every kind show up.
2. trend for the top templates over the period, compared with the preceding period of equal length: \
presence (in how many hours or days it appeared), frequency and change.
3. Components involved, from the survey breakdown; if it is affordable, get exact counts per component with \
locate_occurrences grouped by component or service.

Answer with:
- the recurring problems, ranked by presence, frequency and change, putting ERROR and WARN problems first; \
each described in plain words;
- the components involved in each;
- what to investigate first and why.

Template IDs at most, as bracketed handles after the description; no queries unless asked. Leave ownership \
to the reader: do not guess who owns a component.

{_RULES}"""

MANAGER_PROMPT = f"""\
You are helping a manager decide which observed problems deserve attention first and what should happen next.

{_SCOPING_STEP}
Gather the same evidence as for a team lead (survey over the period, how each problem changed against \
the preceding period, components affected), then condense it.

Rank the problems by these criteria, in this order:
1. severity: FATAL > ERROR > WARN;
2. trend: rising or new > stable;
3. persistence: in how many hours or days it appeared;
4. spread: how many components are affected;
5. volume: its share of the entries.
Do not compute or show a numeric risk score. For each item, say which criteria placed it where it is. When \
two items' estimates overlap within their margins and that decides the order, call them "roughly equal" or \
settle it with exact counts: trend with exact=True, or locate_occurrences for those templates.

Answer with 3-5 items, each with its measured frequency, trend, components affected and a next action. \
Use descriptions only: no template IDs, no queries, no technical syntax. End with an explicit line on what \
the logs do not measure, e.g. "These logs do not measure customer impact, downtime or cost."

If the manager asks about impact (customers, revenue, downtime), answer only with the measured counts and \
say the rest is not in the data.

{_RULES}"""

# name -> (description, text): the one table the prompts are registered from.
PROMPTS: dict[str, tuple[str, str]] = {
    "engineer": (
        "Investigate what failed, where, what happened around it, a possible cause and the next check.",
        ENGINEER_PROMPT,
    ),
    "team-lead": (
        "Recurring problems over a period: how often, trend, components, and what to investigate first.",
        TEAM_LEAD_PROMPT,
    ),
    "manager": (
        "A short, prioritized list of observed problems and next actions, built only on what the logs measure.",
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
