"""4D (time-lapse) seismic on numpy cubes: repeatability, matching, time shifts, difference.

Both cubes must share geometry (same inlines, crosslines and samples); the sample axis is last.
Time shifts are in samples: multiply by the sample interval for milliseconds. Positive = the
monitor event arrives later than in the base (slow-down, e.g. pressure drop or gas coming out).

Import in an app, or get a QC summary of two cubes made by segy_to_npy.py:
    python time_lapse.py data/base data/monitor [--quiet-window 20 80]
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter, uniform_filter1d


def same_geometry(meta_base: dict, meta_monitor: dict) -> list[str]:
    """Problems that make sample-by-sample comparison invalid. Empty list = comparable."""
    out = []
    for key in ("ilines", "xlines", "samples"):
        a, b = np.asarray(meta_base[key]), np.asarray(meta_monitor[key])
        if a.shape != b.shape:
            out.append(f"{key}: {len(a)} in base, {len(b)} in monitor")
        elif not np.allclose(a, b):
            out.append(f"{key}: same count but different values ({a[0]}..{a[-1]} vs {b[0]}..{b[-1]})")
    return out


def _rms(x: np.ndarray, axis=None) -> np.ndarray:
    return np.sqrt(np.mean(np.square(x, dtype=np.float64), axis=axis))


def nrms(base: np.ndarray, monitor: np.ndarray, window: int | None = None) -> np.ndarray | float:
    """Normalised RMS difference in percent: 200 * rms(m - b) / (rms(m) + rms(b)).

    0 = identical, about 141 = unrelated noise, 200 = opposite polarity. Good marine 4D is roughly
    10-30 % outside the reservoir. window=None gives one number; an integer gives a volume
    computed in a sliding window of that many samples.
    """
    b, m = np.asarray(base, dtype=np.float32), np.asarray(monitor, dtype=np.float32)
    if window is None:
        return float(200 * _rms(m - b) / (_rms(m) + _rms(b) + 1e-12))
    f = lambda x: np.sqrt(uniform_filter1d(x * x, size=window, axis=-1))
    return (200 * f(m - b) / (f(m) + f(b) + 1e-12)).astype(np.float32)


def nrms_map(base: np.ndarray, monitor: np.ndarray, k0: int, k1: int) -> np.ndarray:
    """NRMS per trace between sample indices k0 and k1: the standard repeatability map."""
    b, m = np.asarray(base[..., k0:k1], dtype=np.float32), np.asarray(monitor[..., k0:k1], dtype=np.float32)
    return (200 * _rms(m - b, -1) / (_rms(m, -1) + _rms(b, -1) + 1e-12)).astype(np.float32)


def time_shift(base: np.ndarray, monitor: np.ndarray, window: int = 25, max_lag: int = 3,
               smooth_traces: int = 3) -> np.ndarray:
    """Local time shift of the monitor relative to the base, in samples (sub-sample precision).

    Windowed normalised cross-correlation at integer lags, refined with a parabola through the peak.
    window:        correlation window in samples; about 100 ms is usual. Shorter = sharper but noisier.
    max_lag:       largest shift searched. Real 4D shifts are a few ms; a result pinned at +/-max_lag
                   means the search is too narrow or the surveys are not aligned.
    smooth_traces: lateral smoothing of the result over this many traces (1 = none).
    Memory: holds 2*max_lag+1 float32 copies of the cube; crop to the interval of interest first.
    """
    b, m = np.asarray(base, dtype=np.float32), np.asarray(monitor, dtype=np.float32)
    lags = np.arange(-max_lag, max_lag + 1)
    cc = np.empty((len(lags),) + b.shape, dtype=np.float32)
    for i, lag in enumerate(lags):
        ms = np.roll(m, -lag, axis=-1)                      # ms[t] = m[t + lag]
        cc[i] = uniform_filter1d(b * ms, size=window, axis=-1) / np.sqrt(
            uniform_filter1d(ms * ms, size=window, axis=-1) + 1e-12)
    k = np.clip(cc.argmax(axis=0), 1, len(lags) - 2)
    y0, y1, y2 = (np.take_along_axis(cc, (k + d)[None], 0)[0] for d in (-1, 0, 1))
    curv = y0 - 2 * y1 + y2
    delta = np.where(curv < -1e-9, 0.5 * (y0 - y2) / np.where(curv == 0, 1, curv), 0.0)
    shift = lags[k] + np.clip(delta, -1, 1)
    if smooth_traces > 1 and shift.ndim == 3:
        shift = uniform_filter(shift, size=(smooth_traces, smooth_traces, 1))
    return shift.astype(np.float32)


def apply_shift(monitor: np.ndarray, shift: np.ndarray | float) -> np.ndarray:
    """Warp the monitor onto base time: out[t] = monitor[t + shift[t]] (linear interpolation)."""
    m = np.asarray(monitor, dtype=np.float32)
    n = m.shape[-1]
    pos = np.clip(np.arange(n, dtype=np.float32) + shift, 0, n - 1)
    pos = np.broadcast_to(pos, m.shape)
    i0 = np.clip(np.floor(pos).astype(np.int64), 0, n - 2)
    frac = (pos - i0).astype(np.float32)
    return (1 - frac) * np.take_along_axis(m, i0, -1) + frac * np.take_along_axis(m, i0 + 1, -1)


def match(base: np.ndarray, monitor: np.ndarray, k0: int, k1: int, max_lag: int = 3) -> tuple[np.ndarray, dict]:
    """Remove survey-wide differences using a quiet window (sample indices k0..k1) where no production
    effect is expected, normally the overburden: one bulk time shift and one amplitude scalar.

    Returns the matched monitor and a report with what was removed and NRMS in the window before
    and after. If NRMS barely improves, the surveys differ in ways a scalar cannot fix (phase,
    bandwidth, positioning) and small 4D signals should not be trusted.
    """
    b, m = np.asarray(base, dtype=np.float32), np.asarray(monitor, dtype=np.float32)
    before = nrms(b[..., k0:k1], m[..., k0:k1])
    ts = time_shift(b[..., k0:k1], m[..., k0:k1], window=min(25, k1 - k0), max_lag=max_lag, smooth_traces=1)
    bulk = float(np.median(ts))
    out = apply_shift(m, bulk)
    scale = float(_rms(b[..., k0:k1]) / (_rms(out[..., k0:k1]) + 1e-12))
    out = (out * scale).astype(np.float32)
    after = nrms(b[..., k0:k1], out[..., k0:k1])
    return out, dict(bulk_shift_samples=round(bulk, 3), amplitude_scale=round(scale, 4),
                     nrms_before=round(before, 1), nrms_after=round(after, 1))


def rms_along_horizon(x: np.ndarray, horizon_samples: np.ndarray, half: int = 5, offset: int = 0) -> np.ndarray:
    """RMS of a cube in a window of +/- half samples around a horizon given as sample indices (2D).

    Use on the difference cube for a map of 4D change at the reservoir. offset moves the window
    centre down (positive) or up, in samples.
    """
    n = x.shape[-1]
    centre = np.nan_to_num(np.asarray(horizon_samples, dtype=float), nan=0).round().astype(int) + offset
    acc = np.zeros(x.shape[:-1], dtype=np.float64)
    for d in range(-half, half + 1):
        idx = np.clip(centre + d, 0, n - 1)[..., None]
        acc += np.take_along_axis(np.asarray(x), idx, -1)[..., 0].astype(np.float64) ** 2
    out = np.sqrt(acc / (2 * half + 1)).astype(np.float32)
    out[np.isnan(np.asarray(horizon_samples, dtype=float))] = np.nan
    return out


def value_along_horizon(x: np.ndarray, horizon_samples: np.ndarray, offset: int = 0) -> np.ndarray:
    """Value of a cube (e.g. a time-shift volume) at a horizon given as sample indices, plus offset."""
    idx = np.clip(np.asarray(horizon_samples).round().astype(int) + offset, 0, x.shape[-1] - 1)[..., None]
    return np.take_along_axis(np.asarray(x), idx, -1)[..., 0]


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="base cube path without extension (.npy + .json from segy_to_npy.py)")
    ap.add_argument("monitor")
    ap.add_argument("--quiet-window", type=int, nargs=2, metavar=("K0", "K1"),
                    help="sample indices of an interval with no expected change (default: the top third)")
    a = ap.parse_args()
    cubes, metas = [], []
    for p in (a.base, a.monitor):
        cubes.append(np.load(Path(p).with_suffix(".npy"), mmap_mode="r"))
        metas.append(json.loads(Path(p).with_suffix(".json").read_text()))
    problems = same_geometry(*metas)
    if problems:
        print(json.dumps({"comparable": False, "problems": problems}, indent=1))
        raise SystemExit(1)
    k0, k1 = a.quiet_window or (0, cubes[0].shape[-1] // 3)
    matched, report = match(cubes[0], cubes[1], k0, k1)
    diff = matched - cubes[0]
    print(json.dumps({
        "comparable": True, "shape": list(cubes[0].shape), "quiet_window_samples": [k0, k1], "match": report,
        "nrms_whole_cube_after_match": round(nrms(cubes[0], matched), 1),
        "difference_clip_p99": round(float(np.percentile(np.abs(diff[::2, ::2, ::2]), 99)), 4),
        "note": "Display the difference with the same clip as the base, or a stated fraction of it.",
    }, indent=1))
