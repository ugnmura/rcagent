"""setup_metric_table: register long-format metrics (time, service, metric, value), read in place."""

import time
from datetime import UTC, datetime
from typing import Any

from mcp.types import ToolAnnotations

from serenedb_extractor import format as fmt
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident, validate_name
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup import localfiles
from serenedb_extractor.setup.paths import resolve_source
from serenedb_extractor.setup.roles import HELPER_COLUMNS, is_temporal
from serenedb_extractor.setup.sniff import readable, sample_values, sniff
from serenedb_extractor.telemetry.common import TIME_UNITS, epoch_us_sql, fmt_us, guess_epoch_unit
from serenedb_extractor.telemetry.registry import MetricTable, TelemetryStore
from serenedb_extractor.telemetry.roles import METRIC_CANDIDATES, METRIC_REQUIRED, is_numeric, pick_roles, unknown_roles
from serenedb_extractor.timezones import get_zone

TOOL_ANNOTATIONS: dict[str, tuple[bool | None, bool | None]] = {"setup_metric_table": (False, False)}
ROLE_NAMES = (*METRIC_CANDIDATES, "timestamp_unit")


def _wide_hint(columns: list[tuple[str, str]]) -> str:
    numeric = [c for c, t in columns if is_numeric(t)]
    if len(numeric) >= 5:
        return (
            f" It looks wide ({len(numeric)} numeric columns such as {', '.join(numeric[:3])}): metric tables need "
            "long format, one row per time, service, metric name and value. Convert it first (e.g. UNPIVOT)."
        )
    return ""


def setup_metric_table(
    ctx: AppContext, name: str, source: str, roles: dict[str, str | None] | None = None, timezone: str | None = None
) -> str:
    validate_name(name)
    zone = timezone or "UTC"
    get_zone(zone)
    unknown_roles(roles, ROLE_NAMES)
    store = TelemetryStore(ctx.db)
    if name in store.names_in_use():
        raise UserFacingError(f"The name '{name}' is already used by a log, metric or trace table; pick another.")
    rs = resolve_source(source, ctx.settings, None)
    if rs.kind == "raw_text":
        raise UserFacingError("Metric tables are read from Parquet, JSON or a table, not from raw text.")
    if localfiles.copy_needed(rs):
        raise UserFacingError(
            "This file is outside the mounted folder, so SereneDB cannot read it; metric tables are only read in "
            "place. Put it under the mounted folder."
        )
    began = time.perf_counter()
    info = sniff(ctx.db, rs, source, for_setup=True)
    columns = [(c, t) for c, t in info.columns if c not in HELPER_COLUMNS]
    types = dict(columns)
    given = {k: v for k, v in (roles or {}).items() if k != "timestamp_unit"}
    picked, why = pick_roles(columns, METRIC_CANDIDATES, given)
    missing = [r for r in METRIC_REQUIRED if picked.get(r) is None]
    if missing:
        raise UserFacingError(
            f"No column found for {', '.join(missing)} (columns: {', '.join(types)})."
            + _wide_hint(columns)
            + " Name them with roles, e.g. roles={'metric': 'name', 'value': 'v'}."
        )
    ts, value = str(picked["timestamp"]), str(picked["value"])
    if not is_numeric(types[value]):
        raise UserFacingError(f"The value column '{value}' is {types[value]}, not a number.")
    unit = (roles or {}).get("timestamp_unit")
    if is_temporal(types[ts]):
        unit = None
    elif not is_numeric(types[ts]):
        raise UserFacingError(f"The time column '{ts}' is {types[ts]}: it must be a timestamp or an epoch number.")
    elif unit is None:
        seen = [float(v) for v in sample_values(info).get(ts, []) if v.replace(".", "", 1).lstrip("-").isdigit()]
        if not seen:
            raise UserFacingError(f"Can't tell the unit of the epoch column '{ts}'; pass roles={{'timestamp_unit': 's'}}.")
        unit = guess_epoch_unit(max(seen))
        why["timestamp_unit"] = f"guessed from the magnitude of {max(seen):.0f}"
    elif unit not in TIME_UNITS:
        raise UserFacingError(f"timestamp_unit must be one of {', '.join(TIME_UNITS)}.")
    relation = f"extractor.mt_{name}"
    ts_sql = epoch_us_sql(quote_ident(ts), types[ts], unit, zone)
    svc = picked.get("service")
    with readable(source, rs.remote):
        ctx.db.write(f"CREATE OR REPLACE VIEW {relation} AS SELECT * FROM {info.from_sql}", {})
        try:
            agg = ctx.db.read(
                f"SELECT count(*) AS n, min({ts_sql}) AS t0, max({ts_sql}) AS t1, "
                f"count(DISTINCT {quote_ident(str(picked['metric']))}) AS metrics, "
                + (f"count(DISTINCT {quote_ident(svc)}) AS services " if svc else "0 AS services ")
                + f"FROM {relation}",
                {},
                what=f"counting the rows of {source}",
            ).dicts()[0]
            mt = MetricTable(
                name=name,
                source=source.strip(),
                source_format=rs.kind,
                relation=relation,
                timestamp=ts,
                timestamp_unit=unit,
                service=svc,
                metric=str(picked["metric"]),
                value=value,
                row_count=int(agg["n"]),
                timezone=zone,
                created_at=datetime.now(UTC).replace(tzinfo=None),
            )
            store.create_metric_table(mt)
        except Exception:
            ctx.db.write(f"DROP VIEW IF EXISTS {relation}", {})
            raise
    metric_names = _top_values(ctx, relation, mt.metric, 40)
    services = _top_values(ctx, relation, svc, 40) if svc else []
    lines = [
        fmt.how_measured("metric table registered; the source's metadata, 5 sample rows and one count were read"),
        f"Set up metric table '{name}': read in place by SereneDB (nothing is copied). View {relation}.",
        f"rows: {mt.row_count:,}",
        f"time range (UTC): {fmt_us(agg['t0'])} to {fmt_us(agg['t1'])}",
        f"services ({agg['services']}): " + (", ".join(services) if services else "none (no service column)"),
        f"metric names ({agg['metrics']}): " + ", ".join(metric_names),
        f"setup took {fmt.duration(time.perf_counter() - began)}",
        "roles:",
        *(f"  {r}: {picked.get(r) or 'absent'}" + (f"  ({why[r]})" if r in why else "") for r in METRIC_CANDIDATES),
        f"  timestamp_unit: {unit or 'none (a timestamp column)'}"
        + (f"  ({why['timestamp_unit']})" if "timestamp_unit" in why else ""),
        f"time zone for timestamps without one: {zone}",
    ]
    return "\n".join(lines)


def _top_values(ctx: AppContext, relation: str, column: str | None, limit: int) -> list[str]:
    if column is None:
        return []
    rows = ctx.db.read(
        f"SELECT DISTINCT CAST({quote_ident(column)} AS VARCHAR) AS v FROM {relation} ORDER BY 1 LIMIT {int(limit) + 1}", {}
    ).rows
    vals = [str(r[0]) for r in rows]
    return vals[:limit] + (["…"] if len(vals) > limit else [])


_setup_metric_table = setup_metric_table  # the registered tool below shadows the name


def register(mcp: Any, runner: Any) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def setup_metric_table(
        name: str, source: str, roles: dict[str, str | None] | None = None, timezone: str | None = None
    ) -> str:
        """Register metrics so the change tools can use them. Metrics must be in long format: one row per time, service, metric name and value (Parquet, JSON or a table; read in place, nothing copied).
        Use when: a system has metrics next to its logs. Name its tables with one shared prefix (e.g. shop_logs, shop_metrics, shop_traces) so telemetry_overview and the change tools find them together.
        Inputs: name; source (path or table); roles to correct the guesses: timestamp, service, metric, value, timestamp_unit (s|ms|us|ns, for an epoch-number time column); timezone for timestamps without one (default UTC).
        Returns: roles and why, row count, time range, services and metric names."""
        return await runner.run_tool(
            _setup_metric_table, name=name, source=source, roles=roles, timezone=timezone
        )


