# Nordvik steering hub (MCP app)

A role-based dashboard over the repo's agreed metrics. **All data is simulated** (fictional brand "Nordvik Outdoor").

Three layers:

| Layer | Files | Job |
|---|---|---|
| Dashboard | `mcp-server/mcp-app.html`, `mcp-server/src/mcp-app.js` | Role, view and option menus, a Plotly chart or tiles per view, table view, drilldowns, audit log panel |
| MCP server (TypeScript, port 3001) | `mcp-server/server.ts` | Four tools, serves the dashboard resource `ui://nordvik/steering-hub` |
| Python API (Flask, port 5001) | `api.py`, `app/views.py`, `app/access.py`, `app/audit.py` | Access check, calls the existing metric code, audit log |

The Python API calls the existing tools in `mcp_server/server.py` (`get_kpis`, `compare_roas`, `run_quality_check`
and the metric-dictionary helpers) and does not re-implement any formula. Three drilldowns, plus conversion lag,
have no matching tool, so they read the published files as they are: `data/simulated_weekly_data.csv` (observable
columns only), `analysis/attribution_comparison.csv` and `analysis/conversion_lag_results.txt`.

## Run the API

From the repository root:

```
.venv\Scripts\python.exe -m pip install -r mcp_app/requirements.txt
.venv\Scripts\python.exe mcp_app/api.py          # http://127.0.0.1:5001
.venv\Scripts\python.exe -m pytest mcp_app/tests # about 2 minutes
```

At startup a background thread pre-computes the weekly business-health series for every market (104 `get_kpis`
calls per market; all markets and DE first, then AT, FR, NL, UK, SE). Measured on the development laptop: about
5.5 minutes for all seven, so 45 to 50 s per market. The API answers other
requests while it runs; a weekly request for a market not yet warmed is computed on demand. Only
`python mcp_app/api.py` starts the warm-up, so the tests never run it. Results are cached in memory for the life of
the process: restart the API after regenerating data.

## Run the MCP server

Node 20.11 or later (tested with Node 26.13). In a second terminal, with the API running:

```
cd mcp_app/mcp-server
npm ci            # exact versions from package-lock.json
npm run build     # dist/mcp-app.html (single file; Plotly 4.3.0 loads from cdn.plot.ly)
npm start         # http://127.0.0.1:3001/mcp
npm run typecheck # tsc --noEmit
```

MCP tools: `list_views(role)`, `run_view(role, view, options)` (opens the dashboard),
`get_drilldown(role, view, segment, options)`, `get_audit_log(limit)`. The server computes nothing: each tool
forwards to the Python API (`NORDVIK_API_URL`, default `http://127.0.0.1:5001`). It is stateless and builds a fresh
`McpServer` per request.

Stop both servers with Ctrl+C, then check the ports are free:
`Get-NetTCPConnection -LocalPort 3001,5001 -State Listen` should return nothing.

## Test in basic-host

With the API and the MCP server running, start the ext-apps test host in a folder outside this repo:

```
git clone https://github.com/modelcontextprotocol/ext-apps.git
cd ext-apps
npm install
cd examples\basic-host
$env:SERVERS='["http://127.0.0.1:3001/mcp"]'
npm run start     # http://localhost:8080
```

Start it from `examples\basic-host`: `npm start` in the ext-apps root also starts all their example servers.

In the browser, **pick the Nordvik server and the `run_view` tool first, then replace `{}` in the arguments box**,
for example with `{"role": "performance_marketing", "view": "roas_lenses"}`. The box resets to `{}` whenever a server
or tool is selected, and a call without `role` and `view` is refused with "MCP error -32602: Input validation error".

## Routes

| Route | Body / query | Returns |
|---|---|---|
| `GET /api/roles` | | The three roles, their views, market lock and overlay right |
| `GET /api/views?role=` | | The views the role can open, with their options |
| `POST /api/run` | `{role, view, options}` | The view result |
| `POST /api/drilldown` | `{role, view, segment, options}` | The drilldown result |
| `GET /api/audit?limit=` | limit 1 to 1000, default 50 | Audit entries, newest first |

Every 200 reply carries the envelope: `data_origin: "simulated"`, `notice`, `definitions_used`, `conventions`,
`sources`, `caveats`, then `role`, `view`, `options`, (`segment`) and `result`.
Refusals: HTTP 403 `{"error": "...", "access_denied": true}`. Bad input: HTTP 400 `{"error": "...", "access_denied": false}`.

## Roles

| Role id | Views | Rule |
|---|---|---|
| `country_manager_de` | business_health, conversion_lag | Market locked to DE: no market given means DE; any other value (including `all`) is refused |
| `performance_marketing` | roas_lenses, attribution_sensitivity, conversion_lag, data_quality | All markets |
| `leadership` | all five | All markets; may switch on `overlay` (simulated truth, validation only) on roas_lenses and data_quality |

Roles are chosen by the caller (no login): this demonstrates role-based views, not access control.
Conversion lag is pooled over all markets in the results file, so the country manager sees the all-market figures
(labelled as such).

## Views

| View | Options | Segment (drilldown) |
|---|---|---|
| `roas_lenses` | `overlay` (leadership) | `{"channel": "Meta"}` → weekly rows by market, observable columns only |
| `business_health` | `metric` (mer, cac, cm_after_marketing), `group_by` (market, week), `market` | `{"market": "DE"}` or `{"week": "2026-03-02"}` → spend, orders, net revenue, MER |
| `attribution_sensitivity` | `channel` (Google, Meta, Affiliates, TikTok, SEO, Email) | `{"model": "last_click"}` → that model at 7, 30, 90, 365 days |
| `conversion_lag` | none | `{"path": "all", "day": 30}` → blended CAC and payback ratio at 30, 90, 365 days |
| `data_quality` | `overlay` (leadership) | `{"check": "01"}` → rule, action and flagged rows |

Simulated truth (`simulated_true_iroas`, `journey_true_iroas`, check 01's `channel_roas` and `claim_ratio`) appears
only for leadership with `overlay: true`, labelled "validation only: not observable in real data".

## Audit log

`logs/audit.jsonl`, one JSON line per run, drilldown and refusal, with the keys `timestamp` (UTC), `role`, `action`
(`run_view`, `get_drilldown`, `list_views`), `inputs`, `success`, `message`. This is the only file the API writes.

## Limits

- Roles are chosen by the caller (no login): this demonstrates role-based views, not access control.
- The audit log is readable without a role: `GET /api/audit` has no role parameter, so anyone who can reach the API
  can read every entry.
- Weekly results are cached in memory for the life of the process, so the API must be restarted after regenerating
  data (`generate_data.py`, `generate_journeys.py` or the analysis scripts); otherwise it keeps serving the old numbers.
- Conversion lag is pooled over all markets; it cannot be limited to one market without recomputing the analysis.
