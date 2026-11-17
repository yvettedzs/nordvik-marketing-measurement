"""Read-only: a before/after file hash shows nothing in the repo changes when every view and drilldown runs.
The audit log goes to a temp file in these tests; mcp_app/logs/ is the only folder the API may write to."""
import hashlib

from conftest import DRILLS, LEAD, MCP_APP, REPO

SKIP_PARTS = {"__pycache__", ".pytest_cache", ".venv", "venv", ".git", "node_modules"}
LOGS = MCP_APP / "logs"


def snapshot(root):
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or SKIP_PARTS & set(rel.parts) or p.is_relative_to(LOGS):
            continue
        out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_api_writes_nothing_outside_logs(client):
    before = snapshot(REPO)
    for view, drills in DRILLS.items():
        assert client.run(LEAD, view).status_code == 200
        for seg, opts in drills:
            assert client.drill(LEAD, view, seg, opts).status_code == 200
    assert client.run(LEAD, "roas_lenses", {"overlay": True}).status_code == 200
    assert client.run("country_manager_de", "roas_lenses").status_code == 403
    assert snapshot(REPO) == before
    assert len(client.audit_lines()) == 1 + sum(1 + len(d) for d in DRILLS.values()) + 1


def test_views_module_does_not_reimplement_formulas():
    src = (MCP_APP / "app" / "views.py").read_text(encoding="utf-8")
    assert "answer_key" not in src
    for literal in ("0.55", "0.70", "0.15", "CM_RATE", "BREAK_EVEN_ROAS", "net_revenue_eur /", ".sum()"):
        assert literal not in src, literal
