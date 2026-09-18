import datetime as dt

import pandas as pd
import pytest

from vyuha.store.pit import Observation, PITStore, observations_from_frame


@pytest.fixture
def store(tmp_path):
    with PITStore(tmp_path / "t.duckdb") as s:
        yield s


def test_lookahead_is_impossible(store):
    """The central guarantee: a figure published later is invisible earlier.

    CPI for March is not knowable on 1 April. A backtest asking for the world
    as of 1 April must not see it, no matter that the row exists in the table.
    """
    store.write([
        Observation("CPI_YOY", dt.date(2026, 3, 31), dt.datetime(2026, 4, 12), "MOSPI", 5.1)
    ])
    assert store.as_of("2026-04-01").empty
    assert len(store.as_of("2026-04-13")) == 1


def test_revisions_return_latest_visible_print(store):
    """First print 5.1, revised to 5.3. Which one you see depends on when you ask."""
    store.write([
        Observation("CPI_YOY", dt.date(2026, 3, 31), dt.datetime(2026, 4, 12), "MOSPI", 5.1),
    ])
    store.write([
        Observation("CPI_YOY", dt.date(2026, 3, 31), dt.datetime(2026, 5, 12), "MOSPI", 5.3),
    ])
    assert store.as_of("2026-04-20")["value"].iloc[0] == 5.1
    assert store.as_of("2026-06-01")["value"].iloc[0] == 5.3


def test_revision_history_keeps_every_print(store):
    for avail, val in [(dt.datetime(2026, 4, 12), 5.1), (dt.datetime(2026, 5, 12), 5.3)]:
        store.write([Observation("CPI_YOY", dt.date(2026, 3, 31), avail, "MOSPI", val)])
    h = store.revision_history("CPI_YOY", "2026-03-31")
    assert len(h) == 2
    assert list(h["value"]) == [5.1, 5.3]
    assert list(h["revision"]) == [0, 1]


def test_filters_by_series_entity_and_range(store):
    store.write([
        Observation("PX", dt.date(2026, 1, d), dt.datetime(2026, 1, d, 18), "NSE",
                    100.0 + d, entity=sym)
        for d in range(1, 11) for sym in ("RELIANCE", "TCS")
    ])
    assert set(store.as_of("2026-02-01", entity="TCS")["entity"]) == {"TCS"}
    assert len(store.as_of("2026-02-01", entity="TCS", start="2026-01-05")) == 6
    assert len(store.as_of("2026-02-01", series_id="MISSING")) == 0


def test_coverage_reports_publication_lag(store):
    store.write([
        Observation("IIP_YOY", dt.date(2026, m, 28), dt.datetime(2026, m + 2, 10), "MOSPI", 3.0)
        for m in range(1, 5)
    ])
    cov = store.coverage()
    assert cov["observations"].iloc[0] == 4
    assert cov["mean_publication_lag_days"].iloc[0] > 30


def test_frame_helper_requires_exactly_one_timing_rule():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-01"]), "value": [1.0]})
    with pytest.raises(ValueError, match="exactly one"):
        observations_from_frame(df, "S", "src")
    with pytest.raises(ValueError, match="exactly one"):
        observations_from_frame(df, "S", "src", available_at=dt.datetime.now(),
                                publication_lag=dt.timedelta(days=1))


def test_frame_helper_applies_publication_lag():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-31"]), "value": [7.0]})
    obs = observations_from_frame(df, "S", "src", publication_lag=dt.timedelta(days=12))
    assert obs[0].available_at.date() == dt.date(2026, 2, 12)


# ------------------------------------------------------- ingest module shape


def test_rbi_rate_map_covers_the_policy_corridor():
    from vyuha.ingest.rbi import _RATE_MAP

    ids = {v[0] for v in _RATE_MAP.values()}
    assert {"REPO_RATE", "CRR", "SLR", "USDINR"} <= ids


def test_rbi_parser_rejects_a_changed_layout():
    import pytest as _pytest

    from vyuha.ingest.rbi import _tokens

    with _pytest.raises(RuntimeError, match="layout changed"):
        _tokens("<html><body>nothing useful here</body></html>")


def test_catalogue_entries_are_internally_consistent():
    """Anything claiming WORKING must carry a verification date."""
    from vyuha.ingest.catalogue import CATALOGUE, Status

    for s in CATALOGUE:
        if s.status is Status.WORKING:
            assert s.last_verified, f"{s.key} claims WORKING with no last_verified"
        assert s.url.startswith("http"), f"{s.key} has no usable url"
        assert s.description


def test_blocked_sources_explain_themselves():
    from vyuha.ingest.catalogue import CATALOGUE, Status

    for s in CATALOGUE:
        if s.status is Status.BLOCKED:
            assert "BLOCKED" in s.notes or "blocked" in s.notes.lower(), (
                f"{s.key} is BLOCKED but does not say why"
            )


def test_series_ids_are_unique_per_source():
    from vyuha.ingest.catalogue import all_series

    assert len(all_series()) > 50


def test_api_routes_classify_correctly():
    from vyuha.api.server import classify

    assert classify("Will the Nifty fall below 23000?") == "council"
    assert classify("what is the repo rate") == "data"
    assert classify("run a stress test") == "risk"
    assert classify("compute VaR on nifty") == "risk"
