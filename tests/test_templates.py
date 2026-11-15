"""The app templates must run as shipped: copy them plus the helper modules to an empty folder, prepare
synthetic data with the skill's scripts, and run each headless."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "subsurface-app-builder"
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def run(script, *args):
    r = subprocess.run([sys.executable, str(SKILL / "scripts" / script), *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("project")
    for f in (SKILL / "assets" / "app_template").iterdir():
        shutil.copy(f, root)
    for mod in ("subsurface_utils.py", "subsurface_plots.py", "seismic_attributes.py"):
        shutil.copy(SKILL / "scripts" / mod, root)
    run("make_synthetic.py", root / "raw", "--wells", 2)
    run("las_to_parquet.py", root / "raw" / "wells", root / "data" / "wells.parquet")
    run("segy_to_npy.py", root / "raw" / "synthetic_cube.sgy", root / "data" / "survey")
    return root


def test_well_template_runs_and_reports_net_pay(project):
    assert (project / "data" / "wells.notes.json").exists()
    at = AppTest.from_file(str(project / "app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [m.label for m in at.metric]
    assert "Net pay, m" in labels
    assert float(at.metric[labels.index("Net pay, m")].value) > 0
    at.selectbox[0].select_index(1).run()
    assert not at.exception


def test_seismic_template_runs_in_every_display(project):
    at = AppTest.from_file(str(project / "seismic_app.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]
    for choice in ("Discontinuity", "Envelope"):
        at.radio[0].set_value(choice).run()
        assert not at.exception, (choice, [e.value for e in at.exception])
