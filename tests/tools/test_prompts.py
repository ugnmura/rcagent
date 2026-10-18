"""Server instructions and the three audience prompts, checked at the MCP seam (no database)."""

import re

from serenedb_extractor.instructions import ANSWER_RULES, SERVER_INSTRUCTIONS
from serenedb_extractor.prompts import ENGINEER_PROMPT, MANAGER_PROMPT, PROMPTS as REGISTERED, TEAM_LEAD_PROMPT
from serenedb_extractor.telemetry import tool_annotations
from tests.conftest import Client

PROMPTS = {"engineer": ENGINEER_PROMPT, "team-lead": TEAM_LEAD_PROMPT, "manager": MANAGER_PROMPT}


async def test_fifteen_tools_and_annotations(mcp_no_db):
    tools = {t.name: t for t in (await mcp_no_db.list_tools()).tools}
    assert set(tools) == {"inspect_source", "setup_log_table", "create_index", "describe_logs", "survey", "locate_occurrences",
                          "extract_params", "trend", "get_context", "search_logs", "run_sql", "rename_parameter",
                          "count_logs", "show_evidence", "drop_index"} | set(tool_annotations())
    assert tools["create_index"].annotations.destructiveHint and tools["setup_log_table"].annotations.destructiveHint
    assert tools["survey"].annotations.readOnlyHint is False and tools["trend"].annotations.readOnlyHint is True


async def test_prompts_without_arguments(mcp_no_db):
    prompts = {p.name: p for p in (await mcp_no_db.list_prompts()).prompts}
    assert set(prompts) == {"engineer", "team-lead", "manager"} and all(not p.arguments for p in prompts.values())
    assert all(p.description for p in prompts.values())


async def test_get_prompt_returns_the_text(mcp_no_db: Client):
    for name, text in PROMPTS.items():
        result = await mcp_no_db.get_prompt(name)
        assert len(result.messages) == 1 and result.messages[0].role == "user"
        assert result.messages[0].content.text == text  # type: ignore[union-attr]


def test_instructions_sent_on_connect(mcp_no_db: Client):
    options = mcp_no_db.server._mcp_server.create_initialization_options()
    assert options.instructions == SERVER_INSTRUCTIONS


def test_manager_rules():
    m = MANAGER_PROMPT.lower()
    idx = [m.index(w) for w in ("severity", "trend", "persistence", "spread", "volume")]
    assert idx == sorted(idx) and "risk score" in m and "roughly equal" in m and "not measure" in m
    assert "fatal > error > warn" in m and "not in the data" in m and "3-5" in m


def test_instructions():
    s = SERVER_INSTRUCTIONS.lower()
    assert all(k in s for k in ("describe_logs", "survey", "estimate", "never invent", "spelling"))
    assert s.index("describe_logs") < s.index("survey")
    assert all(k in s for k in ("exclude", "confirmed_cost", "margin", "assum", "bracket"))


def test_every_prompt_infers_scope_asks_only_for_missing_and_states_assumptions():
    for text in PROMPTS.values():
        t = text.lower()
        assert all(k in t for k in ("log table", "period", "focus", "infer", "missing", "assumption"))
        assert all(k in t for k in ("estimate", "margin", "never invent", "plain language"))


def test_ids_scaled_to_audience():
    e, tl, m = (p.lower() for p in PROMPTS.values())
    assert "exact query" in e and "on request" in e and "[t" in e
    assert "ids at most" in tl
    assert "no template ids" in m


def test_engineer_workflow_order_and_hypothesis():
    e = ENGINEER_PROMPT.lower()
    steps = [e.index(w) for w in ("survey", "locate_occurrences", "get_context", "extract_params")]
    assert steps == sorted(steps)
    assert "hypothesis" in e and "next check" in e and "narrowest" in e


def test_team_lead_workflow():
    t = TEAM_LEAD_PROMPT.lower()
    steps = [t.index(w) for w in ("survey", "trend", "locate_occurrences")]
    assert steps == sorted(steps)
    assert all(k in t for k in ("preceding period", "presence", "frequency", "change", "ownership", "investigate first"))


async def test_texts_only_name_real_tools_and_parameters(mcp_no_db: Client):
    tools = (await mcp_no_db.list_tools()).tools
    known = {t.name for t in tools} | {p for t in tools for p in t.inputSchema.get("properties", {})}
    for text in [SERVER_INSTRUCTIONS, *PROMPTS.values()]:
        named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text))
        assert named <= known, named - known


async def test_prompts_registered_from_one_table(mcp_no_db: Client):
    listed = {p.name: p.description for p in (await mcp_no_db.list_prompts()).prompts}
    assert listed == {name: desc for name, (desc, _) in REGISTERED.items()}
    assert {name: text for name, (_, text) in REGISTERED.items()} == PROMPTS


def test_one_shared_set_of_answer_rules():
    assert ANSWER_RULES in SERVER_INSTRUCTIONS and all(ANSWER_RULES in p for p in PROMPTS.values())


def test_block_sample_caveat_matches_tool_wording():
    from pathlib import Path

    from serenedb_extractor.tools import investigate, lookup

    tool_text = "".join(Path(m.__file__ or "").read_text() for m in (investigate, lookup))
    assert "block sample" in tool_text
    assert "block sample" in ANSWER_RULES.lower() and "clustered in time" in ANSWER_RULES.lower()


def test_near_ties_say_how_to_get_exact_counts():
    m = MANAGER_PROMPT
    assert "exact=True" in m and "locate_occurrences" in m


def test_team_lead_surveys_the_whole_period_and_prioritises_in_the_report():
    t = TEAM_LEAD_PROMPT.lower()
    assert "whole period" in t and "no level filter" in t
    assert t.index("error and warn") > t.index("answer with")
