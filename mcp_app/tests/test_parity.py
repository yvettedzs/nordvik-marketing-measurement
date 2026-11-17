"""Parity: every view equals the mcp_server tool output or the published file value."""
import pandas as pd
import pytest

from conftest import CM, LEAD, PM, REPO
from mcp_server import server as s

PAID = ["Google", "Meta", "Affiliates", "TikTok", "SEO", "Email"]


def ok(resp):
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


@pytest.fixture(scope="module")
def csv():
    return pd.read_csv(REPO / "data" / "simulated_weekly_data.csv")


@pytest.fixture(scope="module")
def attribution():
    d = pd.read_csv(REPO / "analysis" / "attribution_comparison.csv")
    return d[d.view == "observed"]


# ---------------------------------------------------------------- envelope
@pytest.mark.parametrize("view", ["roas_lenses", "business_health", "attribution_sensitivity", "conversion_lag",
                                  "data_quality"])
def test_envelope(client, view):
    j = ok(client.run(LEAD, view))
    assert j["data_origin"] == "simulated"
    assert j["definitions_used"] and isinstance(j["definitions_used"], dict)
    assert j["sources"] and all(isinstance(x, str) for x in j["sources"])
    assert isinstance(j["caveats"], list)
    assert j["view"] == view and j["role"] == LEAD and "result" in j


# ---------------------------------------------------------------- roas_lenses
def test_roas_lenses_matches_compare_roas(client, attribution):
    res = ok(client.run(PM, "roas_lenses"))["result"]
    ref = s.compare_roas("all")["result"]
    assert res["break_even_roas"] == ref["break_even_roas"] and round(res["break_even_roas"], 2) == 1.82
    rows = {r["channel"]: r for r in res["channels"]}
    refs = {r["channel"]: r for r in ref["channels"]}
    assert list(rows) == list(refs) and set(rows) == set(PAID)
    for ch, r in rows.items():
        assert r["platform_roas"] == refs[ch]["platform_roas"]
        assert r["spend_eur"] == refs[ch]["spend_eur"]
        assert r["last_non_direct_roas_90d"] == refs[ch]["attributed_roas"]["last_non_direct_by_lookback_days"]["90"]
        csv_val = attribution[(attribution.channel == ch) & (attribution.model == "last_non_direct")
                              & (attribution.lookback_days == 90)].model_roas.iloc[0]
        assert r["last_non_direct_roas_90d"] == round(float(csv_val), 4)
        assert (r["tested_iroas"] is not None) == (ch == "Meta")
    meta = rows["Meta"]["tested_iroas"]
    assert meta["value"] == 2.45 and meta["ci_95"] == [1.01, 3.89] and meta["market"] == "DE"
    assert rows["SEO"]["platform_roas"] is None


@pytest.mark.parametrize("channel", ["Meta", "SEO"])
def test_roas_lenses_drilldown_matches_csv(client, csv, channel):
    res = ok(client.drill(PM, "roas_lenses", {"channel": channel}))["result"]
    cols = ["week_start", "market", "spend_eur", "sessions", "platform_reported_revenue_eur"]
    assert res["columns"] == cols
    assert all(list(r) == cols for r in res["rows"])
    ref = csv[csv.channel == channel]
    assert res["row_count"] == len(ref) == 104 * 6
    got = pd.DataFrame(res["rows"]).sort_values(["week_start", "market"]).reset_index(drop=True)
    exp = ref[cols].sort_values(["week_start", "market"]).reset_index(drop=True)
    assert (got.week_start == exp.week_start).all() and (got.market == exp.market).all()
    assert (abs(got.spend_eur - exp.spend_eur) < 0.005).all()
    assert (got.sessions == exp.sessions).all()
    if channel == "SEO":
        assert got.platform_reported_revenue_eur.isna().all()
    else:
        assert (abs(got.platform_reported_revenue_eur - exp.platform_reported_revenue_eur) < 0.005).all()
    assert res["rows"][0]["week_start"] == s.FIRST_WEEK and res["rows"][0]["market"] == "DE"


# ---------------------------------------------------------------- business_health
@pytest.mark.parametrize("metric,field", [("mer", "mer"), ("cac", "cac_eur"),
                                          ("cm_after_marketing", "cm_after_marketing_eur")])
def test_business_health_by_market_matches_get_kpis(client, csv, metric, field):
    res = ok(client.run(LEAD, "business_health", {"metric": metric, "group_by": "market"}))["result"]
    assert [p["segment"] for p in res["points"]] == s.MARKETS and res["chart"] == "bar"
    for p in res["points"]:
        assert p["value"] == s.get_kpis(p["segment"])["result"][field]
        if metric == "mer":                                    # independent pandas cross-check
            g = csv[csv.market == p["segment"]]
            assert abs(p["value"] - g.net_revenue_eur.sum() / g.spend_eur.sum()) < 1e-4


def test_business_health_by_week_matches_get_kpis(client, csv):
    j = ok(client.run(CM, "business_health", {"metric": "mer", "group_by": "week"}))
    res = j["result"]
    assert res["market"] == "DE" and res["chart"] == "line"
    assert [p["segment"] for p in res["points"]] == s.WEEKS and len(s.WEEKS) == 104
    de = csv[csv.market == "DE"].groupby("week_start")[["net_revenue_eur", "spend_eur"]].sum()
    for p in res["points"]:
        ref = de.loc[p["segment"]]
        assert abs(p["value"] - ref.net_revenue_eur / ref.spend_eur) < 1e-4
    for i in (0, 50, 70, 103):                                 # sample checked against the tool itself
        w = s.WEEKS[i]
        assert res["points"][i]["value"] == s.get_kpis("DE", "all", w, w)["result"]["mer"]
    short = [c for c in j["caveats"] if c.startswith("Window is 1 weeks")]
    assert len(short) == 1                                     # de-duplicated, shown once


def test_business_health_drilldowns_match_get_kpis(client):
    keys = ["spend_eur", "orders", "net_revenue_eur", "mer", "first_week", "last_week", "weeks"]
    res = ok(client.drill(LEAD, "business_health", {"market": "FR"}))["result"]
    ref = s.get_kpis("FR")["result"]
    assert {k: res[k] for k in keys} == {k: ref[k] for k in keys}
    res = ok(client.drill(LEAD, "business_health", {"week": "2026-03-02"}, {"market": "NL"}))["result"]
    ref = s.get_kpis("NL", "all", "2026-03-02", "2026-03-02")["result"]
    assert {k: res[k] for k in keys} == {k: ref[k] for k in keys} and res["market"] == "NL"


def test_business_health_promo_caveat_passed_through(client):
    j = ok(client.run(LEAD, "business_health"))
    assert any(c.startswith("Includes promo weeks (March 2026)") for c in j["caveats"])


# ---------------------------------------------------------------- attribution_sensitivity
@pytest.mark.parametrize("channel", PAID)
def test_attribution_matches_csv_and_compare_roas(client, attribution, channel):
    res = ok(client.run(PM, "attribution_sensitivity", {"channel": channel}))["result"]
    assert [m["model"] for m in res["models"]] == s.ATTRIBUTION_MODELS
    ref = s.compare_roas(channel)["result"]["channels"][0]["attributed_roas"]["models_90d"]
    g = attribution[(attribution.channel == channel) & (attribution.lookback_days == 90)].set_index("model")
    for m in res["models"]:
        assert m["model_roas"] == ref[m["model"]] == round(float(g.model_roas[m["model"]]), 4)
    assert round(res["break_even_roas"], 2) == 1.82


@pytest.mark.parametrize("model", ["last_click", "last_non_direct", "w_shaped"])
def test_attribution_drilldown_matches_csv(client, attribution, model):
    j = ok(client.drill(PM, "attribution_sensitivity", {"model": model}, {"channel": "Meta"}))
    by = j["result"]["by_lookback"]
    assert [b["lookback_days"] for b in by] == [7, 30, 90, 365]
    g = attribution[(attribution.channel == "Meta") & (attribution.model == model)].set_index("lookback_days")
    for b in by:
        assert b["model_roas"] == round(float(g.model_roas[b["lookback_days"]]), 4)
        assert b["ga4_lookback_supported"] == (b["lookback_days"] <= 90)
    run = ok(client.run(PM, "attribution_sensitivity", {"channel": "Meta"}))["result"]["models"]
    assert next(m["model_roas"] for m in run if m["model"] == model) == by[2]["model_roas"]


# ---------------------------------------------------------------- conversion_lag (published values)
def test_conversion_lag_matches_results_file(client):
    res = ok(client.run(CM, "conversion_lag"))["result"]
    assert res["checkpoints_days"] == [7, 30, 90, 180, 365]
    series = {x["path"]: x["share_visible"] for x in res["series"]}
    assert series == {"all": [0.005, 0.261, 0.807, 0.965, 1.0],
                      "self_serve": [0.006, 0.315, 0.899, 1.0, 1.0],
                      "lead": [0.001, 0.093, 0.521, 0.855, 1.0]}
    assert round(series["all"][1] * 100) == 26                 # README: "A 30-day window sees only 26%"
    assert res["day30_weekly_range"] == {"min": 0.226, "max": 0.314, "median": 0.26}
    assert "all markets pooled" in res["scope"]


def test_conversion_lag_drilldown_payback(client):
    j = ok(client.drill(LEAD, "conversion_lag", {"path": "lead", "day": 90}))
    res = j["result"]
    assert res["clicked"] == {"path": "lead", "day": 90, "share_visible": 0.521}
    assert res["highlight_horizon_days"] == 90
    assert res["horizons"] == [
        {"horizon_days": 30, "orders": 7752, "blended_cac_eur": 2789, "cm_per_order_eur": 1738, "payback_ratio": 0.62},
        {"horizon_days": 90, "orders": 23947, "blended_cac_eur": 903, "cm_per_order_eur": 1847, "payback_ratio": 2.05},
        {"horizon_days": 365, "orders": 29658, "blended_cac_eur": 729, "cm_per_order_eur": 1980, "payback_ratio": 2.72},
    ]
    # docs/metric_dictionary.md: "about EUR 2,790 (payback ratio 0.6) against about EUR 730 after 365 days (2.7)"
    h = {x["horizon_days"]: x for x in res["horizons"]}
    assert round(h[30]["blended_cac_eur"], -1) == 2790 and round(h[30]["payback_ratio"], 1) == 0.6
    assert round(h[365]["blended_cac_eur"], -1) == 730 and round(h[365]["payback_ratio"], 1) == 2.7
    assert ok(client.drill(LEAD, "conversion_lag", {"path": "all", "day": 7}))["result"]["highlight_horizon_days"] is None


# ---------------------------------------------------------------- data_quality
def test_data_quality_tiles_match_run_quality_check(client):
    tiles = ok(client.run(PM, "data_quality"))["result"]["tiles"]
    assert [t["number"] for t in tiles] == ["01", "02", "03", "04"]
    for t in tiles:
        ref = s.run_quality_check(t["number"])["result"]
        assert t["status"] == ref["overall_status"].split(":")[0] and t["row_count"] == ref["row_count"]
    assert [t["status"] for t in tiles] == ["FAIL", "FLAG", "FLAG", "WARN"]   # sql/README.md and mcp_server demo


@pytest.mark.parametrize("num", ["01", "02", "03", "04"])
def test_data_quality_drilldown_matches_run_quality_check(client, num):
    res = ok(client.drill(LEAD, "data_quality", {"check": num}, {"overlay": True}))["result"]
    ref = s.run_quality_check(num)["result"]
    for k in ("rule", "action", "method", "note", "description", "file"):
        assert res[k] == ref[k]
    flagged = [r for r in ref["rows"] if r.get("status") != "OK"] if "status" in ref["columns"] else ref["rows"]
    assert res["flagged_rows"] == flagged and res["columns"] == ref["columns"]
    assert res["row_count_total"] == ref["row_count"]
    if num == "04":
        assert res["action"] is None and res["action_note"] == "No action defined in the SQL file."
