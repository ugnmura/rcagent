"""Metric and trace tables and the change tools (ADR-0004).

Each module registers its own tools (`register(mcp, runner)`) and declares their annotations in
`TOOL_ANNOTATIONS` as (readOnlyHint, destructiveHint), so parallel work never edits the same file.
Modules are imported lazily: catalog.schema and the context import parts of this package.
"""

from importlib import import_module
from typing import Any

MODULES = ("metric_setup", "trace_setup", "overview", "metrics", "traces", "log_changes")


def _modules() -> list[Any]:
    return [import_module(f"rcagent.telemetry.{m}") for m in MODULES]


def register_telemetry_tools(mcp: Any, runner: Any) -> None:
    for module in _modules():
        module.register(mcp, runner)


def tool_annotations() -> dict[str, tuple[bool | None, bool | None]]:
    out: dict[str, tuple[bool | None, bool | None]] = {}
    for module in _modules():
        out.update(module.TOOL_ANNOTATIONS)
    return out
