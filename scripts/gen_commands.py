"""Write the Claude Code slash commands /engineer, /team-lead and /manager (.claude/commands/) from the
server's audience prompts, so they never drift apart (tests/test_commands.py checks they match).

    uv run python scripts/gen_commands.py
"""

from pathlib import Path

from serenedb_extractor.prompts import PROMPTS

ROOT = Path(__file__).resolve().parents[1]
HEADER = """---
description: {description}
argument-hint: [your question about the logs]
---
Use the rcagent MCP tools to answer this question: $ARGUMENTS

"""


def render(name: str) -> str:
    description, text = PROMPTS[name]
    return HEADER.format(description=description) + text


def main() -> None:
    out = ROOT / ".claude" / "commands"
    out.mkdir(parents=True, exist_ok=True)
    for name in PROMPTS:
        (out / f"{name}.md").write_text(render(name), encoding="utf-8")
        print(f"wrote {out / f'{name}.md'}")


if __name__ == "__main__":
    main()
