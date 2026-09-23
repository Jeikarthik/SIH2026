"""Shared fixtures: every test runs against its own freshly built dataset.

The data paths in `cnas.config` are module constants read at call time, so a
test repoints them at a temporary directory and runs the real pipeline into
it. Nothing a test does can reach the working `data/` directory.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from cnas import config


def _point_at(d: pathlib.Path) -> None:
    config.DATA_DIR = d
    config.GRAPH_PATH = d / "graph.json"
    config.FINDINGS_PATH = d / "findings.json"
    config.DB_PATH = d / "cnas.sqlite"


# `cnas.api` initialises the database when it is imported, so the paths are
# moved off `data/` before that import, not only inside the fixture.
_point_at(pathlib.Path(tempfile.mkdtemp(prefix="cnas-test-")))

from fastapi.testclient import TestClient  # noqa: E402

import run_pipeline  # noqa: E402
from cnas import api  # noqa: E402


def rebuild() -> None:
    """Run the pipeline and drop anything the API had cached in memory."""
    assert run_pipeline.main() == 0, "pipeline self-checks failed"
    api._graph = None
    api._findings = []
    api._mtimes.clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "GRAPH_PATH", "FINDINGS_PATH", "DB_PATH"):
        monkeypatch.setattr(config, name, getattr(config, name))
    _point_at(tmp_path)
    rebuild()
    return TestClient(api.app)


def role(name: str) -> dict[str, str]:
    return {"X-CNAS-Role": name}


STD = role("standard_officer")
ELV = role("elevated_analyst")
RES = role("restricted_analyst")
