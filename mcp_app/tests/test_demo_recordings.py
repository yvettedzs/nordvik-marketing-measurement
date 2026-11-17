"""Demo recordings: docs/demo/recordings.json equals what the current API returns, call for call.

The slow test re-records everything through the real Flask app and compares. If it fails after a
change to the data, the metric code or the views, regenerate with: python mcp_app/demo/record_responses.py
"""
import json
import re
import sys

import pytest

from conftest import MCP_APP, REPO

sys.path.insert(0, str(MCP_APP / "demo"))
import record_responses as rr  # noqa: E402

RECORDINGS = REPO / rr.OUT_REL


@pytest.fixture(scope="module")
def recorded():
    assert RECORDINGS.exists(), f"{rr.OUT_REL} is missing: run mcp_app/demo/record_responses.py"
    return json.loads(RECORDINGS.read_text(encoding="utf-8"))


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def test_format_and_coverage(recorded):
    assert recorded["format"] == rr.FORMAT
    assert [r["id"] for r in recorded["roles"]] == ["country_manager_de", "performance_marketing", "leadership"]
    names = {json.loads(k)["name"] for k in recorded["calls"]}
    assert names == {"list_views", "run_view", "get_drilldown"}
    for entry in recorded["calls"].values():
        status, body = rr.unpack(recorded, entry)
        assert status == 200 and body["data_origin"] == "simulated"
    for case, entry in recorded["refusals"].items():
        status, body = rr.unpack(recorded, entry)
        assert status == 403 and body["access_denied"] is True, case


def test_no_local_paths(recorded):
    local = re.compile(r"[A-Za-z]:[\\/]|\\Users\\|/Users/|/home/|AppData", re.IGNORECASE)
    hits = [s for s in strings(recorded) if local.search(s)]
    assert not hits, hits[:5]


@pytest.mark.slow
def test_recordings_match_current_api(recorded):
    fresh = rr.build()
    assert fresh["roles"] == recorded["roles"]
    for kind in ("calls", "refusals"):
        assert set(fresh[kind]) == set(recorded[kind]), (
            f"{kind}: missing {sorted(set(fresh[kind]) - set(recorded[kind]))[:3]}, "
            f"extra {sorted(set(recorded[kind]) - set(fresh[kind]))[:3]}")
        diffs = [k for k in fresh[kind] if rr.unpack(fresh, fresh[kind][k]) != rr.unpack(recorded, recorded[kind][k])]
        assert not diffs, f"{len(diffs)} {kind} differ from the current API, e.g. {diffs[:3]}"
