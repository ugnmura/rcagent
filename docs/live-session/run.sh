#!/usr/bin/env bash
# The live sessions behind docs/live-session.md: one headless Claude Code session per role, with only this MCP
# server attached (--strict-mcp-config, no user settings). Base corpus loaded as in the README's quick start;
# fill in <checkout> and the URLs in mcp.json first.
set -u
cd "$(dirname "$0")"
run() { # name role question
  printf '%s\n' "/mcp__serenedb-extractor__$2 $3" > "$1.prompt.txt"
  claude -p "/mcp__serenedb-extractor__$2 $3" --model claude-opus-5-5 --strict-mcp-config --mcp-config mcp.json \
    --setting-sources "" --allowedTools "mcp__serenedb-extractor" --output-format stream-json --verbose --max-turns 40 \
    > "$1.jsonl" 2> "$1.err"
}
run engineer engineer "What failed on BGL on 11 June 2005, and what happened just before?" &
run team-lead team-lead "Which problems keep recurring across BGL and OpenStack, and what should we look at first?" &
run manager manager "What should we prioritise from these logs?" &
wait
# If a session asks a clarifying question, answer it once in the same session and keep both parts:
#   claude -p "<answer>" --resume <session_id> ... > <name>-2.jsonl   (and the answer in <name>-2.prompt.txt)
# docs/live-session.md is its hand-written header followed by body.md
python3 render.py body.md "Engineer:engineer.jsonl" "Team lead:team-lead.jsonl" "Manager:manager.jsonl"
