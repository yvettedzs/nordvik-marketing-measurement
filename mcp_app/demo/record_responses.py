"""Record the steering-hub API responses for the static demo page (docs/demo/). ALL DATA IS SIMULATED.

Runs every tool call the dashboard can make, for every role, view, option value and drilldown, plus the refusals
the demo can show, through the real Flask app (test client, scratch audit log). Writes docs/demo/recordings.json.

Run from the repository root (about 7 minutes: the weekly business-health series is slow to compute):
    python mcp_app/demo/record_responses.py

Storage: every top-level field of every reply is stored once in "parts" and referenced by index, so the file is
about a sixth of the plain size. mcp_app/demo/shim.js rebuilds the replies in the browser.
mcp_app/tests/test_demo_recordings.py checks the file against the current API output.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

MCP_APP = Path(__file__).resolve().parents[1]
REPO = MCP_APP.parent
for p in (str(REPO), str(MCP_APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

import api  # noqa: E402

OUT_REL = "docs/demo/recordings.json"
FORMAT = 1
NOTICE = ("Recorded responses of the Nordvik steering hub API, for the static demo page. All data is simulated "
          "(fictional brand Nordvik Outdoor). Regenerate with mcp_app/demo/record_responses.py.")
# refusal cases the demo can show (from the page URL): any other market value or overlay request is not recorded
REFUSED_MARKETS = ["all", "AT", "FR", "NL", "UK", "SE"]


def call_key(name: str, args: dict[str, Any]) -> str:
    """Canonical key of one tool call: sorted keys, no spaces. shim.js builds the same string."""
    return json.dumps({"name": name, "arguments": args}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Recorder:
    def __init__(self, client):
        self.c = client
        self.calls: dict[str, tuple[int, dict[str, Any]]] = {}
        self.refusals: dict[str, tuple[int, dict[str, Any]]] = {}

    def _post(self, route: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        r = self.c.post(route, json=body)
        return r.status_code, r.get_json()

    def list_views(self, role: str) -> dict[str, Any]:
        r = self.c.get(f"/api/views?role={role}")
        self.calls[call_key("list_views", {"role": role})] = (r.status_code, r.get_json())
        return r.get_json()

    def run(self, role: str, view: str, options: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        args = {"role": role, "view": view, "options": options}
        out = self._post("/api/run", args)
        self.calls[call_key("run_view", args)] = out
        return out

    def drill(self, role: str, view: str, segment: dict[str, Any], options: dict[str, Any]) -> None:
        args = {"role": role, "view": view, "segment": segment, "options": options}
        self.calls[call_key("get_drilldown", args)] = self._post("/api/drilldown", args)

    def refusal(self, case: str, role: str, view: str, options: dict[str, Any]) -> None:
        status, body = self._post("/api/run", {"role": role, "view": view, "options": options})
        if status != 403:
            raise RuntimeError(f"expected a refusal for {case}, got HTTP {status}")
        self.refusals[case] = (status, body)


def option_sets(spec: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every options object the dashboard can send for one view (same rules as viewOptions() in mcp-app.js)."""
    sets: list[dict[str, Any]] = [{}]
    for name, o in spec["options"].items():
        values = [False, True] if name == "overlay" else o["values"] if o["type"] == "enum" else None
        if values is None:
            continue
        sets = [{**s, name: v} for s in sets for v in values]
    yield from sets


def drill_segments(view: str, result: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every segment the dashboard can request from one view result."""
    if view == "roas_lenses":
        for row in result["channels"]:
            yield {"channel": row["channel"]}
    elif view == "business_health":
        for p in result["points"]:
            yield {result["group_by"]: p["segment"]}
    elif view == "attribution_sensitivity":
        for m in result["models"]:
            yield {"model": m["model"]}
    elif view == "conversion_lag":
        for s in result["series"]:
            for day in result["checkpoints_days"]:
                yield {"path": s["path"], "day": day}
    elif view == "data_quality":
        for t in result["tiles"]:
            yield {"check": t["number"]}


def record(client) -> dict[str, Any]:
    rec = Recorder(client)
    roles = client.get("/api/roles").get_json()["result"]["roles"]
    all_views = [v for r in roles for v in r["views"]]
    all_views = list(dict.fromkeys(all_views))
    for role in roles:
        rid = role["id"]
        specs = rec.list_views(rid)["result"]["views"]
        for spec in specs:
            vid = spec["id"]
            rec.run(rid, vid, {})                       # the opening call, as Claude sends it without options
            for options in option_sets(spec):
                status, body = rec.run(rid, vid, options)
                if status != 200:
                    raise RuntimeError(f"run_view {rid} {vid} {options}: HTTP {status} {body}")
                for seg in drill_segments(vid, body["result"]):
                    rec.drill(rid, vid, seg, body["options"])
        for vid in all_views:
            if vid not in role["views"]:
                rec.refusal(f"view|{rid}|{vid}", rid, vid, {})
            elif not role["overlay_allowed"] and vid in ("roas_lenses", "data_quality"):
                rec.refusal(f"overlay|{rid}|{vid}", rid, vid, {"overlay": True})
        if role["market_lock"] and "business_health" in role["views"]:
            for m in REFUSED_MARKETS:
                rec.refusal(f"market|{rid}|{m}", rid, "business_health", {"market": m})
    return pack(roles, rec.calls, rec.refusals)


def pack(roles: list[dict[str, Any]], calls: dict, refusals: dict) -> dict[str, Any]:
    parts: list[Any] = []
    index: dict[str, int] = {}

    def part(value: Any) -> int:
        k = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if k not in index:
            index[k] = len(parts)
            parts.append(value)
        return index[k]

    def packed(status: int, body: dict[str, Any]) -> list[Any]:
        return [status, [[field, part(v)] for field, v in body.items()]]

    return {
        "format": FORMAT,
        "notice": NOTICE,
        "roles": roles,
        "calls": {k: packed(*v) for k, v in calls.items()},
        "refusals": {k: packed(*v) for k, v in refusals.items()},
        "parts": parts,
    }


def unpack(rec: dict[str, Any], entry: list[Any]) -> tuple[int, dict[str, Any]]:
    """Inverse of packed(): the status and the full reply body (shim.js does the same)."""
    status, fields = entry
    return status, {field: rec["parts"][i] for field, i in fields}


def build() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        app = api.create_app(Path(tmp) / "audit.jsonl")    # scratch audit log: mcp_app/logs is never touched
        app.testing = True
        return record(app.test_client())


def main() -> None:
    data = build()
    out = REPO / OUT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"{OUT_REL}: {len(data['calls'])} calls, {len(data['refusals'])} refusals, {len(data['parts'])} parts, "
          f"{len(text.encode()) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
