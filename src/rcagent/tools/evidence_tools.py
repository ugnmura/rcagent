"""show_evidence: the queries and results behind earlier answers, by their Q<n> handles."""

from rcagent import evidence
from rcagent.context import AppContext
from rcagent.errors import UserFacingError

MAX_IDS = 10


def show_evidence(ctx: AppContext, ids: list[str] | None = None, include_result: bool = True) -> str:
    if not ids:
        recent = ctx.evidence.recent(20)
        if not recent:
            return "The evidence log is empty: no tool has run a query yet."
        lines = ["The most recent evidence records (newest first); pass their IDs to see the queries and results:"]
        for rec in recent:
            args = ", ".join(f"{k}={v!r}" for k, v in rec.args.items() if v not in (None, "", [], {}))
            lines.append(
                f"  [{rec.handle}] {rec.created_at:%Y-%m-%d %H:%M:%S} UTC {rec.tool}({args}): "
                f"{len(rec.queries)} query(ies)"
            )
        return "\n".join(lines)
    if len(ids) > MAX_IDS:
        raise UserFacingError(f"Ask for at most {MAX_IDS} evidence records at once.")
    out: list[str] = []
    for raw in ids:
        n = evidence.parse_id(raw)
        found = ctx.evidence.get(n)
        if found is None:
            out.append(f"[Q{n}] not found: it may come from another database or was never recorded.")
            continue
        out.append(evidence.full_text(found, include_result))
    return "\n\n".join(out)
