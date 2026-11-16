"""Generate small synthetic well logs (LAS) and a 3D seismic cube (SEG-Y) for tests and offline work.

The data is physically plausible (sand/shale sequence with a hydrocarbon sand, layered
reflectivity with a fault) but invented. Label it as synthetic wherever it is shown.

Usage:
    python make_synthetic.py data/synthetic                 # 3 wells + 1 cube
    python make_synthetic.py data/synthetic --wells 8 --seed 7
    python make_synthetic.py data/synthetic --monitor       # also a 4D monitor cube (production effect + noise)
    python make_synthetic.py data/synthetic --geosteer      # also a horizontal well: type log, LWD gamma ray, survey
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def make_well(name: str, rng: np.random.Generator, top: float = 1500.0, base: float = 2100.0, step: float = 0.1524):
    import lasio

    depth = np.arange(top, base, step)
    n = len(depth)
    # blocky shale fraction: random beds 2-25 m thick
    vsh = np.empty(n)
    i = 0
    while i < n:
        thick = int(rng.uniform(2, 25) / step)
        vsh[i:i + thick] = rng.choice([0.05, 0.15, 0.5, 0.85, 0.95], p=[0.2, 0.15, 0.15, 0.25, 0.25])
        i += thick
    vsh = np.clip(np.convolve(vsh, np.ones(7) / 7, mode="same") + rng.normal(0, 0.03, n), 0, 1)
    phi = np.clip(0.28 * (1 - vsh) + 0.04 - (depth - top) * 2e-5 + rng.normal(0, 0.01, n), 0.01, 0.4)
    owc = top + (base - top) * rng.uniform(0.45, 0.6)
    pay = (depth > owc - 60) & (depth < owc) & (vsh < 0.35)
    sw = np.where(pay, np.clip(0.15 + vsh * 0.8, 0, 1), 1.0)

    gr = 20 + 100 * vsh + rng.normal(0, 4, n)
    rho_fl = np.where(pay, 0.8, 1.03)
    rhob = (1 - phi) * (2.65 + 0.05 * vsh) + phi * rho_fl + rng.normal(0, 0.01, n)
    nphi = phi + 0.25 * vsh - np.where(pay, 0.03, 0) + rng.normal(0, 0.01, n)
    rt_clean = 0.06 / (phi ** 2 * sw ** 2)
    rdep = np.exp(np.log(np.clip(1 / ((1 - vsh) / rt_clean + vsh / 3.0), 0.2, 2000)) + rng.normal(0, 0.05, n))
    dtc = 55.5 * (1 - phi) + 189 * phi + 25 * vsh + rng.normal(0, 1, n)
    bs = np.full(n, 8.5)
    cali = bs + 0.2 + np.where(vsh > 0.8, rng.uniform(0, 1.5, n), 0) + rng.normal(0, 0.05, n)

    # realistic defects: a null gap, a washout with bad density, different mnemonics per well
    gap = slice(int(n * 0.2), int(n * 0.2) + 40)
    nphi[gap] = np.nan
    wash = slice(int(n * 0.7), int(n * 0.7) + 60)
    cali[wash] += 4
    rhob[wash] -= 0.35

    las = lasio.LASFile()
    las.well["WELL"] = lasio.HeaderItem("WELL", value=name)
    las.well["FLD"] = lasio.HeaderItem("FLD", value="SYNTHETIC")
    las.well["COMP"] = lasio.HeaderItem("COMP", value="SYNTHETIC DATA - NOT REAL")
    names = rng.choice(["std", "vendor"])
    mn = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "RDEP": "RDEP", "DTC": "DTC"} if names == "std" else \
         {"GR": "SGR", "RHOB": "RHOZ", "NPHI": "TNPH", "RDEP": "AT90", "DTC": "DTCO"}
    las.append_curve("DEPT", depth, unit="m", descr="Measured depth")
    las.append_curve(mn["GR"], gr, unit="gAPI", descr="Gamma ray")
    las.append_curve("CALI", cali, unit="in", descr="Caliper")
    las.append_curve("BS", bs, unit="in", descr="Bit size")
    las.append_curve(mn["RDEP"], rdep, unit="ohm.m", descr="Deep resistivity")
    las.append_curve(mn["RHOB"], rhob, unit="g/cm3", descr="Bulk density")
    las.append_curve(mn["NPHI"], nphi, unit="v/v", descr="Neutron porosity")
    las.append_curve(mn["DTC"], dtc, unit="us/ft", descr="Compressional slowness")
    return las


def ricker(f: float, dt: float, length: float = 0.128) -> np.ndarray:
    t = np.arange(-length / 2, length / 2, dt)
    a = (np.pi * f * t) ** 2
    return (1 - 2 * a) * np.exp(-a)


def _model(rng: np.random.Generator, n_il: int, n_xl: int, n_s: int):
    """Reflectivity volume and the structural shift (in samples) of every trace."""
    il, xl = np.meshgrid(np.arange(n_il), np.arange(n_xl), indexing="ij")
    # structure: gentle anticline + dip, plus a normal fault with 12 samples of throw
    shift = 18 * np.exp(-(((il - n_il / 2) / 25) ** 2 + ((xl - n_xl / 2) / 30) ** 2)) - 0.1 * xl
    shift = shift + np.where(xl > 0.6 * n_xl + 0.2 * il, -12, 0)
    refl_1d = rng.normal(0, 1, n_s + 80) * (rng.random(n_s + 80) < 0.12)
    refl_1d[140] = -2.5  # one bright event to follow across the volume
    idx = np.arange(n_s)[None, None, :] + 40 - np.round(shift)[:, :, None].astype(int)
    return refl_1d[np.clip(idx, 0, len(refl_1d) - 1)], shift


def _to_seismic(refl: np.ndarray, rng: np.random.Generator, dt_ms: float, noise: float = 0.05) -> np.ndarray:
    w = ricker(28, dt_ms / 1000)
    cube = np.apply_along_axis(lambda tr: np.convolve(tr, w, mode="same"), 2, refl)
    cube += rng.normal(0, noise, cube.shape)
    return cube.astype(np.float32)


def make_cube(rng: np.random.Generator, n_il: int = 60, n_xl: int = 80, n_s: int = 251, dt_ms: float = 4.0) -> np.ndarray:
    refl, _ = _model(rng, n_il, n_xl, n_s)
    return _to_seismic(refl, rng, dt_ms)


def make_base_and_monitor(rng: np.random.Generator, n_il: int = 60, n_xl: int = 80, n_s: int = 251, dt_ms: float = 4.0,
                          dimming: float = 0.6, slowdown_ms: float = 3.0):
    """A base cube (identical to make_cube for the same seed) and a monitor survey shot "after production".

    Production effect, confined to the anticline crest on one side of the fault: the bright reservoir
    event loses `dimming` of its strength and everything below it arrives up to `slowdown_ms` later.
    Non-repeatability, everywhere: new random noise, 8 % stronger amplitudes and a 1 ms static.
    Returns base, monitor, truth (dict with the reservoir horizon in samples and the footprint weights).
    """
    refl, shift = _model(rng, n_il, n_xl, n_s)
    base = _to_seismic(refl, rng, dt_ms)

    il, xl = np.meshgrid(np.arange(n_il), np.arange(n_xl), indexing="ij")
    r = np.sqrt(((il - n_il / 2) / 14) ** 2 + ((xl - 0.45 * n_xl) / 16) ** 2)
    weight = np.clip(1.5 - 1.5 * r, 0, 1) * (xl <= 0.6 * n_xl + 0.2 * il)      # soft edge, sealed by the fault
    horizon = (100 + np.round(shift)).astype(int)                             # sample of the bright event

    refl_m = refl.copy()
    ii, xx = np.nonzero(weight)
    refl_m[ii, xx, horizon[ii, xx]] *= 1 - dimming * weight[ii, xx]
    mon = _to_seismic(refl_m, rng, dt_ms)

    # delay below the reservoir, ramping in over 10 samples, plus the static:  monitor(t) = clean(t - delay)
    k = np.arange(n_s)[None, None, :]
    ramp = np.clip((k - horizon[:, :, None]) / 10.0, 0, 1)
    delay = (slowdown_ms * weight[:, :, None] * ramp + 1.0) / dt_ms
    pos = np.clip(k - delay, 0, n_s - 1)
    i0 = np.clip(np.floor(pos).astype(int), 0, n_s - 2)
    frac = (pos - i0).astype(np.float32)
    mon = (1 - frac) * np.take_along_axis(mon, i0, 2) + frac * np.take_along_axis(mon, i0 + 1, 2)
    mon = (1.08 * mon).astype(np.float32)
    truth = dict(horizon_sample=horizon.tolist(), footprint=np.round(weight, 2).tolist(), dt_ms=dt_ms,
                 dimming=dimming, slowdown_ms=slowdown_ms, static_ms=1.0, amplitude_scale=1.08)
    return base, mon, truth


def make_geosteer(rng: np.random.Generator, md_start: float = 2200.0, md_end: float = 3800.0, azimuth: float = 45.0):
    """A horizontal well for geosteering work: type log, LWD gamma ray along the lateral, survey, truth.

    The target is a 12 m sand (type-log depth 1950-1962 m) with a thin shale streak. The formation
    dips change along the section and the well follows them late, so it leaves the sand in places.
    Dip convention: positive = beds get deeper in the drilling direction.
    Returns type_las, lateral_las, survey (list of dict rows), truth.
    """
    import lasio

    # --- type log (vertical offset well): blocky beds with a recognisable sequence around the target
    zt = np.arange(1880.0, 2020.0, 0.1524)
    gr_t = np.empty(len(zt))
    i = 0
    while i < len(zt):
        thick = int(rng.uniform(2, 7) / 0.1524)
        gr_t[i:i + thick] = rng.uniform(75, 125)
        i += thick
    for top, base, val in [(1938, 1944, 95), (1944, 1947, 150), (1947, 1950, 72), (1950, 1962, 30),
                           (1955.2, 1956.0, 78), (1962, 1969, 105), (1969, 1970.5, 22), (1970.5, 1978, 115)]:
        gr_t[(zt >= top) & (zt < base)] = val
    gr_t = np.convolve(np.pad(gr_t, 3, mode="edge"), np.ones(7) / 7, mode="valid") + rng.normal(0, 2.5, len(zt))
    zone = (1950.0, 1962.0)

    # --- true structure along the vertical section, and a well that reacts to it 220 m late
    nodes = np.array([0.0, 250.0, 500.0, 750.0, 1000.0, 1250.0])
    dips = np.array([0.5, 1.6, -0.6, -1.8, 0.9, 2.2])
    md = np.arange(md_start, md_end + 0.25, 0.5)
    build_end = md_start + 300.0
    inc = np.empty(len(md))
    tvd = np.zeros(len(md))
    vs = np.zeros(len(md))
    for j in range(len(md)):
        m = md[j]
        if m <= build_end:
            inc[j] = 70 + 19.5 * (m - md_start) / 300.0
        else:
            seen = dips[np.searchsorted(nodes, max(vs[j - 1] - 220.0, 0.0), side="right") - 1]
            inc[j] = 90 - seen + 0.5 * np.sin((m - build_end) / 110.0)
        if j:
            a = np.radians(0.5 * (inc[j] + inc[j - 1]))
            tvd[j] = tvd[j - 1] + 0.5 * np.cos(a)
            vs[j] = vs[j - 1] + 0.5 * np.sin(a)
    seg = np.searchsorted(nodes, vs, side="right") - 1
    node_shift = np.concatenate([[0.0], np.cumsum(np.tan(np.radians(dips[:-1])) * np.diff(nodes))])
    shift = node_shift[seg] + np.tan(np.radians(dips[seg])) * (vs - nodes[seg])
    land = int(np.searchsorted(md, build_end))
    tvd += 1954.0 - (tvd[land] - shift[land])              # land 4 m below the top of the sand
    gr = np.interp(tvd - shift, zt, gr_t) + rng.normal(0, 3.0, len(md))

    def las(name, index, values, descr):
        f = lasio.LASFile()
        f.well["WELL"] = lasio.HeaderItem("WELL", value=name)
        f.well["FLD"] = lasio.HeaderItem("FLD", value="SYNTHETIC")
        f.well["COMP"] = lasio.HeaderItem("COMP", value="SYNTHETIC DATA - NOT REAL")
        f.append_curve("DEPT", index, unit="m", descr=descr)
        f.append_curve("GR", values, unit="gAPI", descr="Gamma ray")
        return f

    st = np.arange(0, len(md), 60)                          # a survey station every 30 m
    survey = [dict(md=round(float(md[k]), 2), inc=round(float(inc[k]), 3), azi=azimuth) for k in st]
    in_zone = (tvd - shift >= zone[0]) & (tvd - shift <= zone[1])
    truth = dict(nodes_vs=nodes.tolist(), dips_deg=dips.tolist(), zone_top=zone[0], zone_base=zone[1],
                 tvd_at_first_station=round(float(tvd[0]), 3), azimuth=azimuth,
                 in_zone_fraction=round(float(in_zone[land:].mean()), 3))
    return las("SYN-TYPE", zt, gr_t, "True vertical depth"), las("SYN-LATERAL", md, gr, "Measured depth"), survey, truth


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--wells", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-seismic", action="store_true")
    ap.add_argument("--monitor", action="store_true", help="also write a 4D monitor cube and its truth file")
    ap.add_argument("--geosteer", action="store_true", help="also write a horizontal-well geosteering case")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    wells_dir = args.out / "wells"
    wells_dir.mkdir(parents=True, exist_ok=True)
    for i in range(args.wells):
        name = f"SYN-{i + 1}"
        with open(wells_dir / f"{name}.las", "w") as fh:
            make_well(name, rng).write(fh, version=2.0)
    print(f"wrote {args.wells} LAS files to {wells_dir}")

    if not args.no_seismic:
        import segyio

        dst = args.out / "synthetic_cube.sgy"
        if args.monitor:
            import json

            cube, monitor, truth = make_base_and_monitor(rng)
            segyio.tools.from_array3D(str(args.out / "synthetic_monitor.sgy"), monitor, iline=189, xline=193, dt=4000)
            (args.out / "synthetic_4d_truth.json").write_text(json.dumps(truth))
            print(f"wrote {args.out / 'synthetic_monitor.sgy'} and synthetic_4d_truth.json")
        else:
            cube = make_cube(rng)
        segyio.tools.from_array3D(str(dst), cube, iline=189, xline=193, dt=4000)
        print(f"wrote {dst} shape={cube.shape} (inline, crossline, sample), 4 ms")

    if args.geosteer:
        import csv
        import json

        gdir = args.out / "geosteer"
        gdir.mkdir(parents=True, exist_ok=True)
        type_las, lateral_las, survey, truth = make_geosteer(np.random.default_rng(args.seed + 1))
        for name, f in (("type_well.las", type_las), ("lateral.las", lateral_las)):
            with open(gdir / name, "w") as fh:
                f.write(fh, version=2.0)
        with open(gdir / "survey.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["md", "inc", "azi"])
            w.writeheader()
            w.writerows(survey)
        (gdir / "truth.json").write_text(json.dumps(truth, indent=1))
        print(f"wrote geosteering case to {gdir}: type_well.las, lateral.las, survey.csv, truth.json")


if __name__ == "__main__":
    main()
