"""The 4D and geosteering helpers must recover effects planted in synthetic data."""
import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "subsurface-app-builder" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import geosteering as gs  # noqa: E402
import make_synthetic as ms  # noqa: E402
import time_lapse as tl  # noqa: E402


def test_base_cube_is_unchanged_by_monitor_option():
    base, _, _ = ms.make_base_and_monitor(np.random.default_rng(3))
    assert np.array_equal(base, ms.make_cube(np.random.default_rng(3)))


def test_time_lapse_recovers_planted_effect():
    base, monitor, truth = ms.make_base_and_monitor(np.random.default_rng(42))
    hor, w = np.array(truth["horizon_sample"]), np.array(truth["footprint"])
    core, outside = w > 0.9, w == 0

    assert tl.nrms(base, base) == 0
    matched, rep = tl.match(base, monitor, 0, 60)
    assert rep["nrms_after"] < rep["nrms_before"]
    assert abs(rep["bulk_shift_samples"] * truth["dt_ms"] - truth["static_ms"]) < 0.3

    ts = tl.time_shift(base, matched)
    below = tl.value_along_horizon(ts, hor, 30) * truth["dt_ms"]
    assert abs(np.median(below[core]) - truth["slowdown_ms"]) < 0.7
    assert abs(np.median(below[outside])) < 0.4

    change = tl.rms_along_horizon(matched - base, hor, 4)
    assert change[core].mean() > 4 * change[outside].mean()

    # aligning removes the difference that exists below the reservoir only because events arrive later
    deep_raw = tl.rms_along_horizon(matched - base, hor, 4, offset=40)
    deep_aligned = tl.rms_along_horizon(tl.apply_shift(matched, ts) - base, hor, 4, offset=40)
    assert deep_aligned[core].mean() < 0.5 * deep_raw[core].mean()


def test_same_geometry_reports_mismatch():
    a = dict(ilines=[1, 2, 3], xlines=[1, 2], samples=[0, 4, 8])
    assert tl.same_geometry(a, a) == []
    assert tl.same_geometry(a, dict(a, samples=[0, 2, 4]))
    assert tl.same_geometry(a, dict(a, ilines=[1, 2]))


def test_minimum_curvature_simple_shapes():
    vertical = gs.minimum_curvature([0, 100, 200], [0, 0, 0], [0, 0, 0])
    assert np.allclose(vertical["tvd"], [0, 100, 200]) and np.allclose(vertical["north"], 0)
    horizontal = gs.minimum_curvature([0, 100], [90, 90], [90, 90])
    assert np.allclose(horizontal["tvd"], 0, atol=1e-9) and np.allclose(horizontal["east"], [0, 100])
    # quarter circle from vertical to horizontal over 100 m of hole: radius = 200 / pi
    arc = gs.minimum_curvature([0, 100], [0, 90], [0, 0])
    assert np.allclose([arc["tvd"].iloc[-1], arc["north"].iloc[-1]], 200 / np.pi, rtol=1e-6)


def test_geosteering_fit_recovers_structure():
    type_las, lateral_las, survey, truth = ms.make_geosteer(np.random.default_rng(43))
    path = gs.minimum_curvature([s["md"] for s in survey], [s["inc"] for s in survey], [s["azi"] for s in survey],
                                tvd0=truth["tvd_at_first_station"])
    md = np.asarray(lateral_las.index)
    keep = md <= path["md"].max()
    pts = gs.path_at(path, md[keep], truth["azimuth"])
    gr = np.asarray(lateral_las["GR"])[keep]
    fit = gs.fit_dips(pts["vs"], pts["tvd"], gr, type_las.index, type_las["GR"])

    true = gs.structure_shift(pts["vs"], truth["nodes_vs"], truth["dips_deg"])
    found = gs.structure_shift(pts["vs"], fit["nodes_vs"], fit["dips_deg"], fit["start_shift"])
    assert np.abs(true - found).mean() < 1.5            # metres, against a 12 m target
    assert fit["rms_misfit"] < 12                       # gAPI

    strat = pts["tvd"].to_numpy() - found
    lateral = pts["inc"].to_numpy() > 86
    status = gs.zone_status(strat[lateral], truth["zone_top"], truth["zone_base"])
    assert 0.3 < truth["in_zone_fraction"] < 0.9        # the case is only useful if the well leaves the zone
    assert abs(status["in_zone_fraction"] - truth["in_zone_fraction"]) < 0.15


def test_steering_advice_direction():
    # bit below the centre of the zone -> build angle; above -> drop
    low = gs.steering_advice(1.0, 1960, 1950, 1962)
    high = gs.steering_advice(1.0, 1951, 1950, 1962)
    assert low["hold_parallel_inc"] == 89.0
    assert low["to_centre_inc"] > 89.0 > high["to_centre_inc"]
