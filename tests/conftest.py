"""Test isolation.

Running the suite was writing council run logs into the REAL council_runs/
directory -- 11 of them in one pass, all from EchoProvider stubs answering
"Will X happen?" with a fixed 0.42.

That is not cosmetic. Those files are indistinguishable from genuine forecasts
to `resolve_due`, so they would be scored, folded into the track record, and
used to derive the pooling weights and bias corrections that govern every real
answer. A test run would quietly teach the council that a stub is a forecaster.

Every test therefore gets its own throwaway directories.
"""

from __future__ import annotations

import pytest

from vyuha.config import settings


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    """Point all writable paths at a per-test temporary directory."""
    for attr, name in (
        ("council_log_dir", "council_runs"),
        ("data_dir", "data"),
        ("cache_dir", "cache"),
    ):
        p = tmp_path / name
        p.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, attr, p)
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.duckdb")
    yield
