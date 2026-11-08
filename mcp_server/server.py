"""
Nordvik MCP server: a small, read-only MCP server over the repo's agreed metric definitions and data.

ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor"). See docs/mcp_server_spec.md.

Run (stdio transport):  python mcp_server/server.py
Works from any working directory: all paths are resolved from this file's location.
"""
from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

# ---------------------------------------------------------------- paths and constants
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_REL = "data/simulated_weekly_data.csv"
CALENDAR_REL = "data/events_calendar.csv"
ATTRIBUTION_REL = "analysis/attribution_comparison.csv"
ATTRIBUTION_SCRIPT_REL = "analysis/03_attribution_models.py"
ATTRIBUTION_MODELS = ["last_click", "last_non_direct", "first_click", "linear", "time_decay_7d", "time_decay_30d",
                      "u_shaped", "w_shaped"]
ATTRIBUTION_LOOKBACKS = [7, 30, 90, 365]
MODEL_CREDITED_LABEL = ("model-credited revenue / spend: analytics attribution on the simulated user journeys "
                        "(observed paths, after consent loss); not incremental")
DICTIONARY_REL = "docs/metric_dictionary.md"
ASSUMPTIONS_REL = "docs/assumptions.md"

# unit economics from docs/assumptions.md (section 4)
GROSS_MARGIN, VAR_COST = 0.70, 0.15
CM_RATE = GROSS_MARGIN - VAR_COST           # contribution margin before marketing, 55% of net revenue
BREAK_EVEN_ROAS = 1 / CM_RATE               # ~1.82
LAG_WEEKS = 13                              # 30-90 day buying window (assumptions.md section 5)

NOTICE = "Simulated data for a fictional brand (Nordvik Outdoor). Not real company results."
CONVENTIONS = "Revenue is net of VAT and after cancellations; spend is excluding VAT; weekly grain, EUR (docs/assumptions.md)."
INCREMENTAL_LABEL = "incremental revenue: the revenue each channel caused in the simulation"
VALIDATION_ONLY = "validation only: not observable in real data"

QUALITY_CHECKS = {
    "01": "01_platform_vs_analytics_gap",
    "02": "02_weekly_volume_anomalies",
    "03": "03_spend_vs_sessions_sanity",
    "04": "04_revenue_reconciliation",
}
TESTS = {
    "meta_holdout": ("analysis/meta_holdout_results.txt", "analysis/01_meta_holdout.py"),
    "discount": ("analysis/discount_results.txt", "analysis/02_discount_prepost.py"),
}
TEST_ALIASES = {"meta_holdout": "meta_holdout", "meta": "meta_holdout", "holdout": "meta_holdout",
                "discount": "discount", "promo": "discount"}

mcp = FastMCP("nordvik")
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


# ---------------------------------------------------------------- helpers
def _path(rel: str) -> Path:
    return REPO_ROOT / rel


def _read(rel: str) -> str:
    return _path(rel).read_text(encoding="utf-8")


def _con() -> duckdb.DuckDBPyConnection:
    """Fresh in-memory DuckDB connection; relative paths in queries resolve against the repo root."""
    con = duckdb.connect(":memory:")
    con.execute("SET file_search_path = ?", [REPO_ROOT.as_posix()])
    return con


def _envelope(definitions: dict[str, str], sources: list[str], result: dict[str, Any],
              caveats: list[str] | None = None) -> dict[str, Any]:
    return {
        "data_origin": "simulated",
        "notice": NOTICE,
        "definitions_used": definitions,
        "conventions": CONVENTIONS,
        "sources": sources,
        "result": result,
        "caveats": caveats or [],
    }


def _valid_list(values) -> str:
    return ", ".join(values)


def _load_dimensions() -> tuple[list[str], list[str], list[str]]:
    con = _con()
    markets = [r[0] for r in con.execute(f"SELECT DISTINCT market FROM read_csv_auto('{DATA_REL}')").fetchall()]
    channels = [r[0] for r in con.execute(f"SELECT DISTINCT channel FROM read_csv_auto('{DATA_REL}')").fetchall()]
    weeks = [r[0].isoformat() for r in con.execute(
        f"SELECT DISTINCT week_start FROM read_csv_auto('{DATA_REL}') ORDER BY 1").fetchall()]
    order_m = ["DE", "AT", "FR", "NL", "UK", "SE"]          # order used in assumptions.md / the analysis
    order_c = ["Google", "Meta", "Affiliates", "TikTok", "SEO", "Email", "Direct_Other"]
    markets = sorted(markets, key=lambda m: order_m.index(m) if m in order_m else 99)
    channels = sorted(channels, key=lambda c: order_c.index(c) if c in order_c else 99)
    return markets, channels, weeks


MARKETS, CHANNELS, WEEKS = _load_dimensions()
FIRST_WEEK, LAST_WEEK = WEEKS[0], WEEKS[-1]


def _resolve(value: str, valid: list[str], kind: str) -> str:
    if value is None or str(value).strip().lower() == "all":
        return "all"
    lookup = {v.lower(): v for v in valid}
    key = str(value).strip().lower()
    if key not in lookup:
        raise ToolError(f"Unknown {kind} '{value}'. Valid values: all, {_valid_list(valid)}")
    return lookup[key]


def _parse_date(value: str | None, default: str, kind: str) -> str:
    if value is None or str(value).strip() == "":
        return default
    try:
        d = date.fromisoformat(str(value).strip())
    except ValueError:
        raise ToolError(f"Invalid {kind} date '{value}'. Use ISO format YYYY-MM-DD, "
                        f"between {FIRST_WEEK} and {LAST_WEEK}.")
    iso = d.isoformat()
    if iso < FIRST_WEEK or iso > LAST_WEEK:
        raise ToolError(f"{kind.capitalize()} date {iso} is outside the data range {FIRST_WEEK} to {LAST_WEEK}.")
    return iso


def _calendar() -> pd.DataFrame:
    return pd.read_csv(_path(CALENDAR_REL), dtype=str).fillna("")


# ---------------------------------------------------------------- metric dictionary parsing
_LABEL = re.compile(r"\*\*([^*]+?):\*\*\s*")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "").replace("*", "")).strip()


def _parse_dictionary() -> list[dict[str, Any]]:
    """Metric sections of docs/metric_dictionary.md: numbered sections plus 'Supporting metric'."""
    text = _read(DICTIONARY_REL)
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    metrics = []
    for part in parts:
        heading, _, body = part.partition("\n")
        heading = heading.strip()
        m = re.match(r"^(?:\d+\.\s*|Supporting metric:\s*)(.+)$", heading)
        if not m:                                      # 'Base reference numbers', 'Worked example ...'
            continue
        title = m.group(1).strip()
        pm = re.match(r"^(.+?)\s*\((.+)\)$", title)
        if pm:
            a, b = pm.group(1).strip(), pm.group(2).strip()
            abbr, full = (a, b) if len(a) <= len(b) else (b, a)
            key = abbr.lower()
        else:
            abbr, full = None, title
            key = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        details: dict[str, str] = {}
        notes: list[str] = []
        for line in body.splitlines():
            if not line.startswith("- "):
                continue
            bullet = line[2:].strip()
            labels = list(_LABEL.finditer(bullet))
            if not labels:
                notes.append(_clean(bullet))
                continue
            if labels[0].start() > 0:
                notes.append(_clean(bullet[:labels[0].start()]))
            for i, lm in enumerate(labels):
                end = labels[i + 1].start() if i + 1 < len(labels) else len(bullet)
                details[lm.group(1).strip()] = _clean(bullet[lm.end():end])
        definition = details.get("Definition") or details.get("Ratio") or (notes[0] if notes else "")
        metrics.append({
            "key": key,
            "name": f"{full} ({abbr})" if abbr else full,
            "abbreviation": abbr,
            "full_name": full,
            "one_line": definition,
            "definition": definition,
            "formula": details.get("Ratio") if "Definition" not in details and "Ratio" in details else definition,
            "includes": details.get("Includes"),
            "excludes": details.get("Excludes"),
            "example": details.get("Example"),
            "details": details,
            "notes": notes,
            "section_markdown": ("## " + heading + "\n" + body).strip(),
        })
    return metrics


def _metric_lookup() -> dict[str, dict[str, Any]]:
    out = {}
    for m in _parse_dictionary():
        for alias in (m["key"], m["abbreviation"], m["full_name"], m["name"]):
            if alias:
                out[alias.lower()] = m
    return out


def _definition(key: str) -> str:
    m = _metric_lookup()[key]
    return f"{m['name']}: {m['definition']}"


# ---------------------------------------------------------------- test-result parsing
def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _pct(s: str) -> float:
    return round(float(s) / 100, 6)


def _match(pattern: str, text: str, label: str) -> re.Match:
    m = re.search(pattern, text)
    if not m:
        raise ToolError(f"Could not parse '{label}' from the result file; its format may have changed. "
                        f"Re-run the analysis script or update the parser.")
    return m


_P = r"([+-]?[\d.]+)%"          # signed percentage


def _verdict_roas(point: float, lo: float, hi: float, be: float) -> str:
    if lo > be:
        return "profitable: the whole 95% interval is above break-even"
    if hi < be:
        return "loss-making: the whole 95% interval is below break-even"
    side = "above" if point >= be else "below"
    proven = "profitable" if point >= be else "loss-making"
    return f"point estimate {side} break-even, but the 95% interval includes it: not proven {proven}"


def _parse_meta(text: str) -> dict[str, Any]:
    m = _match(r"Test window: (\S+) to (\S+) \((\d+) weeks; Meta paused in the first (\d+)\)", text, "test window")
    r: dict[str, Any] = {"market": "DE", "channel": "Meta", "outcome": "orders",
                         "test_window": {"start": m[1], "end": m[2]}, "weeks": int(m[3]), "paused_weeks": int(m[4])}
    r["pre_fit_mape"] = _pct(_match(r"mean abs % error\): ([\d.]+)%", text, "pre-period fit")[1])
    r["control_weights"] = ast.literal_eval(_match(r"Control weights: (\{.*\})", text, "control weights")[1])
    m = _match(r"Orders actual vs counterfactual: ([\d,]+) vs ([\d,]+)", text, "orders")
    r["orders_actual"], r["orders_counterfactual"] = int(_num(m[1])), int(_num(m[2]))
    m = _match(rf"Incremental orders from Meta: ([\d,]+) lost when paused \({_P}, 95% interval {_P} to {_P}\)",
               text, "incremental orders")
    r["orders_lost"] = int(_num(m[1])); r["pct_change"] = _pct(m[2]); r["pct_ci_95"] = [_pct(m[3]), _pct(m[4])]
    r["naive_prepost"] = _pct(_match(rf"Naive pre/post \(same-length window before\): {_P}", text, "naive")[1])
    r["did_ratio"] = _pct(_match(rf"Simple ratio difference-in-differences:\s+{_P}", text, "DiD")[1])
    r["spend_saved_eur"] = _num(_match(r"Meta spend saved during the pause: EUR ([\d,]+)", text, "spend saved")[1])
    m = _match(r"Incremental net revenue lost: EUR ([\d,]+)\s+\(avg DE net order value EUR ([\d,]+)\)", text, "revenue lost")
    r["incremental_revenue_lost_eur"], r["avg_order_value_eur"] = _num(m[1]), _num(m[2])
    m = _match(r"Incremental ROAS: ([\d.]+)\s+\(95% interval ([\d.]+) to ([\d.]+)\)", text, "incremental ROAS")
    r["iroas"], r["iroas_ci_95"] = float(m[1]), [float(m[2]), float(m[3])]
    r["platform_roas_de_pre_test"] = float(_match(r"Platform-reported ROAS in DE \(pre-test\): ([\d.]+)", text, "platform ROAS")[1])
    r["break_even_roas"] = float(_match(r"Break-even ROAS: ([\d.]+)", text, "break-even")[1])
    r["verdict"] = _verdict_roas(r["iroas"], *r["iroas_ci_95"], r["break_even_roas"])
    return r


def _parse_discount(text: str) -> dict[str, Any]:
    m = _match(r"Promo window: (\S+) to (\S+); follow-up window: (\S+) to (\S+)", text, "windows")
    r: dict[str, Any] = {"markets": ["DE", "AT", "FR", "NL"], "control_markets": ["UK", "SE"],
                         "product": "outdoor_furniture", "outcome": "orders, then contribution margin",
                         "promo_window": {"start": m[1], "end": m[2]}, "follow_up_window": {"start": m[3], "end": m[4]}}
    r["naive_prepost"] = _pct(_match(rf"Naive pre/post \(promo weeks vs 4 weeks before\): {_P}", text, "naive")[1])
    m = _match(rf"Promo window orders: ([\d,]+) actual vs ([\d,]+) counterfactual -> lift {_P} \(95% interval {_P} to {_P}\)",
               text, "promo window")
    r["promo_orders_actual"], r["promo_orders_counterfactual"] = int(_num(m[1])), int(_num(m[2]))
    r["lift"], r["lift_ci_95"] = _pct(m[3]), [_pct(m[4]), _pct(m[5])]
    m = _match(rf"Follow-up window:\s+([\d,]+) actual vs ([\d,]+) counterfactual -> {_P} \(95% interval {_P} to {_P}\)",
               text, "follow-up window")
    r["follow_up_orders_actual"], r["follow_up_orders_counterfactual"] = int(_num(m[1])), int(_num(m[2]))
    r["pull_forward_dip"], r["dip_ci_95"] = _pct(m[3]), [_pct(m[4]), _pct(m[5])]
    m = _match(rf"8-week net orders:\s+([+-]?[\d,]+) orders \({_P}, 95% interval {_P} to {_P}\)", text, "net orders")
    r["net_orders_8w"], r["net_pct_8w"], r["net_pct_ci_95"] = int(_num(m[1])), _pct(m[2]), [_pct(m[3]), _pct(m[4])]
    m = _match(r"Realised discount implied by revenue: (\d+)% \(headline (\d+)%", text, "realised discount")
    r["realised_discount"], r["headline_discount"] = _pct(m[1]), _pct(m[2])
    m = _match(r"Contribution margin per outdoor-furniture order: (\d+)% of regular net price -> (\d+)% when discounted",
               text, "margin per order")
    r["cm_per_order_regular"], r["cm_per_order_discounted"] = _pct(m[1]), _pct(m[2])
    m = _match(rf"Break-even lift \(orders needed just to keep margin flat\): {_P}\s+vs observed {_P}", text, "break-even lift")
    r["break_even_lift"], r["observed_lift_rounded"] = _pct(m[1]), _pct(m[2])
    r["net_revenue_effect_8w_eur"] = _num(_match(r"Net revenue:\s+EUR (-?[\d,]+)", text, "net revenue effect")[1])
    m = _match(rf"Contribution margin:\s+EUR (-?[\d,]+)\s+\({_P} of baseline margin; range EUR (-?[\d,]+) to (-?[\d,]+)",
               text, "contribution margin effect")
    r["cm_effect_8w_eur"], r["cm_effect_pct_of_baseline"] = _num(m[1]), _pct(m[2])
    r["cm_effect_range_eur"] = [_num(m[3]), _num(m[4])]
    r["verdict"] = ("orders rose, but the lift is far below the break-even lift, so the promo lost contribution margin"
                    if r["lift"] < r["break_even_lift"] else "lift reached the break-even lift")
    return r


# ---------------------------------------------------------------- SQL check helpers
def _resolve_check(name: str) -> str:
    key = str(name or "").strip().lower().removesuffix(".sql").removeprefix("sql/")
    for num, stem in QUALITY_CHECKS.items():
        if key in (num, num.lstrip("0"), stem, stem[3:]):
            return stem
    raise ToolError(f"Unknown quality check '{name}'. Valid values: "
                    + "; ".join(f"{n} / {s[3:]}" for n, s in QUALITY_CHECKS.items()))


def _parse_sql_header(sql: str) -> dict[str, str]:
    header: dict[str, str] = {}
    current = None
    for line in sql.splitlines():
        if not line.startswith("--"):
            break
        body = line[2:].strip()
        m = re.match(r"^([A-Z]+):\s*(.*)$", body)
        if m:
            current = m.group(1).lower(); header[current] = m.group(2)
        elif current and body:
            header[current] += " " + body
    return header


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat() if v == v.normalize() else v.isoformat()
    if isinstance(v, str):
        return re.sub(r"^(\d{4}-\d{2}-\d{2}) 00:00:00$", r"\1", v)
    if hasattr(v, "item"):                       # numpy scalar
        v = v.item()
    if isinstance(v, float) and v != v:          # NaN
        return None
    if isinstance(v, date):
        return v.isoformat()
    return v


# ---------------------------------------------------------------- attribution extension (journey simulation)
def _attribution_blocks() -> dict[str, dict[str, Any]] | None:
    """Per channel: ROAS by attribution model (90-day lookback) and last non-direct by lookback, from the
    attribution comparison CSV (observed paths). None if the CSV does not exist yet."""
    path = _path(ATTRIBUTION_REL)
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df = df[(df.view == "observed") & (df.channel != "Direct_Other")]
    out = {}
    for ch, g in df.groupby("channel"):
        m90 = g[g.lookback_days == 90].set_index("model").model_roas
        lnd = g[g.model == "last_non_direct"].set_index("lookback_days").model_roas
        out[ch] = {
            "status": "available",
            "label": MODEL_CREDITED_LABEL,
            "source": ATTRIBUTION_REL,
            "scope": "journey simulation: one-year cohort (first touches 2024-10-28 to 2025-10-26, orders followed "
                     "to 2026-10-25), all markets, observed paths",
            "journey_spend_eur": round(float(g.spend_eur.iloc[0]), 2),
            "models_90d": {m: round(float(m90[m]), 4) for m in ATTRIBUTION_MODELS},
            "last_non_direct_by_lookback_days": {str(lb): round(float(lnd[lb]), 4) for lb in ATTRIBUTION_LOOKBACKS},
            "journey_true_iroas": round(float(g.true_iroas.iloc[0]), 4),
            "journey_true_iroas_label": VALIDATION_ONLY,
            "lookback_note": "GA4's maximum lookback window is 90 days; 365 days is shown for comparison only.",
        }
    return out


# ---------------------------------------------------------------- tools
@mcp.tool(annotations=READ_ONLY)
def list_metrics() -> dict[str, Any]:
    """List the agreed Nordvik metrics (CAC, ROAS, MER, contribution margin, payback, iROAS) with
    one-line definitions, parsed from docs/metric_dictionary.md. Simulated data, fictional brand."""
    metrics = [{"key": m["key"], "name": m["name"], "one_line": m["one_line"]} for m in _parse_dictionary()]
    return _envelope(
        {"source_of_definitions": "docs/metric_dictionary.md is the single agreed definition for each metric"},
        [DICTIONARY_REL], {"metrics": metrics, "count": len(metrics)},
        ["Use define_metric(name) for formula, inclusions/exclusions and caveats."])


@mcp.tool(annotations=READ_ONLY)
def define_metric(name: str) -> dict[str, Any]:
    """Full definition of one metric from docs/metric_dictionary.md: formula, inclusions/exclusions,
    example and caveats. `name` is case-insensitive: key, abbreviation or full name (e.g. 'CAC',
    'customer acquisition cost', 'iROAS', 'contribution_margin')."""
    lookup = _metric_lookup()
    m = lookup.get(str(name or "").strip().lower())
    if m is None:
        keys = [x["key"] for x in _parse_dictionary()]
        raise ToolError(f"Unknown metric '{name}'. Valid values: {_valid_list(keys)}")
    return _envelope({m["key"]: m["definition"]}, [DICTIONARY_REL],
                     {k: m[k] for k in ("key", "name", "definition", "formula", "includes", "excludes",
                                        "example", "details", "notes", "section_markdown")},
                     [f"Break-even ROAS = 1 / contribution margin before marketing = 1 / {CM_RATE:.2f} = {BREAK_EVEN_ROAS:.2f}."]
                     if m["key"] in ("roas", "iroas") else [])


@mcp.tool(annotations=READ_ONLY)
def get_kpis(market: str = "all", channel: str = "all", start: str | None = None,
             end: str | None = None) -> dict[str, Any]:
    """Spend, orders, net revenue, MER, CAC and contribution margin for a market, channel and date range,
    computed with the metric dictionary's formulas on data/simulated_weekly_data.csv (simulated data).

    market: all, DE, AT, FR, NL, UK, SE. channel: all, Google, Meta, Affiliates, TikTok, SEO, Email, Direct_Other.
    start / end: ISO dates (YYYY-MM-DD), inclusive on week_start; default = full period 2024-10-28 to 2026-10-19.
    With a channel filter, MER is null (it is an all-channel metric) and simulated_incremental_roas is returned."""
    mk = _resolve(market, MARKETS, "market")
    ch = _resolve(channel, CHANNELS, "channel")
    s = _parse_date(start, FIRST_WEEK, "start")
    e = _parse_date(end, LAST_WEEK, "end")
    if s > e:
        raise ToolError(f"Start date {s} is after end date {e}.")
    row = _con().execute(f"""
        SELECT COUNT(DISTINCT week_start), MIN(week_start), MAX(week_start),
               SUM(spend_eur), SUM(orders), SUM(net_revenue_eur)
        FROM read_csv_auto('{DATA_REL}')
        WHERE (? = 'all' OR market = ?) AND (? = 'all' OR channel = ?)
          AND week_start BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)""", [mk, mk, ch, ch, s, e]).fetchone()
    n_weeks, w0, w1, spend, orders, rev = row
    if not n_weeks:
        raise ToolError(f"No weeks between {s} and {e}. Weeks start on Mondays; data covers {FIRST_WEEK} to {LAST_WEEK}.")
    spend, orders, rev = float(spend), int(orders), float(rev)
    cm_before = CM_RATE * rev
    cm_after = cm_before - spend
    ratio = round(rev / spend, 4) if spend > 0 else None
    cac = round(spend / orders, 2) if spend > 0 and orders > 0 else None

    result: dict[str, Any] = {
        "filters": {"market": mk, "channel": ch, "start": s, "end": e},
        "weeks": int(n_weeks), "first_week": w0.isoformat(), "last_week": w1.isoformat(),
        "spend_eur": round(spend, 2), "orders": orders, "net_revenue_eur": round(rev, 2),
        "net_revenue_label": "net of VAT and cancellations" + (f"; {INCREMENTAL_LABEL}" if ch != "all" else ""),
        "mer": ratio if ch == "all" else None,
    }
    if ch != "all":
        result["mer_note"] = "MER is defined over all channels (no attribution), so it is not computed for one channel."
        result["simulated_incremental_roas"] = ratio
        result["simulated_incremental_roas_label"] = f"channel incremental revenue / channel spend ({VALIDATION_ONLY})"
    result["cac_eur"] = cac
    result["cac_label"] = ("blended CAC: all marketing spend / all new customers (orders)" if ch == "all"
                           else f"simulated incremental CAC: channel spend / orders the channel caused ({VALIDATION_ONLY})")
    if cac is None:
        result["cac_note"] = "No spend (or no orders) in the selection, so CAC is undefined."
    if ratio is None:
        result["ratio_note"] = "No spend in the selection, so MER / ROAS-type ratios are undefined."
    result.update({
        "cm_before_marketing_eur": round(cm_before, 2),
        "cm_after_marketing_eur": round(cm_after, 2),
        "cm_after_marketing_pct": round(cm_after / rev, 4) if rev else None,
        "cm_formula": f"before marketing = {CM_RATE:.0%} x net revenue ({GROSS_MARGIN:.0%} gross margin - {VAR_COST:.0%} variable costs); after marketing = that - spend",
    })

    defs = {"MER": _definition("mer"),
            "CAC": _definition("cac") + " Orders = new customers (assumption: no repeat purchases, see docs/assumptions.md).",
            "Contribution margin": _definition("contribution_margin")}
    if ch != "all":
        defs["iROAS"] = _definition("iroas")
    caveats = []
    if int(n_weeks) < LAG_WEEKS:
        caveats.append(f"Window is {n_weeks} weeks: with a 30-90 day buying window, orders and revenue in it partly "
                       "come from spend in earlier weeks, so MER and CAC are distorted for short windows.")
    sources = [DATA_REL, DICTIONARY_REL, ASSUMPTIONS_REL, CALENDAR_REL]
    cal = _calendar()
    for _, ev in cal[cal.event == "promo"].iterrows():
        overlaps_time = ev.start_week <= e and ev.end_week >= s
        overlaps_mkt = mk == "all" or mk in ev.markets.split(",")
        if overlaps_time and overlaps_mkt:
            month = date.fromisoformat(ev.start_week).strftime("%B %Y")
            disc = _parse_discount(_read(TESTS["discount"][0]))          # per-order CM figures from the discount analysis
            caveats.append(f"Includes promo weeks ({month}): CM is overstated for those weeks, because discounted "
                           f"outdoor-furniture orders earn about {disc['cm_per_order_discounted']:.0%} CM "
                           f"instead of {disc['cm_per_order_regular']:.0%}.")
            sources.append(TESTS["discount"][0])
    if ch != "all":
        caveats.append("Channel-level net revenue is the simulation's causal truth; a real analytics tool could not split revenue this way.")
    return _envelope(defs, sources, result, caveats)


@mcp.tool(annotations=READ_ONLY)
def compare_roas(channel: str = "all") -> dict[str, Any]:
    """Platform-reported ROAS vs simulated true incremental ROAS per paid channel (full period, all markets),
    with the break-even ROAS line (1 / 0.55 = 1.82). Meta also gets the geo-holdout iROAS and interval.
    attributed_roas: model-credited ROAS from the journey simulation (observed paths): all 8 attribution model
    variants at a 90-day lookback, plus last non-direct click at 7 / 30 / 90 / 365 days.
    channel: all, Google, Meta, Affiliates, TikTok, SEO, Email. Simulated data."""
    valid = [c for c in CHANNELS if c != "Direct_Other"]
    ch = _resolve(channel, valid, "channel")
    df = _con().execute(f"""
        SELECT channel, SUM(spend_eur) AS spend, SUM(platform_reported_revenue_eur) AS platform_rev,
               SUM(net_revenue_eur) AS channel_rev
        FROM read_csv_auto('{DATA_REL}')
        WHERE channel <> 'Direct_Other' AND (? = 'all' OR channel = ?)
        GROUP BY channel ORDER BY spend DESC""", [ch, ch]).df()
    holdout = _parse_meta(_read(TESTS["meta_holdout"][0]))
    attribution = _attribution_blocks()
    missing = {"status": f"not available: run {ATTRIBUTION_SCRIPT_REL} to create {ATTRIBUTION_REL}", "models_90d": {}}
    rows = []
    for r in df.itertuples():
        plat = None if pd.isna(r.platform_rev) else float(r.platform_rev)
        p_roas = round(plat / r.spend, 4) if plat is not None else None
        t_roas = round(r.channel_rev / r.spend, 4)
        rows.append({
            "channel": r.channel,
            "spend_eur": round(float(r.spend), 2),
            "platform_reported_revenue_eur": round(plat, 2) if plat is not None else None,
            "incremental_revenue_eur": round(float(r.channel_rev), 2),
            "platform_roas": p_roas,
            "simulated_true_iroas": t_roas,
            "simulated_true_iroas_label": VALIDATION_ONLY,
            "overstatement_ratio": round(plat / r.channel_rev, 4) if plat is not None else None,
            "platform_above_break_even": (p_roas >= BREAK_EVEN_ROAS) if p_roas is not None else None,
            "true_above_break_even": t_roas >= BREAK_EVEN_ROAS,
            "attributed_roas": (attribution or {}).get(r.channel, missing),
            "holdout": ({"iroas": holdout["iroas"], "ci_95": holdout["iroas_ci_95"], "market": "DE",
                         "verdict": holdout["verdict"], "source": TESTS["meta_holdout"][0]}
                        if r.channel == "Meta" else None),
        })
    result = {"break_even_roas": round(BREAK_EVEN_ROAS, 4),
              "break_even_formula": f"1 / contribution margin before marketing = 1 / {CM_RATE:.2f}",
              "scope": f"full period {FIRST_WEEK} to {LAST_WEEK}, all markets", "channels": rows}
    caveats = [
        "simulated_true_iroas = channel incremental revenue / channel spend. It is known only because the data is "
        "simulated (validation only: not observable in real data). Real decisions need incrementality tests.",
        "Platform revenue is dated by click week, incremental revenue by order week; full-period totals are compared.",
        "Meta's figures include the DE holdout weeks (zero spend, lagged revenue still arriving).",
    ]
    if any(r["channel"] == "SEO" for r in rows):
        caveats.append("SEO has no ad platform, so platform ROAS is null.")
    sources = [DATA_REL, DICTIONARY_REL, ASSUMPTIONS_REL, TESTS["meta_holdout"][0]]
    defs = {"ROAS (platform)": _definition("roas"), "iROAS": _definition("iroas"),
            "Break-even ROAS": f"1 / {CM_RATE:.2f} = {BREAK_EVEN_ROAS:.2f}"}
    if attribution is not None:
        sources.append(ATTRIBUTION_REL)
        defs["Model-credited ROAS"] = MODEL_CREDITED_LABEL
        caveats += [
            "attributed_roas comes from the user-journey simulation (one-year cohort), not from the 104-week weekly "
            "dataset: compare it with journey_true_iroas in the same block, not with simulated_true_iroas.",
            "Attribution models split credit for orders; they do not measure what a channel caused. "
            "70% of simulated orders have a zero-lift navigational session just before purchase (a design choice), "
            "which drives the last-click results.",
        ]
    return _envelope(defs, sources, result, caveats)


@mcp.tool(annotations=READ_ONLY)
def run_quality_check(name: str) -> dict[str, Any]:
    """Run one of the four tracking-quality SQL checks in sql/ (DuckDB) and return its status table.
    name: 01 / platform_vs_analytics_gap, 02 / weekly_volume_anomalies, 03 / spend_vs_sessions_sanity,
    04 / revenue_reconciliation. Simulated data."""
    stem = _resolve_check(name)
    rel = f"sql/{stem}.sql"
    sql = _read(rel)
    header = _parse_sql_header(sql)
    df = _con().execute(sql).df()
    rows = [{k: _jsonable(v) for k, v in rec.items()} for rec in df.to_dict("records")]
    severity = {"OK": 0, "FLAG": 1, "WARN": 2, "FAIL": 3}
    if not rows:
        overall = "OK: nothing flagged"
    elif "status" in df.columns:
        overall = max((r["status"] for r in rows), key=lambda x: severity.get(x, 1))
    else:
        overall = "FLAG"
    result = {"check": stem, "file": rel, "description": header.get("check"), "method": header.get("method"),
              "rule": header.get("rule"), "action": header.get("action"), "note": header.get("note"),
              "columns": list(df.columns), "row_count": len(rows), "rows": rows, "overall_status": overall}
    caveats = []
    if stem.startswith("01"):
        result["column_notes"] = {
            "platform_roas": "platform-reported revenue / spend",
            "channel_roas": f"channel incremental revenue / spend: simulated incremental ROAS, not analytics-attributed ({VALIDATION_ONLY})",
            "claim_ratio": "platform-reported revenue / incremental revenue the channel caused",
        }
    if stem.startswith("02"):
        caveats.append("A flag is a prompt to investigate (check data/events_calendar.csv), not proof of a tracking break.")
    defs = {k: v for k, v in header.items() if k in ("check", "method", "rule", "note") and v}
    return _envelope(defs, [rel, DATA_REL], result, caveats)


@mcp.tool(annotations=READ_ONLY)
def get_test_result(test: str) -> dict[str, Any]:
    """Result of an incrementality test from analysis/*_results.txt, including the 95% interval.
    test: 'meta_holdout' (Germany Meta geo holdout; aliases meta, holdout) or 'discount' (spring promo; alias promo).
    Simulated data."""
    key = TEST_ALIASES.get(str(test or "").strip().lower())
    if key is None:
        raise ToolError(f"Unknown test '{test}'. Valid values: meta_holdout, discount")
    txt_rel, script_rel = TESTS[key]
    text = _read(txt_rel)
    result = _parse_meta(text) if key == "meta_holdout" else _parse_discount(text)
    result["raw_text"] = text
    caveats = ["The 95% intervals come from placebo tests on the pre-period (see the script docstring)."]
    if key == "meta_holdout":
        defs = {"iROAS": _definition("iroas"),
                "Break-even ROAS": f"1 / {CM_RATE:.2f} = {BREAK_EVEN_ROAS:.2f}",
                "Method": "synthetic control on DE orders (controls AT, FR, NL, UK, SE); iROAS = incremental net revenue lost / Meta spend saved"}
        caveats.append("One noisy test in one market: the interval is wide. Halo effects on Google/SEO are not isolated.")
    else:
        defs = {"Contribution margin": _definition("contribution_margin"),
                "Method": "promo markets (DE, AT, FR, NL) vs UK+SE control, pre-period ratio counterfactual; "
                          "break-even lift = regular CM per order / discounted CM per order - 1"}
    return _envelope(defs, [txt_rel, script_rel], result, caveats)


if __name__ == "__main__":
    mcp.run()
