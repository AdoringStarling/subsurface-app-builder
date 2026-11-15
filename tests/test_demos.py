"""Smoke tests: each demo app runs headless without raising. Skipped when sample data is absent."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def run_app(rel: str) -> "AppTest":
    at = AppTest.from_file(str(ROOT / rel), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    return at


@pytest.mark.skipif(not (ROOT / "data/force2020/wells.parquet").exists(), reason="sample wells not downloaded")
def test_well_log_explorer():
    at = run_app("demos/01_well_log_explorer/app.py")
    assert len(at.tabs) == 5 and len(at.metric) >= 5
    at.selectbox[0].select_index(3).run()  # switch well
    assert not at.exception


@pytest.mark.skipif(not (ROOT / "data/volve/volve_sub3d.npy").exists(), reason="sample seismic not converted")
def test_seismic_viewer():
    at = run_app("demos/02_seismic_viewer/app.py")
    assert len(at.tabs) >= 3


@pytest.mark.skipif(not (ROOT / "data/factpages/field.csv").exists(), reason="factpages not downloaded")
def test_ncs_explorer():
    at = run_app("demos/03_ncs_explorer/app.py")
    assert len(at.tabs) >= 3
