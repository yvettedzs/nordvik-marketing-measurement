"""Audit: every run, drilldown and refusal adds exactly one line with the six keys; reads add none."""
import json
from datetime import datetime, timedelta

import pytest

from app import audit
from conftest import CM, LEAD, MCP_APP, PM

KEYS = {"timestamp", "role", "action", "inputs", "success", "message"}


def last_entry(client):
    return json.loads(client.audit_lines()[-1])


@pytest.mark.parametrize("call,role,action,success", [
    (lambda c: c.run(PM, "roas_lenses"), PM, "run_view", True),
    (lambda c: c.drill(PM, "roas_lenses", {"channel": "Meta"}), PM, "get_drilldown", True),
    (lambda c: c.run(CM, "roas_lenses"), CM, "run_view", False),                                     # refusal
    (lambda c: c.run(CM, "business_health", {"market": "FR"}), CM, "run_view", False),               # refusal
    (lambda c: c.drill(CM, "business_health", {"market": "FR"}), CM, "get_drilldown", False),        # refusal
    (lambda c: c.run(PM, "roas_lenses", {"overlay": True}), PM, "run_view", False),                  # refusal
    (lambda c: c.get("/api/views?role=intern"), "intern", "list_views", False),                       # refusal
    (lambda c: c.run(LEAD, "business_health", {"metric": "roas"}), LEAD, "run_view", False),         # 400
    (lambda c: c.drill(LEAD, "conversion_lag", {"path": "all", "day": 30}), LEAD, "get_drilldown", True),
])
def test_each_call_adds_exactly_one_line(client, call, role, action, success):
    before = len(client.audit_lines())
    call(client)
    lines = client.audit_lines()
    assert len(lines) == before + 1
    e = json.loads(lines[-1])
    assert set(e) == KEYS
    assert e["role"] == role and e["action"] == action and e["success"] is success
    assert isinstance(e["inputs"], dict) and isinstance(e["message"], str) and e["message"]
    ts = datetime.fromisoformat(e["timestamp"])
    assert ts.utcoffset() == timedelta(0)                     # timezone-aware UTC


def test_refusal_message_matches_response(client):
    r = client.run(CM, "business_health", {"market": "FR"})
    assert last_entry(client)["message"] == r.get_json()["error"]
    assert last_entry(client)["inputs"] == {"view": "business_health", "options": {"market": "FR"}}


def test_reads_do_not_add_lines(client):
    client.run(PM, "conversion_lag")
    n = len(client.audit_lines())
    for path in ("/api/roles", f"/api/views?role={PM}", "/api/audit?limit=5"):
        assert client.get(path).status_code == 200
    assert len(client.audit_lines()) == n


def test_sequence_of_calls_counts(client):
    client.run(LEAD, "data_quality")
    client.drill(LEAD, "data_quality", {"check": "02"})
    client.run(CM, "data_quality")
    client.drill(CM, "conversion_lag", {"path": "lead", "day": 365})
    assert len(client.audit_lines()) == 4
    assert all(set(json.loads(ln)) == KEYS for ln in client.audit_lines())


def test_audit_route(client):
    client.run(PM, "conversion_lag")
    client.run(CM, "roas_lenses")
    j = client.get("/api/audit?limit=2").get_json()
    assert j["data_origin"] == "simulated"
    entries = j["result"]["entries"]
    assert len(entries) == 2 and j["result"]["order"] == "newest first"
    assert entries[0]["success"] is False and entries[1]["success"] is True
    assert client.get("/api/audit?limit=1").get_json()["result"]["entries"] == entries[:1]
    for bad in ("abc", "0", "5000"):
        assert client.get(f"/api/audit?limit={bad}").status_code == 400


def test_default_log_path_and_utc_source():
    assert audit.DEFAULT_LOG_PATH == MCP_APP / "logs" / "audit.jsonl"
    src = (MCP_APP / "app" / "audit.py").read_text(encoding="utf-8")
    assert "utcnow" not in src and "datetime.now(timezone.utc)" in src
