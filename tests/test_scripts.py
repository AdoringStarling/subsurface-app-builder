"""End-to-end tests of the skill's helper scripts on synthetic data."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "subsurface-app-builder" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import subsurface_utils as su  # noqa: E402


def run(script, *args):
    r = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture(scope="session")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synth")
    run("make_synthetic.py", out, "--wells", 4)
    return out


def test_inspect_las_single(synth):
    info = json.loads(run("inspect_las.py", synth / "wells" / "SYN-1.las"))
    assert info["well"] == "SYN-1"
    assert {"GR", "RHOB", "NPHI", "RDEP", "DTC", "CALI", "BS"} <= set(info["families_present"])
    nphi = next(c for c in info["curves"] if c["family"] == "NPHI")
    assert nphi["valid_pct"] < 100  # the generator inserts a null gap


def test_inspect_las_folder(synth):
    info = json.loads(run("inspect_las.py", synth / "wells", "--brief"))
    assert info["files"] == 4 and not info["errors"]
    assert info["family_coverage_wells"]["GR"] == 4


def test_las_to_parquet_harmonises_names(synth, tmp_path):
    import pandas as pd

    dst = tmp_path / "wells.parquet"
    run("las_to_parquet.py", synth / "wells", dst)
    df = pd.read_parquet(dst)
    assert df["WELL"].nunique() == 4
    assert {"GR", "RHOB", "NPHI", "RDEP", "DTC"} <= set(df.columns)  # vendor names mapped
    assert not {"SGR", "RHOZ", "TNPH", "AT90", "DTCO"} & set(df.columns)


def test_inspect_segy_finds_geometry(synth):
    info = json.loads(run("inspect_segy.py", synth / "synthetic_cube.sgy"))
    g = info["geometry"]
    assert (g["n_ilines"], g["n_xlines"]) == (60, 80)
    assert info["samples_per_trace"] == 251 and info["sample_interval"] == 4.0


def test_segy_to_npy_full_and_crop(synth, tmp_path):
    run("segy_to_npy.py", synth / "synthetic_cube.sgy", tmp_path / "cube")
    cube = np.load(tmp_path / "cube.npy", mmap_mode="r")
    meta = json.loads((tmp_path / "cube.json").read_text())
    assert cube.shape == (60, 80, 251) == tuple(meta["shape"])
    run("segy_to_npy.py", synth / "synthetic_cube.sgy", tmp_path / "crop",
        "--ilines", 10, 19, "--xlines", 5, 24, "--samples", 50, 150)
    crop = np.load(tmp_path / "crop.npy")
    assert crop.shape == (10, 20, 100)
    np.testing.assert_allclose(crop, cube[9:19, 4:24, 50:150])


def test_canonical_name():
    assert su.canonical_name("RHOZ") == "RHOB"
    assert su.canonical_name("gr") == "GR"
    assert su.canonical_name("GR:1") == "GR"
    assert su.canonical_name("DT_EDIT") == "DTC"
    assert su.canonical_name("FORCE_2020_LITHOFACIES_LITHOLOGY") is None


def test_petrophysics_values():
    assert su.vshale_gr([20, 70, 120], 20, 120).tolist() == [0.0, 0.5, 1.0]
    assert su.vshale_gr([70], 20, 120, "larionov_old")[0] == pytest.approx(0.33, abs=1e-6)
    assert su.porosity_density([2.65, 2.32])[1] == pytest.approx(0.2)
    # Archie: phi 0.2, Rw 0.05, Rt 1.25 -> Sw 1.0 ; Rt 5 -> Sw 0.5
    assert su.sw_archie([1.25, 5.0], [0.2, 0.2], rw=0.05).tolist() == pytest.approx([1.0, 0.5])


def test_net_pay_on_synthetic(synth):
    df = su.las_to_frame(synth / "wells" / "SYN-1.las")
    df["VSH"] = su.vshale_gr(df["GR"])
    df["PHIE"] = su.porosity_effective(su.porosity_density(df["RHOB"]), df["VSH"])
    df["SW"] = su.sw_archie(df["RDEP"], df["PHIE"], rw=0.06)
    s = su.net_pay_summary(df)
    assert 0 < s["net_pay_m"] < s["net_reservoir_m"] < s["gross_m"] <= 601
    assert su.flag_bad_hole(df).sum() >= 50  # the inserted washout


def test_fetch_factpages_lists_tables():
    out = run("fetch_factpages.py", "--list")
    assert "wellbore_exploration_all" in out and "field_production_monthly" in out


def test_fix_units_converts_percent_and_kgm3():
    import pandas as pd

    df = pd.DataFrame({"NPHI": [20.0, 25.0, 30.0], "RHOB": [2300.0, 2400.0, 2500.0], "GR": [50.0, 60.0, 70.0]})
    done = su.fix_units(df)
    assert df["NPHI"].tolist() == pytest.approx([0.20, 0.25, 0.30]) and df["RHOB"].tolist() == pytest.approx([2.3, 2.4, 2.5])
    assert len(done) == 2 and df["GR"].tolist() == [50.0, 60.0, 70.0]
    assert su.fix_units(df) == []  # already correct: nothing changes
