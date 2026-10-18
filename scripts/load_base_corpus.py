"""Load the base corpus (Loghub BGL and OpenStack) into SereneDB as two log tables: `bgl` and `openstack`.

    uv run python scripts/load_base_corpus.py --data-dir ~/logs/loghub

Steps (each is skipped when its output already exists; --force redoes them):
1. download BGL.zip and OpenStack.tar.gz from Zenodo into --data-dir and unpack them;
2. parse the raw lines into one Parquet file per dataset (columns below), in batches;
3. set up the log tables through the extractor itself (setup_log_table), reading the Parquet in place.

SereneDB has to be able to read the Parquet files. Either keep --data-dir under the folder mounted into the
container (LOGS_HOST_DIR / LOGS_CONTAINER_DIR, as in the README), or pass --docker-cp <container> to copy the
two files into the container. Connection settings come from the same environment variables as the server
(SERENEDB_READER_URL, SERENEDB_WRITER_URL, LOGS_HOST_DIR, LOGS_CONTAINER_DIR).

Schema written:
  bgl:       entry_id, ts, level, component, node (host), event_type, alert_label (NULL for non-alerts), message
  openstack: entry_id, ts, level, component, service (nova-api/-compute/-scheduler), log_file, pid, request_id,
             user_id, tenant_id, instance_id, client_ip, http_method, http_path, status, response_bytes,
             latency_s, anomaly_instance (TRUE for the four instances labelled with injected anomalies), source_file, message
"""

import argparse
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

ZENODO = "https://zenodo.org/records/8196385/files/{name}?download=1"
BATCH = 250_000
ROW_GROUP = 50_000  # entries per Parquet row group: many small blocks keep block-sampled estimates tight

BGL_LINE = re.compile(
    r"^(?P<label>\S+) (?P<epoch>\d+) (?P<date>\S+) (?P<node>\S+) "
    r"(?P<time>\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}(?:\.\d+)?) (?P<noderepeat>\S+) "
    r"(?P<type>\S+) (?P<component>\S+) (?P<level>\S+)(?: (?P<content>.*))?$"
)
# Fallback for the few lines that lack the repeated node name or carry stray text before the event type:
# the type (RAS or NULL) followed by a known level anchors the tail.
BGL_LOOSE = re.compile(
    r"^(?P<label>\S+) (?P<epoch>\d+) (?P<date>\S+) (?P<node>\S+) "
    r"(?P<time>\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}(?:\.\d+)?) (?:.*? )?"
    r"(?P<type>RAS|NULL) (?P<component>\S+) (?P<level>INFO|WARNING|SEVERE|ERROR|FATAL|FAILURE)(?: (?P<content>.*))?$"
)
BGL_LEVELS = {"INFO", "WARNING", "SEVERE", "ERROR", "FATAL", "FAILURE"}

OS_LINE = re.compile(
    r"^(?P<file>\S+) (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}(?:\.\d+)?) "
    r"(?P<pid>\d+) (?P<level>[A-Z]+) (?P<component>\S+)(?: (?:\[(?P<ctx>[^\]]*)\] ?)?(?P<content>.*))?$"
)
OS_CTX = re.compile(r"^(?P<req>req-[0-9a-f-]+)(?: (?P<user>\S+) (?P<tenant>\S+))?")
OS_INSTANCE = re.compile(r"\[instance: (?P<id>[0-9a-f-]{36})\]")
OS_HTTP = re.compile(
    r'^(?P<ip>\S+) "(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" status: (?P<status>\d+) len: (?P<len>\d+) '
    r"time: (?P<time>[\d.]+)"
)

BGL_SCHEMA = pa.schema(
    [
        ("entry_id", pa.int64()),
        ("ts", pa.timestamp("us", tz="UTC")),
        ("level", pa.string()),
        ("component", pa.string()),
        ("node", pa.string()),
        ("event_type", pa.string()),
        ("alert_label", pa.string()),
        ("message", pa.string()),
    ]
)
OS_SCHEMA = pa.schema(
    [
        ("entry_id", pa.int64()),
        ("ts", pa.timestamp("us", tz="UTC")),
        ("level", pa.string()),
        ("component", pa.string()),
        ("service", pa.string()),
        ("log_file", pa.string()),
        ("pid", pa.int32()),
        ("request_id", pa.string()),
        ("user_id", pa.string()),
        ("tenant_id", pa.string()),
        ("instance_id", pa.string()),
        ("client_ip", pa.string()),
        ("http_method", pa.string()),
        ("http_path", pa.string()),
        ("status", pa.int32()),
        ("response_bytes", pa.int64()),
        ("latency_s", pa.float64()),
        ("anomaly_instance", pa.bool_()),
        ("source_file", pa.string()),
        ("message", pa.string()),
    ]
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- download


def download(data_dir: Path, force: bool) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, unpacked, unpack in (
        ("BGL.zip", data_dir / "BGL" / "BGL.log", _unzip),
        ("OpenStack.tar.gz", data_dir / "OpenStack" / "openstack_normal1.log", _untar),
    ):
        if unpacked.exists() and not force:
            log(f"{unpacked} exists; skipping download")
            continue
        archive = data_dir / name
        if not archive.exists() or force:
            log(f"downloading {name} from Zenodo …")
            urllib.request.urlretrieve(ZENODO.format(name=name), archive)  # noqa: S310 (fixed https URL)
        log(f"unpacking {name}")
        unpack(archive, data_dir / name.split(".")[0])


def _unzip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)


def _untar(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as t:
        t.extractall(dest, filter="data")


# ---------------------------------------------------------------- parsing


def _bgl_ts(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, "%Y-%m-%d-%H.%M.%S.%f").replace(tzinfo=UTC)
    except ValueError:
        return None


def bgl_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            m = BGL_LINE.match(line)
            if m is None or m["level"] not in BGL_LEVELS:
                m = BGL_LOOSE.match(line) or m
            if m is None:  # a handful of malformed lines: keep them, unparsed, so counts stay complete
                yield {"entry_id": n, "ts": None, "level": None, "component": None, "node": None,
                       "event_type": None, "alert_label": None, "message": line}
                continue
            level, content = m["level"], m["content"] or ""
            if level not in BGL_LEVELS:  # the level is missing on a few lines; it is part of the message
                content = f"{level} {content}".strip()
                level = None
            yield {
                "entry_id": n,
                "ts": _bgl_ts(m["time"]),
                "level": level,
                "component": m["component"],
                "node": m["node"],
                "event_type": m["type"],
                "alert_label": None if m["label"] == "-" else m["label"],
                "message": content,
            }


def _service(log_file: str) -> str | None:
    m = re.match(r"(nova-[a-z]+)", log_file)
    return m.group(1) if m else None


def openstack_rows(paths: list[Path], anomalous: set[str]) -> Iterator[dict[str, Any]]:
    """One row per entry. A traceback is logged as many lines with the same time, pid and component and
    no request context; those lines are joined onto the entry they continue, so it counts once."""
    pending: dict[str, Any] | None = None
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                row = _openstack_row(line.rstrip("\n"), n, path.name, anomalous)
                if (
                    pending is not None
                    and row["request_id"] is None
                    and row["_ctx"] is None
                    and (row["ts"], row["pid"], row["component"]) == (pending["ts"], pending["pid"], pending["component"])
                ):
                    pending["message"] += "\n" + row["message"]
                    continue
                if pending is not None:
                    yield pending
                pending = row
    if pending is not None:
        yield pending


def _openstack_row(line: str, n: int, source_file: str, anomalous: set[str]) -> dict[str, Any]:
    """`entry_id` is the line number within the file, offset per file so it stays unique."""
    base = {"openstack_normal1.log": 0, "openstack_normal2.log": 1_000_000, "openstack_abnormal.log": 2_000_000}
    entry_id = base.get(source_file, 3_000_000) + n
    m = OS_LINE.match(line)
    if m is None:
        return {f.name: None for f in OS_SCHEMA} | {"entry_id": entry_id, "message": line, "source_file": source_file,
                                                     "anomaly_instance": False, "_ctx": None}
    ctx = OS_CTX.match(m["ctx"] or "")
    content = m["content"] or ""
    inst = OS_INSTANCE.search(content)
    http = OS_HTTP.match(content)
    user = ctx["user"] if ctx and ctx["user"] not in (None, "-") else None
    tenant = ctx["tenant"] if ctx and ctx["tenant"] not in (None, "-") else None
    instance = inst["id"] if inst else None
    return {
        "entry_id": entry_id,
        "_ctx": m["ctx"],
        "ts": datetime.fromisoformat(f"{m['date']} {m['time']}").replace(tzinfo=UTC),
        "level": m["level"],
        "component": m["component"],
        "service": _service(m["file"]),
        "log_file": m["file"],
        "pid": int(m["pid"]),
        "request_id": ctx["req"] if ctx else None,
        "user_id": user,
        "tenant_id": tenant,
        "instance_id": instance,
        "client_ip": http["ip"] if http else None,
        "http_method": http["method"] if http else None,
        "http_path": http["path"] if http else None,
        "status": int(http["status"]) if http else None,
        "response_bytes": int(http["len"]) if http else None,
        "latency_s": float(http["time"]) if http else None,
        "anomaly_instance": instance in anomalous if instance else False,
        "source_file": source_file,
        "message": content,
    }


def write_parquet(rows: Iterator[dict[str, Any]], schema: pa.Schema, out: Path) -> int:
    tmp = out.with_suffix(".parquet.tmp")
    total = 0
    with pq.ParquetWriter(tmp, schema, compression="zstd") as writer:
        batch: list[dict[str, Any]] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= BATCH:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema), row_group_size=ROW_GROUP)
                total += len(batch)
                batch = []
                log(f"  {out.name}: {total:,} entries written")
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema), row_group_size=ROW_GROUP)
            total += len(batch)
    tmp.replace(out)
    return total


def parse(data_dir: Path, force: bool) -> tuple[dict[str, Path], set[str]]:
    """The Parquet file per dataset, and the datasets whose file was (re)written now."""
    out_dir = data_dir / "parquet"
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {"bgl": out_dir / "bgl.parquet", "openstack": out_dir / "openstack.parquet"}
    written = {name for name, path in outputs.items() if force or not path.exists()}
    if "bgl" in written:
        log("parsing BGL …")
        n = write_parquet(bgl_rows(data_dir / "BGL" / "BGL.log"), BGL_SCHEMA, outputs["bgl"])
        log(f"BGL: {n:,} entries → {outputs['bgl']}")
    if "openstack" in written:
        os_dir = data_dir / "OpenStack"
        labels = os_dir / "anomaly_labels.txt"
        anomalous = {ln.strip() for ln in labels.read_text().splitlines() if re.fullmatch(r"[0-9a-f-]{36}", ln.strip())}
        files = [os_dir / f for f in ("openstack_normal1.log", "openstack_normal2.log", "openstack_abnormal.log")]
        log("parsing OpenStack …")
        n = write_parquet(openstack_rows(files, anomalous), OS_SCHEMA, outputs["openstack"])
        log(f"OpenStack: {n:,} entries → {outputs['openstack']} ({len(anomalous)} labelled anomalous instances)")
    return outputs, written


# ---------------------------------------------------------------- setup


ROLES = {
    "bgl": {"timestamp": "ts", "message": "message", "level": "level", "component": "component", "host": "node",
            "order": "entry_id"},
    "openstack": {"timestamp": "ts", "message": "message", "level": "level", "component": "component",
                  "service": "service", "trace": "request_id", "order": "entry_id"},
}


def docker_cp(container: str, files: dict[str, Path], target_dir: str) -> dict[str, str]:
    subprocess.run(["docker", "exec", "-u", "0", container, "mkdir", "-p", target_dir], check=True)
    out = {}
    for name, path in files.items():
        dest = f"{target_dir}/{path.name}"
        log(f"copying {path.name} into {container}:{dest}")
        subprocess.run(["docker", "cp", str(path), f"{container}:{dest}"], check=True)
        subprocess.run(["docker", "exec", "-u", "0", container, "chmod", "a+r", dest], check=True)
        out[name] = dest
    return out


# The zone each log's timestamps were written in. BGL records US Pacific local time: its epoch column
# 1117838570 is 2005-06-03 22:42:50 UTC, and the same line's time reads 2005-06-03-15.42.50.
ZONES = {"bgl": "America/Los_Angeles", "openstack": "UTC"}


def setup_tables(sources: dict[str, str], replace: bool, rewritten: set[str]) -> None:
    """Set up each log table; one whose file was rewritten now (or that points elsewhere, with --replace) is
    registered again so its entry count and roles match the new file (its template catalog starts over)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from serenedb_extractor.config import Settings
    from serenedb_extractor.context import AppContext
    from serenedb_extractor.tools import setup_tools

    ctx = AppContext.from_settings(Settings.from_env(os.environ))
    try:
        known = {lt.name: lt for lt in ctx.store.list_log_tables()}
        for name, source in sources.items():
            if name in known and known[name].source == source and name not in rewritten:
                if known[name].timezone != ZONES[name]:
                    setup_tools.setup_log_table(ctx, name=name, source=source, timezone=ZONES[name])
                    log(f"log table '{name}': time zone corrected from {known[name].timezone} to {ZONES[name]}")
                else:
                    log(f"log table '{name}' is already set up for {source}; nothing to do")
                continue
            if name in known:
                if known[name].source != source and not replace:
                    log(f"log table '{name}' already exists for {known[name].source}; pass --replace to set it up again")
                    continue
                for table, col in (("log_tables", "name"), ("templates", "log_table"),
                                   ("template_redirects", "log_table"), ("log_index_columns", "log_table")):
                    ctx.db.write(f"DELETE FROM extractor.{table} WHERE {col} = %(n)s", {"n": name})
                ctx.db.write(f"DROP VIEW IF EXISTS {known[name].relation}")
            began = time.perf_counter()
            out = setup_tools.setup_log_table(ctx, name=name, source=source, roles=ROLES[name], timezone=ZONES[name])
            log(f"setup of '{name}' took {time.perf_counter() - began:.1f} s:\n" + out)
    finally:
        ctx.db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOGS_HOST_DIR", "~/logs")) / "loghub")
    ap.add_argument("--docker-cp", metavar="CONTAINER", help="copy the Parquet files into this SereneDB container")
    ap.add_argument("--container-dir", default="/data/loghub", help="where --docker-cp puts them (default /data/loghub)")
    ap.add_argument("--skip-setup", action="store_true", help="only download and convert")
    ap.add_argument("--replace", action="store_true", help="set up bgl/openstack again if they point elsewhere")
    ap.add_argument("--force", action="store_true", help="download and convert again even if the files exist")
    args = ap.parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    download(data_dir, args.force)
    files, rewritten = parse(data_dir, args.force)
    if args.skip_setup:
        return
    if args.docker_cp:
        sources = docker_cp(args.docker_cp, files, args.container_dir)
    else:
        sources = {k: str(v) for k, v in files.items()}
    setup_tables(sources, args.replace, rewritten)


if __name__ == "__main__":
    main()
