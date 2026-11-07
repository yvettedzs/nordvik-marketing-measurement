"""
Tests for mcp_server/server.py. Run from the repository root:  python -m pytest tests -v

Four layers:
  A. independent recalculation in pandas (catches DuckDB / SQL mistakes in the server)
  B. published numbers in the existing outputs (results txt, SQL checks, README, memo, answer-key calibration)
  C. contract: envelope, validation errors, wording, read-only, MCP protocol
  D. slow: re-run the analysis scripts in a temp folder and check the committed results txt are current
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys

import anyio
import duckdb
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server import server as s

YEARS = 104 / 52
EUR_TOL = 0.011          # server rounds EUR to cents
RATIO_TOL = 5e-5         # server rounds ratios to 4 dp
PAID = ["Google", "Meta", "Affiliates", "TikTok", "SEO", "Email"]


def _pandas_kpis(df, market="all", channel="all", start=None, end=None):
    d = df
    if market != "all":
        d = d[d.market == market]
    if channel != "all":
        d = d[d.channel == channel]
    if start:
        d = d[d.week_start >= start]
    if end:
        d = d[d.week_start <= end]
    return d.spend_eur.sum(), int(d.orders.sum()), d.net_revenue_eur.sum(), d.week_start.nunique()


# ============================================================ A. independent recalculation (pandas)
CASES = ([("all", "all", None, None)]
         + [(m, "all", None, None) for m in ["DE", "AT", "FR", "NL", "UK", "SE"]]
         + [("all", c, None, None) for c in PAID + ["Direct_Other"]]
         + [("all", "all", "2026-03-02", "2026-04-20"), ("DE", "Meta", "2026-05-11", "2026-10-19")])


@pytest.mark.parametrize("market,channel,start,end", CASES)
def test_get_kpis_matches_pandas(df, market, channel, start, end):
    spend, orders, rev, weeks = _pandas_kpis(df, market, channel, start, end)
    r = s.get_kpis(market, channel, start, end)["result"]
    assert r["weeks"] == weeks
    assert r["orders"] == orders
    assert abs(r["spend_eur"] - spend) < EUR_TOL
    assert abs(r["net_revenue_eur"] - rev) < EUR_TOL
    assert abs(r["cm_before_marketing_eur"] - 0.55 * rev) < EUR_TOL
    assert abs(r["cm_after_marketing_eur"] - (0.55 * rev - spend)) < EUR_TOL
    ratio = rev / spend if spend > 0 else None
    cac = spend / orders if spend > 0 else None
    if channel == "all":
        assert abs(r["mer"] - ratio) < RATIO_TOL
        assert r["cac_label"].startswith("blended CAC")
    else:
        assert r["mer"] is None
        assert r["cac_label"].startswith("simulated incremental CAC")
        if ratio is None:
            assert r["simulated_incremental_roas"] is None
        else:
            assert abs(r["simulated_incremental_roas"] - ratio) < RATIO_TOL
    if cac is None:
        assert r["cac_eur"] is None
    else:
        assert abs(r["cac_eur"] - cac) < EUR_TOL


def test_compare_roas_matches_pandas(df):
    g = df[df.channel != "Direct_Other"].groupby("channel").agg(
        spend=("spend_eur", "sum"), plat=("platform_reported_revenue_eur", "sum"), rev=("net_revenue_eur", "sum"))
    rows = {r["channel"]: r for r in s.compare_roas()["result"]["channels"]}
    assert set(rows) == set(PAID)
    for ch, x in g.iterrows():
        assert abs(rows[ch]["simulated_true_iroas"] - x.rev / x.spend) < RATIO_TOL
        if ch == "SEO":
            assert rows[ch]["platform_roas"] is None            # not 0, which a naive SUM would give
        else:
            assert abs(rows[ch]["platform_roas"] - x.plat / x.spend) < RATIO_TOL


# ============================================================ B. published numbers in existing outputs
def test_get_kpis_full_period_matches_answer_key_calibration():
    # docs/answer_key.md section 5 (only the numbers are hard-coded here; the server never reads that file)
    r = s.get_kpis()["result"]
    assert round(r["mer"], 2) == 5.09
    assert round(r["net_revenue_eur"] / YEARS / 1e6, 1) == 114.3
    assert round(r["spend_eur"] / YEARS / 1e6, 2) == 22.47
    assert round(r["orders"] / YEARS) == 31904


def _memo_table(repo_root):
    text = (repo_root / "docs" / "budget_memo.md").read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\| (\w+) \| €([\d.]+)M \(\d+%\) \| ([\d.]+|n/a) \| ([\d.]+) \|", line)
        if m:
            rows[m[1]] = dict(spend_m=float(m[2]), platform=None if m[3] == "n/a" else float(m[3]), true=float(m[4]))
    return rows


def test_memo_table_matches_tools(repo_root):
    memo = _memo_table(repo_root)
    assert set(memo) == set(PAID)
    rows = {r["channel"]: r for r in s.compare_roas()["result"]["channels"]}
    for ch, m in memo.items():
        spend_yr = s.get_kpis(channel=ch)["result"]["spend_eur"] / YEARS / 1e6
        assert round(spend_yr, 1) == m["spend_m"], ch
        assert round(rows[ch]["simulated_true_iroas"], 1) == m["true"], ch
        if m["platform"] is None:
            assert rows[ch]["platform_roas"] is None
        else:
            assert round(rows[ch]["platform_roas"], 1) == m["platform"], ch


def test_compare_roas_matches_sql_check_01_and_break_even():
    sql_rows = {r["channel"]: r for r in s.run_quality_check("01")["result"]["rows"]}
    res = s.compare_roas()["result"]
    for r in res["channels"]:
        if r["channel"] == "SEO":
            continue
        assert round(r["platform_roas"], 2) == sql_rows[r["channel"]]["platform_roas"]
        assert round(r["simulated_true_iroas"], 2) == sql_rows[r["channel"]]["channel_roas"]
        assert round(r["overstatement_ratio"], 2) == sql_rows[r["channel"]]["claim_ratio"]
    assert round(res["break_even_roas"], 2) == 1.82            # meta_holdout_results.txt "Break-even ROAS: 1.82"
    meta = next(r for r in res["channels"] if r["channel"] == "Meta")
    assert meta["holdout"]["iroas"] == 2.45 and meta["holdout"]["ci_95"] == [1.01, 3.89]
    assert meta["platform_above_break_even"] is True and meta["true_above_break_even"] is False
    tiktok = next(r for r in res["channels"] if r["channel"] == "TikTok")
    assert tiktok["true_above_break_even"] is False


def test_meta_holdout_result():
    r = s.get_test_result("meta_holdout")["result"]
    assert r["iroas"] == 2.45
    assert r["iroas_ci_95"] == [1.01, 3.89]
    assert r["platform_roas_de_pre_test"] == 2.42
    assert r["break_even_roas"] == 1.82
    assert (r["orders_actual"], r["orders_counterfactual"], r["orders_lost"]) == (6655, 7152, 497)
    assert r["pct_change"] == -0.069 and r["pct_ci_95"] == [-0.11, -0.029]
    assert r["naive_prepost"] == 0.175
    assert r["spend_saved_eur"] == 738617 and r["incremental_revenue_lost_eur"] == 1811088
    assert (r["weeks"], r["paused_weeks"]) == (24, 12)
    assert r["control_weights"] == {"AT": 0.664, "FR": 0.941, "NL": 0.526, "UK": 0.44, "SE": 0.649}
    assert "not proven profitable" in r["verdict"]
    # README headline: "about 7% (95% interval 3% to 11%)", "iROAS 2.45 (range 1.0 to 3.9)"
    assert round(-r["pct_change"], 2) == 0.07 and [round(-x, 2) for x in r["pct_ci_95"]] == [0.11, 0.03]
    assert [round(x, 1) for x in r["iroas_ci_95"]] == [1.0, 3.9]


def test_discount_result():
    r = s.get_test_result("discount")["result"]
    assert r["naive_prepost"] == 0.491
    assert r["lift"] == 0.243 and r["lift_ci_95"] == [0.127, 0.358]
    assert r["pull_forward_dip"] == -0.10 and r["dip_ci_95"] == [-0.216, 0.016]
    assert r["net_orders_8w"] == 249 and r["net_pct_8w"] == 0.063
    assert r["realised_discount"] == 0.24 and r["headline_discount"] == 0.40
    assert r["cm_per_order_regular"] == 0.55 and r["cm_per_order_discounted"] == 0.31
    assert r["break_even_lift"] == 0.77
    assert r["net_revenue_effect_8w_eur"] == -908511
    assert r["cm_effect_8w_eur"] == -1236710
    assert r["cm_effect_range_eur"] == [-1824659, -648760]
    # README headline: +24% lift, +49% naive, -10% dip, +77% to break even, ~EUR 1.2M margin cost
    assert round(r["lift"], 2) == 0.24 and round(r["naive_prepost"], 2) == 0.49
    assert round(-r["cm_effect_8w_eur"] / 1e6, 1) == 1.2


@pytest.mark.parametrize("num", ["01", "02", "03", "04"])
def test_quality_check_rows_equal_direct_duckdb_run(repo_root, num, monkeypatch):
    """Same path as sql/run_checks.py: run the .sql file from the repo root and compare row by row."""
    stem = s.QUALITY_CHECKS[num]
    monkeypatch.chdir(repo_root)
    direct = duckdb.sql((repo_root / "sql" / f"{stem}.sql").read_text(encoding="utf-8")).df()
    r = s.run_quality_check(num)["result"]
    assert r["columns"] == list(direct.columns)
    assert r["row_count"] == len(direct)
    expected = [{k: s._jsonable(v) for k, v in rec.items()} for rec in direct.to_dict("records")]
    assert r["rows"] == expected


def test_quality_check_published_findings():
    # sql/README.md "What it returns on this dataset"
    c1 = s.run_quality_check("platform_vs_analytics_gap")["result"]
    st = {r["channel"]: (r["status"], r["claim_ratio"]) for r in c1["rows"]}
    assert st["TikTok"] == ("FAIL", 2.77) and st["Meta"] == ("FAIL", 1.63)
    assert {st[c][0] for c in ["Google", "Affiliates", "Email"]} == {"WARN"}
    assert c1["overall_status"] == "FAIL"

    c2 = s.run_quality_check("02")["result"]
    assert {(r["week_start"], r["market"]) for r in c2["rows"]} == {
        ("2025-11-03", "FR"), ("2025-10-20", "UK"), ("2025-10-20", "FR")}
    assert c2["overall_status"] == "FLAG"

    c3 = s.run_quality_check("03")["result"]
    assert [(r["week_start"], r["market"], r["channel"], r["problem"]) for r in c3["rows"]] == [
        ("2024-12-16", "AT", "Google", "C: cost per session outlier")]

    assert c3["rule"].startswith("FLAG a row if A) spend > 0 and sessions = 0")
    assert c3["rule"].endswith("market x channel's mean over the full period.")
    assert c3["action"].startswith("for A and B, check tags, landing pages and UTMs")
    assert c3["action"].endswith("before using that week's cost figures.")

    c4 = s.run_quality_check("04")["result"]
    assert all(r["check_name"] == "revenue per order vs expected" and r["status"] == "WARN" for r in c4["rows"])
    assert {(r["period"], r["market"]) for r in c4["rows"]} == {("2026-03-01", m) for m in ["DE", "AT", "FR", "NL"]}
    assert c4["overall_status"] == "WARN"


def test_metric_dictionary_tools():
    lm = s.list_metrics()["result"]
    assert [m["key"] for m in lm["metrics"]] == ["cac", "roas", "mer", "contribution_margin", "payback", "iroas"]
    assert all(m["one_line"] for m in lm["metrics"])
    assert s.define_metric("ROAS")["result"]["key"] == "roas"
    assert any("1.8" in n for n in s.define_metric("roas")["result"]["notes"])        # break-even bullet
    cac = s.define_metric("customer acquisition cost")["result"]
    assert "~€720" in cac["example"]
    assert cac["excludes"].startswith("sales staff salaries")
    assert s.define_metric("iROAS")["result"]["key"] == "iroas"
    assert s.define_metric("Contribution_Margin")["result"]["excludes"].startswith("fixed costs")
    assert s.define_metric("payback")["result"]["formula"].startswith("contribution margin on the first order / CAC")


# ============================================================ C. contract
ALL_CALLS = [
    lambda: s.list_metrics(), lambda: s.define_metric("mer"), lambda: s.get_kpis(),
    lambda: s.get_kpis("DE", "Meta", "2026-05-11", "2026-07-27"), lambda: s.compare_roas(),
    lambda: s.compare_roas("TikTok"), *[(lambda n=n: s.run_quality_check(n)) for n in ["01", "02", "03", "04"]],
    lambda: s.get_test_result("meta_holdout"), lambda: s.get_test_result("discount"),
]


@pytest.mark.parametrize("call", ALL_CALLS)
def test_envelope(repo_root, call):
    r = call()
    assert r["data_origin"] == "simulated"
    assert "Simulated data" in r["notice"]
    assert r["definitions_used"] and all(isinstance(v, str) and v for v in r["definitions_used"].values())
    assert "net of VAT" in r["conventions"] and "excluding VAT" in r["conventions"]
    assert r["sources"] and all((repo_root / p).exists() for p in r["sources"])
    json.dumps(r)                                                         # JSON-serialisable


@pytest.mark.parametrize("call,expected", [
    (lambda: s.get_kpis(market="ES"), "Valid values: all, DE, AT, FR, NL, UK, SE"),
    (lambda: s.get_kpis(channel="Bing"), "Valid values: all, Google, Meta, Affiliates, TikTok, SEO, Email, Direct_Other"),
    (lambda: s.get_kpis(start="03/02/2026"), "YYYY-MM-DD"),
    (lambda: s.get_kpis(start="2023-01-02"), "outside the data range"),
    (lambda: s.get_kpis(start="2026-05-01", end="2026-04-01"), "after end date"),
    (lambda: s.get_kpis(start="2026-03-03", end="2026-03-04"), "No weeks"),
    (lambda: s.compare_roas("Direct_Other"), "Valid values: all, Google, Meta"),
    (lambda: s.define_metric("LTV"), "Valid values: cac, roas, mer, contribution_margin, payback, iroas"),
    (lambda: s.run_quality_check("05"), "platform_vs_analytics_gap"),
    (lambda: s.get_test_result("tiktok_geo"), "Valid values: meta_holdout, discount"),
])
def test_validation_errors(call, expected):
    with pytest.raises(ToolError, match=re.escape(expected)):
        call()


def test_inputs_are_case_insensitive():
    assert s.get_kpis("de", "meta")["result"]["filters"] == {
        "market": "DE", "channel": "Meta", "start": "2024-10-28", "end": "2026-10-19"}


def test_channel_revenue_called_incremental_never_attributed():
    for r in [s.get_kpis(channel="Meta"), s.compare_roas(), s.run_quality_check("01")]:
        body = json.dumps({"result": r["result"], "caveats": r["caveats"]})
        # negated uses ("not analytics-attributed revenue", from the SQL header) are allowed
        assert not re.search(r"(?<!not )(?<!not analytics-)attributed (net )?revenue", body, re.I), body
    assert "incremental revenue" in s.get_kpis(channel="Google")["result"]["net_revenue_label"]
    for row in s.compare_roas()["result"]["channels"]:
        assert row["simulated_true_iroas_label"] == "validation only: not observable in real data"


def test_caveats():
    promo_caveat = ("Includes promo weeks (March 2026): CM is overstated for those weeks, because discounted "
                    "outdoor-furniture orders earn about 31% CM instead of 55%.")
    assert promo_caveat in s.get_kpis(start="2026-03-02", end="2026-03-30")["caveats"]
    assert promo_caveat in s.get_kpis()["caveats"]                     # full period includes March 2026
    assert not any("out of date" in c for t in ["meta_holdout", "discount"] for c in s.get_test_result(t)["caveats"])
    assert not any("promo" in c for c in s.get_kpis(market="UK", start="2026-03-02", end="2026-03-30")["caveats"])
    assert any("buying window" in c for c in s.get_kpis(start="2026-06-01", end="2026-06-29")["caveats"])
    assert not any("buying window" in c for c in s.get_kpis()["caveats"])


def test_get_kpis_cac_definition_states_orders_assumption(repo_root):
    note = "Orders = new customers (assumption: no repeat purchases, see docs/assumptions.md)."
    for r in [s.get_kpis(), s.get_kpis("DE", "Meta", "2026-03-02", "2026-04-26")]:
        cac_def = r["definitions_used"]["CAC"]
        assert cac_def.startswith(s._definition("cac"))   # dictionary text kept
        assert cac_def.endswith(note)
    assert "each order is a new customer" in (repo_root / "docs/assumptions.md").read_text(encoding="utf-8")


def test_server_does_not_read_answer_key():
    src = (s.REPO_ROOT / "mcp_server" / "server.py").read_text(encoding="utf-8")
    assert "answer_key" not in src


def _snapshot(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not {"__pycache__", ".pytest_cache", ".venv", "venv", ".git"} & set(p.relative_to(root).parts):
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_tools_are_read_only(repo_root):
    before = _snapshot(repo_root)
    for call in ALL_CALLS:
        call()
    assert _snapshot(repo_root) == before


def test_mcp_protocol():
    async def main():
        async with create_connected_server_and_client_session(s.mcp._mcp_server) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert set(tools) == {"list_metrics", "define_metric", "get_kpis", "compare_roas",
                                  "run_quality_check", "get_test_result"}
            assert list(tools["get_kpis"].inputSchema["properties"]) == ["market", "channel", "start", "end"]
            assert all(t.annotations.readOnlyHint for t in tools.values())
            ok = await client.call_tool("get_test_result", {"test": "meta_holdout"})
            assert not ok.isError
            assert ok.structuredContent["result"]["iroas"] == 2.45
            bad = await client.call_tool("get_kpis", {"market": "ES"})
            assert bad.isError and "DE, AT, FR, NL, UK, SE" in bad.content[0].text
    anyio.run(main)


# ============================================================ D. slow: are the committed results current?
@pytest.mark.slow
@pytest.mark.parametrize("script,txt", [("01_meta_holdout.py", "meta_holdout_results.txt"),
                                        ("02_discount_prepost.py", "discount_results.txt")])
def test_results_txt_reproduce_from_current_data(repo_root, tmp_path, script, txt):
    shutil.copytree(repo_root / "data", tmp_path / "data")
    (tmp_path / "analysis").mkdir()
    shutil.copy(repo_root / "analysis" / script, tmp_path / "analysis" / script)
    subprocess.run([sys.executable, f"analysis/{script}"], cwd=tmp_path, check=True, capture_output=True)
    regenerated = (tmp_path / "analysis" / txt).read_text(encoding="utf-8")
    assert regenerated == (repo_root / "analysis" / txt).read_text(encoding="utf-8")
