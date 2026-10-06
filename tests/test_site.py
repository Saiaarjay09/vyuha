"""Tests for the static site build.

The static site exists because a server on a personal machine is unreachable
whenever that machine sleeps. GitHub Pages is free and always on but runs no
Python, so the build has to ship the data and the mathematics instead.

These tests guard the two things that would quietly break it: a payload too
large to be sensible to download, and a build that fails entirely because one
upstream feed is down.
"""

from __future__ import annotations

import json

import pytest

from vyuha.site import PAGE


def test_page_is_self_contained():
    """No build step and no framework: a browser and a human should both be
    able to read the thing that is showing them numbers."""
    assert "<!DOCTYPE html>" in PAGE
    assert "blockBootstrap" in PAGE, "the simulation must ship with the page"
    for forbidden in ("react", "vue.js", "angular", "jquery"):
        assert forbidden not in PAGE.lower()


def test_only_the_font_is_loaded_remotely():
    import re

    remote = re.findall(r'(?:src|href)="(https?://[^"]+)"', PAGE)
    for url in remote:
        assert "fonts.googleapis.com" in url or "fonts.gstatic.com" in url \
            or "github.com" in url, f"unexpected remote resource: {url}"


def test_client_side_simulation_uses_block_sampling():
    """Independent monthly sampling destroys volatility clustering and makes
    the distribution too narrow in the middle and too thin in the tails --
    flattering, and wrong in the direction that matters."""
    assert "block" in PAGE and "Math.ceil(nMonths/block)" in PAGE


def test_page_states_what_it_cannot_do():
    """The council needs a model at request time, which a static site cannot
    provide. Pretending otherwise would be the one unforgivable omission."""
    low = PAGE.lower()
    assert "cannot" in low
    assert "latest recorded" in low or "most recent recorded" in low


def test_honest_framing_survives_in_the_static_build():
    low = PAGE.lower()
    assert "not investment advice" in low or "not advice" in low
    assert "resample" in low or "resamples history" in low
    assert "nothing leaves your device" in low


def test_inflation_is_applied_not_ignored():
    assert "INFL" in PAGE
    assert "today's money" in PAGE


def test_goal_shows_both_confidence_levels():
    """Quoting only the median and calling it a plan is the failure this
    feature exists to correct."""
    assert "four-in-five" in PAGE
    assert "even chance" in PAGE


def test_unknown_holdings_are_flagged_client_side():
    assert "assumed" in PAGE
    assert "guessed" in PAGE


# ------------------------------------------------------------- the build


@pytest.fixture
def built(tmp_path, monkeypatch):
    import scripts.build_site as bs

    # Every collector is stubbed: the build must be testable without a network,
    # and its contract is "write valid JSON for each section", not "fetch".
    monkeypatch.setattr(bs, "collect_returns", lambda: {"assets": {}, "fixed": {}})
    monkeypatch.setattr(bs, "collect_market", lambda: {"series": []})
    monkeypatch.setattr(bs, "collect_council", lambda: {"runs": []})
    monkeypatch.setattr(bs, "collect_scoreboard", lambda: {"standing": {}})
    monkeypatch.setattr(bs, "collect_coverage", lambda: {"by_asset_class": {}})
    return bs.build(tmp_path / "site"), tmp_path / "site"


def test_build_emits_every_expected_file(built):
    manifest, out = built
    assert (out / "index.html").exists()
    assert (out / ".nojekyll").exists(), "Pages mangles files starting with _ without it"
    for name in ("returns", "market", "council", "scoreboard", "coverage"):
        p = out / "data" / f"{name}.json"
        assert p.exists()
        json.loads(p.read_text())


def test_one_dead_source_does_not_fail_the_whole_build(tmp_path, monkeypatch):
    """A feed being down must not take the calculators offline with it."""
    import scripts.build_site as bs

    def boom():
        raise RuntimeError("upstream is down")

    monkeypatch.setattr(bs, "collect_market", boom)
    monkeypatch.setattr(bs, "collect_returns", lambda: {"assets": {}, "fixed": {}})
    monkeypatch.setattr(bs, "collect_council", lambda: {"runs": []})
    monkeypatch.setattr(bs, "collect_scoreboard", lambda: {"standing": {}})
    monkeypatch.setattr(bs, "collect_coverage", lambda: {"by_asset_class": {}})

    out = tmp_path / "site"
    bs.build(out)
    assert (out / "index.html").exists()
    assert "error" in json.loads((out / "data" / "market.json").read_text())


def test_payload_stays_small_enough_to_be_reasonable(built):
    """This is downloaded by anyone opening the page, often on mobile data."""
    manifest, _ = built
    assert sum(manifest["files"].values()) < 400, "static payload is getting heavy"
