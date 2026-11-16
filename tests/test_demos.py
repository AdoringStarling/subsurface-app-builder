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


@pytest.fixture(scope="module")
def synthetic():
    """Demos 04 and 05 run on generated data, so create it when missing (a few seconds, no network)."""
    if not (ROOT / "data/synthetic/monitor.npy").exists() or not (ROOT / "data/synthetic/geosteer/lateral.las").exists():
        import subprocess
        import sys
        subprocess.run([sys.executable, str(ROOT / "scripts/prepare_synthetic.py")], check=True)


def test_time_lapse(synthetic):
    at = run_app("demos/04_time_lapse/app.py")
    assert len(at.tabs) == 4 and len(at.metric) == 4
    at.checkbox[1].check().run()            # align monitor to base
    assert not at.exception, [e.value for e in at.exception]
    at.checkbox[0].uncheck().run()          # no matching
    assert not at.exception, [e.value for e in at.exception]


def test_geosteering(synthetic):
    at = run_app("demos/05_geosteering/app.py")
    assert len(at.tabs) == 3 and len(at.metric) == 5
    options = at.select_slider[0].options
    for md in (options[0], options[-1]):    # just landed, and total depth
        at.select_slider[0].set_value(md).run()
        assert not at.exception, (md, [e.value for e in at.exception])


@pytest.mark.skipif(not (ROOT / "data/factpages/field.csv").exists(), reason="factpages not downloaded")
def test_ncs_explorer():
    at = run_app("demos/03_ncs_explorer/app.py")
    assert len(at.tabs) >= 3
