"""
Nordvik steering hub: Python API (Flask, port 5001). ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor").

Checks access, calls the existing metric code in mcp_server/server.py (via app/views.py) and writes the audit log.
Read-only: the only file written is mcp_app/logs/audit.jsonl.

Run from the repository root:  .venv\\Scripts\\python.exe mcp_app/api.py

Routes: GET /api/roles, GET /api/views?role=, POST /api/run (role, view, options),
        POST /api/drilldown (role, view, segment, options), GET /api/audit?limit=
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, jsonify, request                 # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError        # noqa: E402

from app import REPO_ROOT, access, views                   # noqa: E402
from app.audit import AuditLog                              # noqa: E402

HOST, PORT = "127.0.0.1", 5001
AUDIT_LIMIT_DEFAULT, AUDIT_LIMIT_MAX = 50, 1000
ROLE_CAVEAT = "Roles are chosen by the caller (no login): this demonstrates role-based views, not access control."


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def create_app(audit_path: Path | str | None = None) -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False
    log = AuditLog(audit_path)
    app.config["AUDIT_LOG"] = log

    def handle(action: str, role: Any, inputs: dict[str, Any], fn: Callable[[], Any], log_success: bool = True):
        """Run fn; write exactly one audit line for a run/drilldown (any outcome) or a refusal."""
        try:
            body = fn()
        except access.AccessDenied as e:
            log.write(role, action, inputs, False, str(e))
            return jsonify({"error": str(e), "access_denied": True}), 403
        except (views.InvalidInput, ToolError) as e:
            log.write(role, action, inputs, False, str(e))
            return jsonify({"error": str(e), "access_denied": False}), 400
        except Exception as e:                              # noqa: BLE001  (logged, then a JSON 500)
            msg = f"internal error: {type(e).__name__}: {e}"
            log.write(role, action, inputs, False, msg)
            return jsonify({"error": msg, "access_denied": False}), 500
        if log_success:
            log.write(role, action, inputs, True, f"ok: {inputs.get('view')}")
        return jsonify(body), 200

    def body_json() -> dict[str, Any]:
        b = request.get_json(silent=True)
        return b if isinstance(b, dict) else {"_invalid_body": True}

    def require_object(b: dict[str, Any]) -> None:
        if b.get("_invalid_body"):
            raise views.InvalidInput("Request body must be a JSON object.")

    @app.get("/api/roles")
    def roles():
        rows = [{"id": rid, "label": r["label"], "views": r["views"], "market_lock": r["market_lock"],
                 "overlay_allowed": r["overlay_allowed"]} for rid, r in access.ROLES.items()]
        return jsonify(views.meta_envelope({"roles": rows}, caveats=[ROLE_CAVEAT]))

    @app.get("/api/views")
    def list_views():
        role = request.args.get("role")
        return handle("list_views", role, {}, lambda: views.meta_envelope(
            {"role": role, "views": views.list_views(role)}, caveats=[ROLE_CAVEAT]), log_success=False)

    @app.post("/api/run")
    def run():
        b = body_json()
        role = b.get("role")
        inputs = {"view": b.get("view"), "options": b.get("options")}

        def go():
            require_object(b)
            return views.run_view(role, b.get("view"), b.get("options"))
        return handle("run_view", role, inputs, go)

    @app.post("/api/drilldown")
    def drilldown():
        b = body_json()
        role = b.get("role")
        inputs = {"view": b.get("view"), "segment": b.get("segment"), "options": b.get("options")}

        def go():
            require_object(b)
            return views.get_drilldown(role, b.get("view"), b.get("segment"), b.get("options"))
        return handle("get_drilldown", role, inputs, go)

    @app.get("/api/audit")
    def audit():
        raw = request.args.get("limit", str(AUDIT_LIMIT_DEFAULT))
        try:
            limit = int(raw)
        except ValueError:
            limit = 0
        if not 1 <= limit <= AUDIT_LIMIT_MAX:
            return jsonify({"error": f"limit must be a whole number from 1 to {AUDIT_LIMIT_MAX}.",
                            "access_denied": False}), 400
        entries = log.read(limit)
        return jsonify(views.meta_envelope({"entries": entries, "count": len(entries), "order": "newest first"},
                                           sources=[_rel(log.path)]))

    @app.errorhandler(404)
    @app.errorhandler(405)
    def not_found(e):
        return jsonify({"error": f"{e.code} {e.name}: {request.method} {request.path}", "access_denied": False}), e.code

    return app


if __name__ == "__main__":
    # weekly business_health is slow cold (45-50 s per market): warm every market in the background (not in tests)
    threading.Thread(target=views.warm_cache, daemon=True, name="warm-cache").start()
    create_app().run(host=HOST, port=PORT, debug=False, threaded=True)
