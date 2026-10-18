"""The slash commands in .claude/commands are the audience prompts, unchanged."""

import importlib.util
from pathlib import Path

from rcagent.prompts import PROMPTS

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("gen_commands", ROOT / "scripts" / "gen_commands.py")
gen = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(gen)  # type: ignore[union-attr]


def test_commands_match_the_prompts():
    for name in PROMPTS:
        path = ROOT / ".claude" / "commands" / f"{name}.md"
        assert path.read_text(encoding="utf-8") == gen.render(name), f"run scripts/gen_commands.py ({path.name})"
