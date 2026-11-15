"""Generate small synthetic well logs (LAS) and a 3D seismic cube (SEG-Y) for tests and offline work.

The data is physically plausible (sand/shale sequence with a hydrocarbon sand, layered
reflectivity with a fault) but invented. Label it as synthetic wherever it is shown.

Usage:
    python make_synthetic.py data/synthetic                 # 3 wells + 1 cube
    python make_synthetic.py data/synthetic --wells 8 --seed 7
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


def make_cube(rng: np.random.Generator, n_il: int = 60, n_xl: int = 80, n_s: int = 251, dt_ms: float = 4.0) -> np.ndarray:
    il, xl = np.meshgrid(np.arange(n_il), np.arange(n_xl), indexing="ij")
    # structure: gentle anticline + dip, plus a normal fault with 12 samples of throw
    shift = 18 * np.exp(-(((il - n_il / 2) / 25) ** 2 + ((xl - n_xl / 2) / 30) ** 2)) - 0.1 * xl
    shift = shift + np.where(xl > 0.6 * n_xl + 0.2 * il, -12, 0)
    refl_1d = rng.normal(0, 1, n_s + 80) * (rng.random(n_s + 80) < 0.12)
    refl_1d[140] = -2.5  # one bright event to follow across the volume
    idx = np.arange(n_s)[None, None, :] + 40 - np.round(shift)[:, :, None].astype(int)
    refl = refl_1d[np.clip(idx, 0, len(refl_1d) - 1)]
    w = ricker(28, dt_ms / 1000)
    cube = np.apply_along_axis(lambda tr: np.convolve(tr, w, mode="same"), 2, refl)
    cube += rng.normal(0, 0.05, cube.shape)
    return cube.astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--wells", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-seismic", action="store_true")
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

        cube = make_cube(rng)
        dst = args.out / "synthetic_cube.sgy"
        segyio.tools.from_array3D(str(dst), cube, iline=189, xline=193, dt=4000)
        print(f"wrote {dst} shape={cube.shape} (inline, crossline, sample), 4 ms")


if __name__ == "__main__":
    main()
