"""Convert a 3D post-stack SEG-Y (or a crop of it) to a .npy cube plus a JSON sidecar.

The .npy is opened with np.load(..., mmap_mode="r"), so an app slices inlines, crosslines
and time slices instantly without holding the volume in memory.

Usage:
    python segy_to_npy.py survey.sgy data/survey
    python segy_to_npy.py survey.sgy data/crop --ilines 10090 10150 --xlines 2150 2300 --samples 0 400
    python segy_to_npy.py survey.sgy data/survey --iline-byte 9 --xline-byte 21

Writes data/survey.npy (float32, axes: inline, crossline, sample) and data/survey.json
(line numbers, sample values, clip_p99 for display, corner coordinates, ilxl_to_xy affine).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import segyio


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path, help="output path without extension")
    ap.add_argument("--iline-byte", type=int, default=189)
    ap.add_argument("--xline-byte", type=int, default=193)
    ap.add_argument("--ilines", type=int, nargs=2, metavar=("FIRST", "LAST"), help="inline number range, inclusive")
    ap.add_argument("--xlines", type=int, nargs=2, metavar=("FIRST", "LAST"), help="crossline number range, inclusive")
    ap.add_argument("--samples", type=int, nargs=2, metavar=("FIRST", "LAST"), help="sample index range, end exclusive")
    args = ap.parse_args()

    with segyio.open(str(args.src), iline=args.iline_byte, xline=args.xline_byte) as f:
        ilines, xlines = np.asarray(f.ilines), np.asarray(f.xlines)
        samples = np.asarray(f.samples, dtype=float)
        il_mask = np.ones(len(ilines), bool) if not args.ilines else (ilines >= args.ilines[0]) & (ilines <= args.ilines[1])
        xl_mask = np.ones(len(xlines), bool) if not args.xlines else (xlines >= args.xlines[0]) & (xlines <= args.xlines[1])
        s0, s1 = args.samples if args.samples else (0, len(samples))
        il_sel, xl_sel, smp = ilines[il_mask], xlines[xl_mask], samples[s0:s1]
        if not len(il_sel) or not len(xl_sel) or not len(smp):
            raise SystemExit("crop selects nothing; check ranges against inspect_segy.py output")

        args.dst.parent.mkdir(parents=True, exist_ok=True)
        npy = args.dst.with_suffix(".npy")
        out = np.lib.format.open_memmap(npy, mode="w+", dtype=np.float32, shape=(len(il_sel), len(xl_sel), len(smp)))
        xl_idx = np.flatnonzero(xl_mask)
        for i, il in enumerate(il_sel):  # one inline at a time keeps memory flat
            out[i] = f.iline[int(il)][xl_idx, s0:s1]
        out.flush()

        # corner coordinates of the crop, for map display
        scalar = int(f.header[0][segyio.TraceField.SourceGroupScalar])
        mult = 1.0 if scalar == 0 else (float(scalar) if scalar > 0 else 1.0 / abs(scalar))
        n_xl = len(xlines)
        corners = {}
        for name, (ii, xi) in {"first_il_first_xl": (0, 0), "first_il_last_xl": (0, -1),
                               "last_il_first_xl": (-1, 0), "last_il_last_xl": (-1, -1)}.items():
            tr = int(np.flatnonzero(il_mask)[ii]) * n_xl + int(xl_idx[xi])
            h = f.header[tr]
            corners[name] = [h[segyio.TraceField.CDP_X] * mult, h[segyio.TraceField.CDP_Y] * mult]

        # affine map (inline, crossline, 1) @ ilxl_to_xy -> (x, y); invert it to place wells/horizons
        a = np.array([[il_sel[0], xl_sel[0], 1], [il_sel[0], xl_sel[-1], 1],
                      [il_sel[-1], xl_sel[0], 1], [il_sel[-1], xl_sel[-1], 1]], dtype=float)
        xy = np.array([corners["first_il_first_xl"], corners["first_il_last_xl"],
                       corners["last_il_first_xl"], corners["last_il_last_xl"]])
        affine = np.linalg.lstsq(a, xy, rcond=None)[0] if np.any(xy) else None

        nz = out[:: max(1, len(il_sel) // 20)]
        nz = nz[nz != 0]
        meta = {
            "source": args.src.name, "shape": list(out.shape), "axes": ["inline", "crossline", "sample"],
            "ilines": [int(v) for v in il_sel], "xlines": [int(v) for v in xl_sel],
            "samples": [float(v) for v in smp],
            "sample_interval": float(smp[1] - smp[0]) if len(smp) > 1 else None,
            "iline_byte": args.iline_byte, "xline_byte": args.xline_byte,
            "corners_xy": corners,
            "ilxl_to_xy": affine.tolist() if affine is not None else None,
            "clip_p99": float(np.percentile(np.abs(nz), 99)) if nz.size else 1.0,
        }
    args.dst.with_suffix(".json").write_text(json.dumps(meta))
    print(f"wrote {npy} shape={tuple(meta['shape'])} {npy.stat().st_size / 1e6:.1f} MB, clip_p99={meta['clip_p99']:.4g}")


if __name__ == "__main__":
    main()
