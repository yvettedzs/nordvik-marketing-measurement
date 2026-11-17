"""Shared fixtures for the steering-hub API tests. Run from the repo root: python -m pytest mcp_app/tests"""
import sys
from pathlib import Path

import pytest

MCP_APP = Path(__file__).resolve().parents[1]
REPO = MCP_APP.parent
for p in (str(REPO), str(MCP_APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

import api  # noqa: E402

LEAD, PM, CM = "leadership", "performance_marketing", "country_manager_de"


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: re-records the demo responses (deselect with -m 'not slow')")

# one default drilldown segment per view (plus options the segment needs)
DRILLS = {
    "roas_lenses": [({"channel": "Meta"}, {}), ({"channel": "SEO"}, {})],
    "business_health": [({"market": "DE"}, {}), ({"week": "2026-03-02"}, {})],
    "attribution_sensitivity": [({"model": "last_click"}, {"channel": "Meta"})],
    "conversion_lag": [({"path": "all", "day": 30}, {})],
    "data_quality": [({"check": n}, {}) for n in ("01", "02", "03", "04")],
}


class Client:
    def __init__(self, flask_client, audit_path):
        self.c = flask_client
        self.audit_path = audit_path

    def run(self, role, view, options=None):
        return self.c.post("/api/run", json={"role": role, "view": view, "options": options or {}})

    def drill(self, role, view, segment, options=None):
        return self.c.post("/api/drilldown", json={"role": role, "view": view, "segment": segment,
                                                   "options": options or {}})

    def get(self, path):
        return self.c.get(path)

    def audit_lines(self):
        if not self.audit_path.exists():
            return []
        return [ln for ln in self.audit_path.read_text(encoding="utf-8").splitlines() if ln.strip()]


@pytest.fixture
def audit_path(tmp_path):
    return tmp_path / "audit.jsonl"


@pytest.fixture
def client(audit_path):
    app = api.create_app(audit_path)
    app.testing = True
    return Client(app.test_client(), audit_path)
