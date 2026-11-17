"""Access: roles see only their views; the country manager is locked to DE; refusals are 403 with the agreed body."""
import pytest

from conftest import CM, DRILLS, LEAD, PM

ALL = ["roas_lenses", "business_health", "attribution_sensitivity", "conversion_lag", "data_quality"]
ALLOWED = {
    CM: ["business_health", "conversion_lag"],
    PM: ["roas_lenses", "attribution_sensitivity", "conversion_lag", "data_quality"],
    LEAD: ALL,
}


def refused(resp):
    assert resp.status_code == 403, resp.get_json()
    j = resp.get_json()
    assert set(j) == {"error", "access_denied"} and j["access_denied"] is True and j["error"]
    return j


def test_roles_route(client):
    j = client.get("/api/roles").get_json()
    assert j["data_origin"] == "simulated"
    roles = {r["id"]: r for r in j["result"]["roles"]}
    assert {k: v["views"] for k, v in roles.items()} == ALLOWED
    assert roles[CM]["market_lock"] == "DE" and roles[LEAD]["overlay_allowed"] is True
    assert roles[PM]["overlay_allowed"] is False


@pytest.mark.parametrize("role", list(ALLOWED))
def test_views_route_lists_only_allowed_views(client, role):
    r = client.get(f"/api/views?role={role}")
    assert r.status_code == 200
    views = r.get_json()["result"]["views"]
    assert [v["id"] for v in views] == ALLOWED[role]
    for v in views:
        assert ("overlay" in v["options"]) == (role == LEAD and v["id"] in ("roas_lenses", "data_quality"))
    if role == CM:
        bh = next(v for v in views if v["id"] == "business_health")
        assert bh["options"]["market"]["values"] == ["DE"]


@pytest.mark.parametrize("role", [None, "", "admin"])
def test_unknown_role_refused(client, role):
    refused(client.get(f"/api/views?role={role or ''}"))
    refused(client.run(role, "conversion_lag"))
    refused(client.drill(role, "conversion_lag", {"path": "all", "day": 30}))


@pytest.mark.parametrize("role,view", [(r, v) for r in ALLOWED for v in ALL if v not in ALLOWED[r]])
def test_view_not_allowed_refused(client, role, view):
    refused(client.run(role, view))
    seg, opts = DRILLS[view][0]
    refused(client.drill(role, view, seg, opts))


def test_country_manager_roas_lenses_403(client):
    j = refused(client.run(CM, "roas_lenses"))
    assert "roas_lenses" in j["error"]


@pytest.mark.parametrize("market", ["FR", "fr", "all", "UK"])
def test_country_manager_other_market_403(client, market):
    refused(client.run(CM, "business_health", {"market": market}))
    refused(client.drill(CM, "business_health", {"week": "2026-03-02"}, {"market": market}))


def test_country_manager_drilldown_other_market_403(client):
    refused(client.drill(CM, "business_health", {"market": "FR"}))


def test_country_manager_locked_to_de(client):
    for opts in ({}, {"market": "DE"}, {"market": "de"}):
        j = client.run(CM, "business_health", opts).get_json()
        assert j["options"]["market"] == "DE"
        assert [p["segment"] for p in j["result"]["points"]] == ["DE"]
    j = client.drill(CM, "business_health", {"market": "DE"}).get_json()
    assert j["result"]["market"] == "DE"
    j = client.drill(CM, "business_health", {"week": "2026-03-02"}).get_json()
    assert j["result"]["market"] == "DE"


@pytest.mark.parametrize("view", ALL)
def test_leadership_gets_200_for_all_five(client, view):
    assert client.run(LEAD, view).status_code == 200
    for seg, opts in DRILLS[view]:
        assert client.drill(LEAD, view, seg, opts).status_code == 200


@pytest.mark.parametrize("role,view", [(PM, "roas_lenses"), (PM, "data_quality")])
def test_overlay_refused_for_non_leadership(client, role, view):
    refused(client.run(role, view, {"overlay": True}))


@pytest.mark.parametrize("role,view,options,segment", [
    (LEAD, "nope", {}, None),
    (LEAD, "business_health", {"metric": "roas"}, None),
    (LEAD, "business_health", {"group_by": "channel"}, None),
    (LEAD, "business_health", {"market": "XX"}, None),
    (LEAD, "business_health", {"colour": "red"}, None),
    (LEAD, "attribution_sensitivity", {"channel": "Direct_Other"}, None),
    (LEAD, "attribution_sensitivity", {"channel": "all"}, None),
    (LEAD, "roas_lenses", {"overlay": "yes"}, None),
    (LEAD, "conversion_lag", {}, {"path": "all", "day": 45}),
    (LEAD, "conversion_lag", {}, {"path": "quote", "day": 30}),
    (LEAD, "data_quality", {}, {"check": "09"}),
    (LEAD, "business_health", {}, {"market": "DE", "week": "2026-03-02"}),
    (LEAD, "business_health", {}, {"week": "2026-03-03"}),
    (LEAD, "roas_lenses", {}, {"channel": "Radio"}),
    (LEAD, "attribution_sensitivity", {"channel": "Meta"}, {"model": "markov"}),
])
def test_invalid_inputs_400(client, role, view, options, segment):
    r = client.run(role, view, options) if segment is None else client.drill(role, view, segment, options)
    assert r.status_code == 400, r.get_json()
    j = r.get_json()
    assert j["access_denied"] is False and j["error"]


def test_non_json_body_400(client):
    r = client.c.post("/api/run", data="not json", content_type="text/plain")
    assert r.status_code == 400 and r.get_json()["access_denied"] is False
