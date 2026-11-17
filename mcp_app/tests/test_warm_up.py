"""Background warm-up of the weekly business_health series: every market, never in the tests, and the API keeps
answering while it runs. The real get_kpis is replaced by fakes here, so these tests take well under a second."""
import threading
import time

from conftest import CM, PM
from app import views
from mcp_server import server as s


def test_create_app_does_not_start_the_warm_up(monkeypatch, client):
    called = []
    monkeypatch.setattr(views, "warm_cache", lambda *a, **k: called.append(1))
    assert client.run(PM, "conversion_lag").status_code == 200
    assert called == []
    assert not any(t.name == "warm-cache" for t in threading.enumerate())


def test_warm_up_covers_every_market_default_and_country_manager_first(monkeypatch):
    calls = []
    monkeypatch.setattr(views, "_kpis_cached", lambda m, a, b: calls.append((m, a, b)))
    views.warm_cache(pause_s=0)
    markets = list(dict.fromkeys(m for m, _, _ in calls))
    assert markets[:2] == ["all", "DE"]
    assert set(markets) == {"all", *s.MARKETS}
    assert len(calls) == len(markets) * len(s.WEEKS)
    assert all(a == b and a in s.WEEKS for _, a, b in calls)


def test_api_answers_while_warming_up(monkeypatch, client):
    started, release = threading.Event(), threading.Event()

    def slow_kpis(market, start, end):      # the first weekly call blocks until the requests below are done
        started.set()
        release.wait(30)
    monkeypatch.setattr(views, "_kpis_cached", slow_kpis)

    warm = threading.Thread(target=views.warm_cache, kwargs={"pause_s": 0}, daemon=True)
    warm.start()
    try:
        assert started.wait(10)
        t0 = time.perf_counter()
        assert client.run(PM, "conversion_lag").status_code == 200
        assert client.run(CM, "roas_lenses").status_code == 403
        assert client.get("/api/views?role=leadership").status_code == 200
        assert warm.is_alive()               # the warm-up was still running throughout
        assert time.perf_counter() - t0 < 10
    finally:
        release.set()
        warm.join(30)
    assert not warm.is_alive()
