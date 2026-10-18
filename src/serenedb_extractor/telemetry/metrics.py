"""metric_changes, metric_series: filled in by slice A2 (spec: docs/superpowers/specs/2026-10-18-metrics-traces-design.md)."""

from typing import Any

TOOL_ANNOTATIONS: dict[str, tuple[bool | None, bool | None]] = {}


def register(mcp: Any, runner: Any) -> None:
    """Registers this module's tools; add each tool's annotations to TOOL_ANNOTATIONS."""
