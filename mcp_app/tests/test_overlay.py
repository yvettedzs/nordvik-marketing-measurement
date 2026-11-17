"""Overlay: simulated-truth fields are absent from every response unless role = leadership and the toggle is on."""
import json

import pytest

from app.views import TRUTH_FIELDS
from conftest import CM, DRILLS, LEAD, PM
from mcp_server import server as s

ALLOWED = {
    CM: ["business_health", "conversion_lag"],
    PM: ["roas_lenses", "attribution_sensitivity", "conversion_lag", "data_quality"],
    LEAD: ["roas_lenses", "business_health", "attribution_sensitivity", "conversion_lag", "data_quality"],
}
TRUTH_NAMES_IN_TEXT = ("simulated_true_iroas", "journey_true_iroas")


def keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from keys(v)


def assert_no_truth(j):
    found = set(keys(j)) & TRUTH_FIELDS
    assert not found, found
    assert "overlay" not in j["result"]
    text = json.dumps(j)
    assert not any(n in text for n in TRUTH_NAMES_IN_TEXT)
    for row in j["result"].get("flagged_rows", []):            # check 01 drilldown
        assert "channel_roas" not in row and "claim_ratio" not in row


CASES = [(role, view) for role, views in ALLOWED.items() for view in views]


@pytest.mark.parametrize("role,view", CASES)
def test_no_truth_without_overlay(client, role, view):
    r = client.run(role, view)
    assert r.status_code == 200
    assert_no_truth(r.get_json())
    for seg, opts in DRILLS[view]:
        if role == CM and seg.get("market") not in (None, "DE"):
            continue
        r = client.drill(role, view, seg, opts)
        assert r.status_code == 200, r.get_json()
        assert_no_truth(r.get_json())


@pytest.mark.parametrize("view", ["roas_lenses", "data_quality"])
def test_leadership_with_toggle_off_has_no_truth(client, view):
    assert_no_truth(client.run(LEAD, view, {"overlay": False}).get_json())
    seg, opts = DRILLS[view][0]
    assert_no_truth(client.drill(LEAD, view, seg, {"overlay": False}).get_json())


def test_leadership_overlay_on_roas_lenses(client):
    j = client.run(LEAD, "roas_lenses", {"overlay": True}).get_json()
    ov = j["result"]["overlay"]
    assert ov["label"] == "validation only: not observable in real data"
    ref = {r["channel"]: r for r in s.compare_roas("all")["result"]["channels"]}
    for row in ov["channels"]:
        assert row["simulated_true_iroas"] == ref[row["channel"]]["simulated_true_iroas"]
        assert row["journey_true_iroas"] == ref[row["channel"]]["attributed_roas"]["journey_true_iroas"]
    assert j["caveats"] == s.compare_roas("all")["caveats"]   # tool caveats verbatim when the overlay is on
    # truth lives only inside the overlay block, never on the channel rows
    assert not set(keys(j["result"]["channels"])) & TRUTH_FIELDS


def test_overlay_on_data_quality_check_01(client):
    on = client.drill(LEAD, "data_quality", {"check": "01"}, {"overlay": True}).get_json()["result"]
    assert "channel_roas" in on["columns"] and "claim_ratio" in on["columns"]
    off = client.drill(LEAD, "data_quality", {"check": "01"}).get_json()["result"]
    assert "channel_roas" not in off["columns"] and "hidden_columns_note" in off
    pm = client.drill(PM, "data_quality", {"check": "01"}).get_json()["result"]
    assert pm["columns"] == off["columns"] and pm["flagged_rows"] == off["flagged_rows"]


def test_overlay_toggle_on_other_views_rejected(client):
    for view in ("business_health", "attribution_sensitivity", "conversion_lag"):
        r = client.run(LEAD, view, {"overlay": True})
        assert r.status_code == 400                             # no overlay exists for these views
