"""The five steering-hub views and their drilldowns. ALL DATA IS SIMULATED (fictional brand "Nordvik Outdoor").

Reuse rule: every number comes from the existing tools in mcp_server/server.py (get_kpis, compare_roas,
run_quality_check, plus its metric-dictionary helpers) or is read as published from a repo file
(analysis/attribution_comparison.csv, analysis/conversion_lag_results.txt, data/simulated_weekly_data.csv).
Nothing here re-implements a formula: this module selects, renames and hides fields.

Truth rule: channel-level incremental revenue and the ratios built on it are the simulation's truth. They appear
only in the leadership overlay (roas_lenses) or the leadership-overlay drilldown of check 01, labelled
"validation only: not observable in real data".
"""
from __future__ import annotations

import copy
import time
from functools import lru_cache
from typing import Any

import pandas as pd
from mcp.server.fastmcp.exceptions import ToolError

from . import REPO_ROOT
from . import access
from mcp_server import server as s


class InvalidInput(Exception):
    """Bad request: HTTP 400 with {"error", "access_denied": false}."""


class ViewDataError(Exception):
    """A source file is missing or its format changed: HTTP 500."""


CONV_LAG_REL = "analysis/conversion_lag_results.txt"
CONV_LAG_SCRIPT_REL = "analysis/04_conversion_lag_cohorts.py"
PAID = [c for c in s.CHANNELS if c != "Direct_Other"]
CHECKPOINTS = [7, 30, 90, 180, 365]
PAYBACK_HORIZONS = [30, 90, 365]
LAG_PATHS = ["all", "self_serve", "lead"]
STATUS_LEVELS = ["OK", "WARN", "FLAG", "FAIL"]
CHECK_01_TRUTH_COLUMNS = ["channel_roas", "claim_ratio"]
DRILLDOWN_COLUMNS = ["week_start", "market", "spend_eur", "sessions", "platform_reported_revenue_eur"]
ATTRIBUTION_DRILL_COLUMNS = ["view", "model", "lookback_days", "channel", "model_roas", "ga4_lookback_supported"]

# field names that carry the simulation's channel truth: never in a response outside the leadership overlay
TRUTH_FIELDS = frozenset({
    "simulated_true_iroas", "journey_true_iroas", "incremental_revenue_eur", "overstatement_ratio",
    "true_above_break_even", "simulated_incremental_roas", "channel_roas", "claim_ratio", "true_iroas",
    "true_incremental_orders", "true_incremental_revenue_eur", "true_share", "credit_to_true_ratio",
})

BUSINESS_METRICS = {
    "mer": {"field": "mer", "label": "MER (total net revenue / total marketing spend)", "unit": "ratio"},
    "cac": {"field": "cac_eur", "label": "Blended CAC (EUR): all marketing spend / new customers", "unit": "EUR"},
    "cm_after_marketing": {"field": "cm_after_marketing_eur", "label": "Contribution margin after marketing (EUR)",
                           "unit": "EUR"},
}
GROUP_BY = ["market", "week"]


# ---------------------------------------------------------------- cached tool calls (data is read-only)
@lru_cache(maxsize=1024)
def _kpis_cached(market: str, start: str | None, end: str | None) -> dict[str, Any]:
    return s.get_kpis(market, "all", start, end)


def _kpis(market: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    return copy.deepcopy(_kpis_cached(market, start, end))


@lru_cache(maxsize=16)
def _compare_cached(channel: str) -> dict[str, Any]:
    return s.compare_roas(channel)


def _compare(channel: str = "all") -> dict[str, Any]:
    return copy.deepcopy(_compare_cached(channel))


@lru_cache(maxsize=8)
def _quality_cached(number: str) -> dict[str, Any]:
    return s.run_quality_check(number)


def _quality(number: str) -> dict[str, Any]:
    return copy.deepcopy(_quality_cached(number))


WARM_ORDER = ["all", "DE"] + [m for m in s.MARKETS if m not in ("all", "DE")]


def warm_cache(pause_s: float = 0.005) -> None:
    """Pre-compute the slow weekly business_health series (104 get_kpis calls per market) for every market:
    the default and the country manager's market first. Runs only in a background thread started by
    `python mcp_app/api.py` (never by create_app, so never in the tests). The short pause after each call
    lets request threads take the interpreter lock, so the API keeps answering while it warms up."""
    for market in WARM_ORDER:
        for w in s.WEEKS:
            _kpis_cached(market, w, w)
            time.sleep(pause_s)


# ---------------------------------------------------------------- helpers
def _uniq(items: list[Any]) -> list[Any]:
    out: list[Any] = []
    for x in items:
        if x not in out:
            out.append(x)
    return out


def _envelope(role: str, view: str, options: dict[str, Any], result: dict[str, Any], definitions: dict[str, str],
              sources: list[str], caveats: list[str], segment: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "data_origin": "simulated",
        "notice": s.NOTICE,
        "definitions_used": definitions,
        "conventions": s.CONVENTIONS,
        "sources": _uniq(sources),
        "caveats": _uniq(caveats),
        "role": role,
        "view": view,
        "options": options,
    }
    if segment is not None:
        out["segment"] = segment
    out["result"] = result
    return out


def meta_envelope(result: dict[str, Any], sources: list[str] | None = None,
                  caveats: list[str] | None = None) -> dict[str, Any]:
    """Envelope for the non-view routes (roles, views list, audit)."""
    return {"data_origin": "simulated", "notice": s.NOTICE, "definitions_used": {}, "conventions": s.CONVENTIONS,
            "sources": sources or [], "caveats": caveats or [], "result": result}


def _options(options: Any, allowed: dict[str, Any]) -> dict[str, Any]:
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise InvalidInput("options must be a JSON object.")
    unknown = sorted(set(options) - set(allowed))
    if unknown:
        valid = ", ".join(allowed) if allowed else "none"
        raise InvalidInput(f"Unknown option(s) {', '.join(unknown)}. Valid options for this view: {valid}")
    return {k: options.get(k, default) for k, default in allowed.items()}


def _segment(segment: Any, required: list[str] | None = None, one_of: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(segment, dict):
        raise InvalidInput("segment must be a JSON object.")
    keys = set(segment)
    if required is not None and keys != set(required):
        raise InvalidInput(f"segment must have exactly the key(s): {', '.join(required)}")
    if one_of is not None and (len(keys) != 1 or not keys <= set(one_of)):
        raise InvalidInput(f"segment must have exactly one of: {', '.join(one_of)}")
    return segment


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidInput(f"Option '{name}' must be true or false.")
    return value


def _enum(value: Any, valid: list[str], name: str) -> str:
    key = str(value).strip().lower() if value is not None else ""
    lookup = {v.lower(): v for v in valid}
    if key not in lookup:
        raise InvalidInput(f"Unknown {name} '{value}'. Valid values: {', '.join(valid)}")
    return lookup[key]


def _paid_channel(value: Any) -> str:
    if value is None or str(value).strip() == "" or str(value).strip().lower() == "all":
        raise InvalidInput(f"Pick one channel. Valid values: {', '.join(PAID)}")
    return s._resolve(value, PAID, "channel")          # ToolError for unknown values -> 400


def _market(role: str, requested: Any) -> str:
    return s._resolve(access.resolve_market(role, requested), s.MARKETS, "market")


# ---------------------------------------------------------------- 1. roas_lenses
LND_REPLACEMENT_CAVEAT = ("Last non-direct ROAS comes from the user-journey simulation (one-year cohort, observed "
                          "paths), not from the 104-week weekly dataset that platform ROAS uses.")


def _roas_caveats(caveats: list[str], overlay: bool) -> list[str]:
    """Tool caveats as returned; without the overlay, the ones that refer to truth fields are replaced or dropped."""
    if overlay:
        return list(caveats)
    out = []
    for c in caveats:
        if c.startswith("attributed_roas comes from the user-journey simulation"):
            out.append(LND_REPLACEMENT_CAVEAT)
        elif any(f in c for f in TRUTH_FIELDS):
            continue
        else:
            out.append(c)
    return out


def roas_lenses_run(role: str, options: Any) -> dict[str, Any]:
    opts = _options(options, {"overlay": False})
    overlay = access.check_overlay(role, _bool(opts["overlay"], "overlay"))
    env = _compare("all")
    r = env["result"]
    channels, truth = [], []
    lnd_scope = None
    for row in r["channels"]:
        a = row["attributed_roas"]
        available = a.get("status") == "available"
        h = row["holdout"]
        out = {
            "channel": row["channel"],
            "spend_eur": row["spend_eur"],
            "platform_reported_revenue_eur": row["platform_reported_revenue_eur"],
            "platform_roas": row["platform_roas"],
            "last_non_direct_roas_90d": a["last_non_direct_by_lookback_days"]["90"] if available else None,
            "tested_iroas": ({"value": h["iroas"], "ci_95": h["ci_95"], "market": h["market"],
                              "verdict": h["verdict"], "source": h["source"]} if h else None),
        }
        if row["platform_roas"] is None:
            out["note"] = "No ad platform, so no platform ROAS."
        if not available:
            out["last_non_direct_note"] = a.get("status")
        lnd_scope = lnd_scope or (a.get("scope") if available else None)
        channels.append(out)
        truth.append({"channel": row["channel"], "simulated_true_iroas": row["simulated_true_iroas"],
                      "journey_true_iroas": a.get("journey_true_iroas") if available else None})
    result: dict[str, Any] = {
        "break_even_roas": r["break_even_roas"],
        "break_even_formula": r["break_even_formula"],
        "scope": r["scope"],
        "lenses": {
            "platform_roas": "platform-reported revenue / spend: what the platform claims (weekly dataset)",
            "last_non_direct_roas_90d": f"{s.MODEL_CREDITED_LABEL}; last non-direct click, 90-day lookback",
            "tested_iroas": "incremental ROAS from the Germany geo holdout, with its 95% interval",
        },
        "last_non_direct_scope": lnd_scope,
        "channels": channels,
    }
    definitions = dict(env["definitions_used"])
    if overlay:
        result["overlay"] = {
            "label": s.VALIDATION_ONLY,
            "simulated_true_iroas_note": "channel incremental revenue / spend in the weekly dataset: compare with "
                                         "platform ROAS (same data and scope)",
            "journey_true_iroas_note": "true iROAS in the journey simulation: compare with last non-direct ROAS "
                                       "(same data and scope)",
            "channels": truth,
        }
        definitions["Simulated truth overlay"] = s.VALIDATION_ONLY
    return _envelope(role, "roas_lenses", opts, result, definitions, env["sources"],
                     _roas_caveats(env["caveats"], overlay))


def roas_lenses_drilldown(role: str, segment: Any, options: Any) -> dict[str, Any]:
    opts = _options(options, {"overlay": False})
    access.check_overlay(role, _bool(opts["overlay"], "overlay"))
    seg = _segment(segment, required=["channel"])
    ch = _paid_channel(seg["channel"])
    df = s._con().execute(
        f"SELECT {', '.join(DRILLDOWN_COLUMNS)} FROM read_csv_auto('{s.DATA_REL}') WHERE channel = ?", [ch]).df()
    order = {m: i for i, m in enumerate(s.MARKETS)}
    df = df.assign(_m=df.market.map(order)).sort_values(["week_start", "_m"]).drop(columns="_m")
    rows = [{k: s._jsonable(rec[k]) for k in DRILLDOWN_COLUMNS} for rec in df.to_dict("records")]
    caveats = ["Observable columns only, as recorded per week and market. Platform revenue is dated by click week."]
    if ch == "SEO":
        caveats.append("SEO has no ad platform, so platform revenue is null.")
    if ch == "Meta":
        caveats.append("Meta spend is zero in DE during the holdout weeks.")
    definitions = {"Columns": "week_start, market, spend_eur (ex VAT), sessions, platform_reported_revenue_eur "
                              "(the platform's own claim, restated to net revenue)"}
    result = {"channel": ch, "columns": DRILLDOWN_COLUMNS, "row_count": len(rows), "rows": rows}
    return _envelope(role, "roas_lenses", opts, result, definitions, [s.DATA_REL, s.ASSUMPTIONS_REL], caveats,
                     segment={"channel": ch})


# ---------------------------------------------------------------- 2. business_health
def _business_options(role: str, options: Any) -> dict[str, Any]:
    opts = _options(options, {"metric": "mer", "group_by": "market", "market": None})
    return {"metric": _enum(opts["metric"], list(BUSINESS_METRICS), "metric"),
            "group_by": _enum(opts["group_by"], GROUP_BY, "group_by"),
            "market": _market(role, opts["market"])}


def _merge(envs: list[dict[str, Any]]) -> tuple[dict[str, str], list[str], list[str]]:
    definitions: dict[str, str] = {}
    sources: list[str] = []
    caveats: list[str] = []
    for e in envs:
        definitions.update(e["definitions_used"])
        sources += e["sources"]
        caveats += e["caveats"]
    return definitions, _uniq(sources), _uniq(caveats)


def business_health_run(role: str, options: Any) -> dict[str, Any]:
    opts = _business_options(role, options)
    metric = BUSINESS_METRICS[opts["metric"]]
    mk = opts["market"]
    if opts["group_by"] == "market":
        pairs = [(m, _kpis(m)) for m in (s.MARKETS if mk == "all" else [mk])]
    else:
        pairs = [(w, _kpis(mk, w, w)) for w in s.WEEKS]
    points = [{"segment": seg, "value": e["result"][metric["field"]]} for seg, e in pairs]
    definitions, sources, caveats = _merge([e for _, e in pairs])
    result = {
        "metric": opts["metric"], "metric_field": metric["field"], "metric_label": metric["label"],
        "unit": metric["unit"], "group_by": opts["group_by"], "market": mk,
        "chart": "bar" if opts["group_by"] == "market" else "line",
        "period": f"{s.FIRST_WEEK} to {s.LAST_WEEK}" + (" (one point per full period)" if opts["group_by"] == "market"
                                                         else " (one point per week)"),
        "points": points,
    }
    return _envelope(role, "business_health", opts, result, definitions, sources, caveats)


def business_health_drilldown(role: str, segment: Any, options: Any) -> dict[str, Any]:
    opts = _business_options(role, options)
    seg = _segment(segment, one_of=["market", "week"])
    if "market" in seg:
        m = _market(role, seg["market"])
        if m == "all":
            raise InvalidInput(f"Pick one market. Valid values: {', '.join(s.MARKETS)}")
        env, segment_out = _kpis(m), {"market": m}
    else:
        w = str(seg["week"]).strip()
        if w not in s.WEEKS:
            raise InvalidInput(f"Unknown week '{seg['week']}'. Use a week_start (Monday, YYYY-MM-DD) between "
                               f"{s.FIRST_WEEK} and {s.LAST_WEEK}.")
        m = opts["market"]
        env, segment_out = _kpis(m, w, w), {"week": w}
    r = env["result"]
    result = {"market": r["filters"]["market"], "first_week": r["first_week"], "last_week": r["last_week"],
              "weeks": r["weeks"], "spend_eur": r["spend_eur"], "orders": r["orders"],
              "net_revenue_eur": r["net_revenue_eur"], "net_revenue_label": r["net_revenue_label"], "mer": r["mer"]}
    return _envelope(role, "business_health", opts, result, env["definitions_used"], env["sources"], env["caveats"],
                     segment=segment_out)


# ---------------------------------------------------------------- 3. attribution_sensitivity
def _attribution_block(ch: str) -> tuple[dict[str, Any], dict[str, Any]]:
    env = _compare(ch)
    a = env["result"]["channels"][0]["attributed_roas"]
    if a.get("status") != "available":
        raise ViewDataError(str(a.get("status")))
    return env, a


def _attribution_caveats(env: dict[str, Any], a: dict[str, Any]) -> list[str]:
    kept = [c for c in env["caveats"] if c.startswith("Attribution models split credit")]
    return ["Model-credited ROAS comes from the user-journey simulation (one-year cohort, observed paths), "
            "not from the 104-week weekly dataset."] + kept + [a["lookback_note"]]


def attribution_run(role: str, options: Any) -> dict[str, Any]:
    opts = _options(options, {"channel": PAID[0]})
    ch = _paid_channel(opts["channel"])
    opts["channel"] = ch
    env, a = _attribution_block(ch)
    result = {
        "channel": ch, "view": "observed", "lookback_days": 90, "label": a["label"], "scope": a["scope"],
        "journey_spend_eur": a["journey_spend_eur"], "break_even_roas": env["result"]["break_even_roas"],
        "models": [{"model": m, "model_roas": a["models_90d"][m]} for m in s.ATTRIBUTION_MODELS],
    }
    definitions = {k: env["definitions_used"][k] for k in ("Model-credited ROAS", "Break-even ROAS")}
    return _envelope(role, "attribution_sensitivity", opts, result, definitions,
                     [s.ATTRIBUTION_REL, s.DICTIONARY_REL, s.ASSUMPTIONS_REL], _attribution_caveats(env, a))


def attribution_drilldown(role: str, segment: Any, options: Any) -> dict[str, Any]:
    opts = _options(options, {"channel": PAID[0]})
    ch = _paid_channel(opts["channel"])
    opts["channel"] = ch
    seg = _segment(segment, required=["model"])
    model = _enum(seg["model"], s.ATTRIBUTION_MODELS, "model")
    env, a = _attribution_block(ch)
    df = pd.read_csv(REPO_ROOT / s.ATTRIBUTION_REL, usecols=ATTRIBUTION_DRILL_COLUMNS)
    g = df[(df.view == "observed") & (df.channel == ch) & (df.model == model)].sort_values("lookback_days")
    by = [{"lookback_days": int(x.lookback_days), "model_roas": round(float(x.model_roas), 4),
           "ga4_lookback_supported": bool(x.ga4_lookback_supported)} for x in g.itertuples()]
    if [b["lookback_days"] for b in by] != s.ATTRIBUTION_LOOKBACKS:
        raise ViewDataError(f"{s.ATTRIBUTION_REL} does not have lookbacks {s.ATTRIBUTION_LOOKBACKS} for {ch} / {model}.")
    result = {"channel": ch, "model": model, "view": "observed", "label": a["label"],
              "break_even_roas": env["result"]["break_even_roas"], "by_lookback": by}
    definitions = {k: env["definitions_used"][k] for k in ("Model-credited ROAS", "Break-even ROAS")}
    return _envelope(role, "attribution_sensitivity", opts, result, definitions,
                     [s.ATTRIBUTION_REL, s.DICTIONARY_REL], _attribution_caveats(env, a), segment={"model": model})


# ---------------------------------------------------------------- 4. conversion_lag (parsed from the results file)
def _parse_conversion_lag(text: str) -> dict[str, Any]:
    m = s._match(r"First-click cohorts: weeks (\S+) to (\S+) \((\d+) weeks, ([\d,]+) people, ([\d,]+) orders\)",
                 text, "first-click cohorts")
    cohorts = {"first_week": m[1], "last_week": m[2], "weeks": int(m[3]), "people": int(s._num(m[4])),
               "orders": int(s._num(m[5]))}

    block = s._match(r"(?s)Share of the 365-day orders already visible\n(.*?)\n\s+Across weekly cohorts",
                     text, "share visible table")[1].strip("\n").splitlines()
    header = block[0].split()
    if header != [f"{d}d" for d in CHECKPOINTS]:
        raise ToolError(f"Could not parse 'share visible table' header {header} from the result file.")
    series = []
    for line in block[1:]:
        parts = line.split()
        if len(parts) != len(CHECKPOINTS) + 1 or not all(p.endswith("%") for p in parts[1:]):
            raise ToolError(f"Could not parse 'share visible' row '{line.strip()}' from the result file.")
        series.append({"path": parts[0], "share_visible": [s._pct(p[:-1]) for p in parts[1:]]})
    if [x["path"] for x in series] != LAG_PATHS:
        raise ToolError(f"Could not parse 'share visible' rows: expected {LAG_PATHS}.")

    m = s._match(r"share visible at day 30 ranges from ([\d.]+)% to ([\d.]+)% \(median ([\d.]+)%\)", text, "day-30 range")
    day30 = {"min": s._pct(m[1]), "max": s._pct(m[2]), "median": s._pct(m[3])}

    spend = s._num(s._match(r"Spend on these cohorts' touches: EUR ([\d,]+)", text, "payback spend")[1])
    formula = s._match(r"(Payback ratio = [^\n]*?)\.?\n", text, "payback formula")[1]
    s._match(r"(?m)^\s+30d\s+90d\s+365d\s*$", text, "payback header")
    rows: dict[str, list[float]] = {}
    for name in ("orders", "blended_cac_eur", "cm_per_order_eur", "payback_ratio"):
        mm = s._match(rf"(?m)^{name}\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$", text, f"payback row {name}")
        rows[name] = [s._num(mm[i]) for i in (1, 2, 3)]
    horizons = [{"horizon_days": d,
                 "orders": int(rows["orders"][i]),
                 "blended_cac_eur": rows["blended_cac_eur"][i],
                 "cm_per_order_eur": rows["cm_per_order_eur"][i],
                 "payback_ratio": rows["payback_ratio"][i]} for i, d in enumerate(PAYBACK_HORIZONS)]

    notes_part = text.split("\nNotes\n", 1)
    if len(notes_part) != 2:
        raise ToolError("Could not parse 'Notes' from the result file.")
    notes: list[str] = []
    for line in notes_part[1].splitlines():
        if line.startswith("- "):
            notes.append(line[2:].strip())
        elif line.strip() and notes:
            notes[-1] += " " + line.strip()
    return {"cohorts": cohorts, "series": series, "day30_weekly_range": day30, "payback_spend_eur": spend,
            "payback_ratio_formula": formula, "horizons": horizons, "notes": notes}


@lru_cache(maxsize=1)
def _conversion_lag_cached() -> dict[str, Any]:
    try:
        return _parse_conversion_lag(s._read(CONV_LAG_REL))
    except FileNotFoundError:
        raise ViewDataError(f"{CONV_LAG_REL} is missing: run {CONV_LAG_SCRIPT_REL}.")
    except ToolError as e:
        raise ViewDataError(f"{CONV_LAG_REL}: {e}")


def _conversion_lag() -> dict[str, Any]:
    return copy.deepcopy(_conversion_lag_cached())


LAG_SOURCES = [CONV_LAG_REL, CONV_LAG_SCRIPT_REL, s.DICTIONARY_REL]
ALL_MARKETS_CAVEAT = ("All markets pooled: the results file is not split by market, so this view cannot be "
                      "filtered to one market.")


def _lag_definitions() -> dict[str, str]:
    return {"Share visible": "orders placed within d days of the first click / orders within 365 days, pooled over "
                             "complete first-click cohorts",
            "Payback": s._definition("payback"),
            "CAC": s._definition("cac") + " Blended CAC here = all spend on the cohorts' touches / their orders."}


def conversion_lag_run(role: str, options: Any) -> dict[str, Any]:
    opts = _options(options, {})
    c = _conversion_lag()
    k = c["cohorts"]
    result = {
        "checkpoints_days": CHECKPOINTS,
        "scope": (f"all markets pooled; complete first-click cohorts {k['first_week']} to {k['last_week']} "
                  f"({k['weeks']} weeks, {k['people']:,} people, {k['orders']:,} orders); clock starts at the "
                  "first click"),
        "y_label": "share of the cohort's 365-day orders already visible",
        "series": c["series"],
        "day30_weekly_range": c["day30_weekly_range"],
    }
    return _envelope(role, "conversion_lag", opts, result, _lag_definitions(), LAG_SOURCES,
                     [ALL_MARKETS_CAVEAT] + c["notes"])


def conversion_lag_drilldown(role: str, segment: Any, options: Any) -> dict[str, Any]:
    opts = _options(options, {})
    seg = _segment(segment, required=["path", "day"])
    path = _enum(seg["path"], LAG_PATHS, "path")
    day = seg["day"]
    if isinstance(day, bool) or not isinstance(day, int) or day not in CHECKPOINTS:
        raise InvalidInput(f"Unknown day '{day}'. Valid values: {', '.join(map(str, CHECKPOINTS))}")
    c = _conversion_lag()
    share = next(x for x in c["series"] if x["path"] == path)["share_visible"][CHECKPOINTS.index(day)]
    result = {
        "clicked": {"path": path, "day": day, "share_visible": share},
        "payback_spend_eur": c["payback_spend_eur"],
        "payback_ratio_formula": c["payback_ratio_formula"],
        "horizons": c["horizons"],
        "highlight_horizon_days": day if day in PAYBACK_HORIZONS else None,
        "note": "Blended across all paths and all markets: the results file has no payback by path or market.",
    }
    return _envelope(role, "conversion_lag", opts, result, _lag_definitions(), LAG_SOURCES,
                     [ALL_MARKETS_CAVEAT] + c["notes"], segment={"path": path, "day": day})


# ---------------------------------------------------------------- 5. data_quality
CHECK_01_VALIDATION_NOTE = ("Check 01 compares platform revenue with the simulation's channel-level incremental "
                            f"revenue, so its status is {s.VALIDATION_ONLY}.")


def _flagged(r: dict[str, Any]) -> list[dict[str, Any]]:
    if "status" in r["columns"]:
        return [row for row in r["rows"] if row.get("status") != "OK"]
    return list(r["rows"])


def data_quality_run(role: str, options: Any) -> dict[str, Any]:
    opts = _options(options, {"overlay": False})
    access.check_overlay(role, _bool(opts["overlay"], "overlay"))
    tiles, definitions, sources, caveats = [], {}, [], []
    for num in s.QUALITY_CHECKS:
        env = _quality(num)
        r = env["result"]
        tile = {"number": num, "check": r["check"], "description": r["description"],
                "status": r["overall_status"].split(":")[0].strip(), "status_detail": r["overall_status"],
                "row_count": r["row_count"], "flagged_count": len(_flagged(r))}
        if num == "01":
            tile["validation_note"] = CHECK_01_VALIDATION_NOTE
        tiles.append(tile)
        definitions[r["check"]] = r["rule"]
        sources += env["sources"]
        caveats += env["caveats"]
    result = {"status_levels": STATUS_LEVELS, "tiles": tiles}
    return _envelope(role, "data_quality", opts, result, definitions, sources, caveats)


def data_quality_drilldown(role: str, segment: Any, options: Any) -> dict[str, Any]:
    opts = _options(options, {"overlay": False})
    overlay = access.check_overlay(role, _bool(opts["overlay"], "overlay"))
    seg = _segment(segment, required=["check"])
    stem = s._resolve_check(seg["check"])                 # ToolError for unknown checks -> 400
    num = stem[:2]
    env = _quality(num)
    r = env["result"]
    columns, rows = list(r["columns"]), _flagged(r)
    column_notes = dict(r.get("column_notes") or {})
    result: dict[str, Any] = {
        "number": num, "check": r["check"], "file": r["file"], "description": r["description"],
        "method": r["method"], "rule": r["rule"], "action": r["action"], "note": r["note"],
        "overall_status": r["overall_status"],
    }
    if r["action"] is None:
        result["action_note"] = "No action defined in the SQL file."
    if num == "01":
        result["validation_note"] = CHECK_01_VALIDATION_NOTE
        if not overlay:
            columns = [c for c in columns if c not in CHECK_01_TRUTH_COLUMNS]
            rows = [{k: v for k, v in row.items() if k not in CHECK_01_TRUTH_COLUMNS} for row in rows]
            column_notes = {k: v for k, v in column_notes.items() if k not in CHECK_01_TRUTH_COLUMNS}
            result["hidden_columns_note"] = ("Two columns built on the simulation's channel truth are hidden; "
                                             "leadership can show them with the validation overlay.")
    result.update({"columns": columns, "flagged_rows": rows, "flagged_count": len(rows),
                   "row_count_total": r["row_count"]})
    if column_notes:
        result["column_notes"] = column_notes
    return _envelope(role, "data_quality", opts, result, env["definitions_used"], env["sources"], env["caveats"],
                     segment={"check": num})


# ---------------------------------------------------------------- registry
OVERLAY_OPTION = {"type": "boolean", "default": False, "label": "Simulated truth (validation only)",
                  "roles": ["leadership"]}

VIEWS: dict[str, dict[str, Any]] = {
    "roas_lenses": {
        "label": "ROAS lenses", "chart": "grouped bars per paid channel with break-even line",
        "source": "compare_roas('all')", "drilldown": "channel -> weekly rows by market (observable columns only)",
        "segment_keys": ["channel"],
        "options": {"overlay": OVERLAY_OPTION},
        "run": roas_lenses_run, "drill": roas_lenses_drilldown,
    },
    "business_health": {
        "label": "Business health", "chart": "bar by market or line by week",
        "source": "get_kpis (channel = all)", "drilldown": "market or week -> spend, orders, net revenue, MER",
        "segment_keys": ["market", "week"],
        "options": {"metric": {"type": "enum", "values": list(BUSINESS_METRICS), "default": "mer"},
                    "group_by": {"type": "enum", "values": GROUP_BY, "default": "market"},
                    "market": {"type": "enum", "values": ["all"] + s.MARKETS, "default": "all"}},
        "run": business_health_run, "drill": business_health_drilldown,
    },
    "attribution_sensitivity": {
        "label": "Attribution sensitivity", "chart": "bars: model-credited ROAS under 8 models, break-even line",
        "source": f"{s.ATTRIBUTION_REL} (view = observed, lookback 90), via compare_roas(channel)",
        "drilldown": "model -> the same model at 7, 30, 90 and 365 days", "segment_keys": ["model"],
        "options": {"channel": {"type": "enum", "values": PAID, "default": PAID[0]}},
        "run": attribution_run, "drill": attribution_drilldown,
    },
    "conversion_lag": {
        "label": "Conversion lag", "chart": "lines: share of 365-day orders visible at 7-365 days",
        "source": CONV_LAG_REL, "drilldown": "point -> blended CAC and payback ratio at 30, 90 and 365 days",
        "segment_keys": ["path", "day"], "options": {},
        "run": conversion_lag_run, "drill": conversion_lag_drilldown,
    },
    "data_quality": {
        "label": "Data quality", "chart": "four status tiles (checks 01-04)",
        "source": "run_quality_check 01-04", "drilldown": "tile -> the check's rule, action and flagged rows",
        "segment_keys": ["check"], "options": {"overlay": OVERLAY_OPTION},
        "run": data_quality_run, "drill": data_quality_drilldown,
    },
}
assert list(VIEWS) == access.ALL_VIEWS


def _view(role: str, view: Any) -> dict[str, Any]:
    access.get_role(role)                                  # unknown role -> 403
    if view not in VIEWS:
        raise InvalidInput(f"Unknown view '{view}'. Valid views: {', '.join(VIEWS)}")
    access.check_view(role, view)                          # view not allowed for the role -> 403
    return VIEWS[view]


def list_views(role: Any) -> list[dict[str, Any]]:
    r = access.get_role(role)
    out = []
    for vid in r["views"]:
        v = VIEWS[vid]
        options = {}
        for name, spec in v["options"].items():
            if spec.get("roles") and role not in spec["roles"]:
                continue
            spec = dict(spec)
            if name == "market" and r["market_lock"]:
                spec.update(values=[r["market_lock"]], default=r["market_lock"])
            options[name] = spec
        out.append({"id": vid, **{k: v[k] for k in ("label", "chart", "source", "drilldown", "segment_keys")},
                    "options": options})
    return out


def run_view(role: Any, view: Any, options: Any = None) -> dict[str, Any]:
    return _view(role, view)["run"](role, options)


def get_drilldown(role: Any, view: Any, segment: Any, options: Any = None) -> dict[str, Any]:
    return _view(role, view)["drill"](role, segment, options)
