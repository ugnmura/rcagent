"""The base-corpus loader's parsers (scripts/load_base_corpus.py); no download, no database."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("load_base_corpus", ROOT / "scripts" / "load_base_corpus.py")
loader = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["load_base_corpus"] = loader
_spec.loader.exec_module(loader)  # type: ignore[union-attr]


def _bgl(tmp_path: Path, *lines: str) -> list[dict]:
    p = tmp_path / "BGL.log"
    p.write_text("\n".join(lines) + "\n")
    return list(loader.bgl_rows(p))


def test_bgl_regular_alert_and_odd_lines(tmp_path):
    rows = _bgl(
        tmp_path,
        "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 R02-M1-N0-C:J12-U11 RAS KERNEL INFO "
        "instruction cache parity error corrected",
        "KERNDTLB 1118536327 2005.06.11 R30-M0-N9-C:J16-U01 2005-06-11-17.32.07.581048 R30-M0-N9-C:J16-U01 RAS KERNEL "
        "FATAL data TLB error interrupt",
        "- 1117867321 2005.06.03 NULL 2005-06-03-23.42.01.994539 NULL RAS MMCS INFO ciodb has been restarted.",
        "- 1119415930 2005.06.21 - 2005-06-21-21.52.10.214285 RAS KERNEL FATAL Kill job 20251 timed out. Block freed.",
        "garbage",
    )
    assert rows[0]["component"] == "KERNEL" and rows[0]["level"] == "INFO" and rows[0]["alert_label"] is None
    assert rows[1]["alert_label"] == "KERNDTLB" and rows[1]["node"] == "R30-M0-N9-C:J16-U01"
    assert rows[2]["component"] == "MMCS" and rows[2]["level"] == "INFO"  # node name is literally NULL
    assert rows[3]["component"] == "KERNEL" and rows[3]["level"] == "FATAL"  # no repeated node name
    assert rows[3]["message"] == "Kill job 20251 timed out. Block freed."
    assert rows[4]["message"] == "garbage" and rows[4]["ts"] is None  # kept, so counts stay complete
    assert [r["entry_id"] for r in rows] == [1, 2, 3, 4, 5]


def test_openstack_fields_and_joined_traceback(tmp_path):
    f = tmp_path / "openstack_normal1.log"
    f.write_text(
        "nova-api.log.1.2017-05-16_13:53:08 2017-05-16 00:00:00.008 25746 INFO nova.osapi_compute.wsgi.server "
        "[req-38101a0b-2096-447d-96ea-a692162415ae 113d3a99c3da401fbd62cc2caa5b96d2 54fadb412c4e40cdbaed9335e4c35a9e - - -] "
        '10.11.10.1 "GET /v2/54fadb412c4e40cdbaed9335e4c35a9e/servers/detail HTTP/1.1" status: 200 len: 1893 time: 0.2477829\n'
        "nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 03:19:45.356 2931 ERROR oslo_service.periodic_task "
        "[req-aaaaaaaa-2096-447d-96ea-a692162415ae - - - - -] Error during pass\n"
        "nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 03:19:45.356 2931 ERROR oslo_service.periodic_task "
        "Traceback (most recent call last):\n"
        "nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 03:19:45.356 2931 ERROR oslo_service.periodic_task\n"
        "nova-compute.log.1.2017-05-16_13:55:31 2017-05-16 03:20:00.000 2931 INFO nova.compute.manager "
        "[req-bbbbbbbb-2096-447d-96ea-a692162415ae - - - - -] [instance: 544fd51c-4edc-4780-baae-ba1d80a0acfc] Took 1 s\n"
    )
    rows = list(loader.openstack_rows([f], {"544fd51c-4edc-4780-baae-ba1d80a0acfc"}))
    assert len(rows) == 3  # the traceback lines joined onto their entry
    api, err, inst = rows
    assert api["service"] == "nova-api" and api["status"] == 200 and abs(api["latency_s"] - 0.2477829) < 1e-9
    assert api["tenant_id"] == "54fadb412c4e40cdbaed9335e4c35a9e" and api["http_method"] == "GET"
    assert err["level"] == "ERROR" and "Traceback" in err["message"] and err["message"].count("\n") == 2
    assert inst["instance_id"] == "544fd51c-4edc-4780-baae-ba1d80a0acfc" and inst["anomaly_instance"] is True
    assert api["anomaly_instance"] is False
