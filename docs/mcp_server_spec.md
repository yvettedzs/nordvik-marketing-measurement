# Nordvik MCP server – specification

Status: plan, to be implemented with Claude Code. Repo: nordvik-marketing-measurement, code in `mcp_server/`, tests in `tests/`.

## Goal
A small, **read-only** MCP server that lets an AI assistant (Claude Desktop, Claude Code) answer questions about Nordvik using the repo’s **agreed metric definitions** and data, instead of calculating its own versions.

## Stack
Python, the official MCP Python SDK (`pip install mcp`, `FastMCP`), DuckDB on the existing CSVs. Local stdio transport only.

## Tools
Build exactly these six tools; propose any additions instead of adding them.

| Tool | Returns |
|---|---|
| `list_metrics()` | Metric names and one-line definitions, parsed from `docs/metric_dictionary.md` |
| `define_metric(name)` | Full definition: formula, inclusions/exclusions, caveats |
| `get_kpis(market, channel, start, end)` | Spend, orders, net revenue, MER, CAC, CM, computed with the dictionary’s formulas |
| `compare_roas(channel)` | Platform ROAS vs simulated true iROAS (and, once the planned attribution extension exists, attributed ROAS by model), with the break-even line |
| `run_quality_check(name)` | Runs one of the four SQL checks and returns the status table |
| `get_test_result(test)` | Meta holdout or discount result from `analysis/*_results.txt`, including the interval |

## Rules every tool follows
- Each response states the **definition used**, the **source file** and **“simulated data”**.
- Revenue is net of VAT and cancellations; spend is ex VAT (as in `assumptions.md`).
- Describes channel-level `net_revenue_eur` as incremental revenue (the revenue each channel caused in the simulation), never as “attributed” revenue (see `assumptions.md`).
- Input validation: unknown market or channel → a clear error listing the valid values.
- Read-only: no tool writes files.

## Deliverables
- `mcp_server/server.py`, `mcp_server/README.md` (install, Claude Desktop / Claude Code config snippet, tool list)
- `tests/test_mcp_tools.py`: each tool’s numbers match the existing analysis outputs (e.g. MER, Meta holdout iROAS 2.45)
- A short demo in the README: 3 questions asked in Claude with the tool calls and answers, plus 1–2 screenshots
- One line added to the main README

## Out of scope
Live ad-platform APIs, authentication, hosting, write actions, a large tool count.
