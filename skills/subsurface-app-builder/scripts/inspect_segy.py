"""Describe a SEG-Y file as compact JSON: headers, geometry, sampling, amplitude statistics.

Reads only headers and a sample of traces, so it is safe on multi-gigabyte files.

Usage:
    python inspect_segy.py survey.sgy
    python inspect_segy.py survey.sgy --text-header      # also print the 3200-byte text header
    python inspect_segy.py survey.sgy --iline-byte 9 --xline-byte 21   # force header byte positions
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import segyio

sys.path.insert(0, str(Path(__file__).parent))
from subsurface_utils import compact_json  # noqa: E402

# (inline byte, crossline byte) pairs tried in order: SEG-Y rev1, then common vendor layouts.
BYTE_CANDIDATES = [(189, 193), (9, 21), (5, 21), (9, 17), (13, 17), (17, 21), (181, 185), (221, 225)]

SCAN_FIELDS = {
    "TRACE_SEQUENCE_LINE": 1, "TRACE_SEQUENCE_FILE": 5, "FieldRecord": 9, "TraceNumber": 13,
    "EnergySourcePoint": 17, "CDP": 21, "CDP_TRACE": 25, "offset": 37,
    "SourceX": 73, "SourceY": 77, "GroupX": 81, "GroupY": 85,
    "CDP_X": 181, "CDP_Y": 185, "INLINE_3D": 189, "CROSSLINE_3D": 193,
}


def try_geometry(path: str, il: int, xl: int):
    try:
        with segyio.open(path, iline=il, xline=xl, strict=True) as f:
            if len(f.ilines) < 2 or len(f.xlines) < 2:
                return None
            return {
                "iline_byte": il, "xline_byte": xl,
                "n_ilines": len(f.ilines), "iline_range": [int(f.ilines[0]), int(f.ilines[-1])],
                "iline_step": int(f.ilines[1] - f.ilines[0]),
                "n_xlines": len(f.xlines), "xline_range": [int(f.xlines[0]), int(f.xlines[-1])],
                "xline_step": int(f.xlines[1] - f.xlines[0]),
                "n_offsets": len(f.offsets),
                "sorting": "inline" if f.sorting == segyio.TraceSortingFormat.INLINE_SORTING else "crossline",
            }
    except Exception:
        return None


def scan_headers(f, n_scan: int) -> dict:
    """Show how each candidate header word varies, to help pick inline/crossline/coordinate bytes."""
    n = min(f.tracecount, n_scan)
    out = {}
    for name, byte in SCAN_FIELDS.items():
        vals = f.attributes(byte)[:n]
        uniq = np.unique(vals)
        if len(uniq) == 1 and uniq[0] == 0:
            continue
        out[f"{name}@{byte}"] = {"min": int(vals.min()), "max": int(vals.max()), "n_unique": int(len(uniq)),
                                 "first": [int(v) for v in vals[:4]]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--iline-byte", "--iline", dest="iline", type=int, help="inline header byte")
    ap.add_argument("--xline-byte", "--xline", dest="xline", type=int, help="crossline header byte")
    ap.add_argument("--text-header", action="store_true")
    ap.add_argument("--scan", type=int, default=2000, help="traces to scan for header variation")
    args = ap.parse_args()
    path = str(args.path)

    info: dict = {"file": args.path.name, "size_mb": round(args.path.stat().st_size / 1e6, 1)}
    with segyio.open(path, ignore_geometry=True) as f:
        b = f.bin
        fmt = int(b[segyio.BinField.Format])
        dt_us = int(b[segyio.BinField.Interval])
        samples = np.asarray(f.samples, dtype=float)
        info.update({
            "traces": int(f.tracecount),
            "samples_per_trace": int(len(samples)),
            "sample_interval": dt_us / 1000.0,
            "sample_interval_note": "ms for time data; for depth data the same number is metres or feet",
            "first_sample": float(samples[0]), "last_sample": float(samples[-1]),
            "sample_format": {1: "IBM float32", 2: "int32", 3: "int16", 5: "IEEE float32", 8: "int8"}.get(fmt, str(fmt)),
            "segy_revision": int(b[segyio.BinField.SEGYRevision]),
            "measurement_system": {1: "metres", 2: "feet"}.get(int(b[segyio.BinField.MeasurementSystem]), "unset"),
        })
        text = segyio.tools.wrap(f.text[0])
        if args.text_header:
            info["text_header"] = text
        else:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip() and ln.strip() not in {f"C{i:2d}" for i in range(1, 41)}]
            info["text_header_first_lines"] = lines[:12]
            info["text_header_hint"] = "rerun with --text-header for all 40 lines; byte positions are often documented there"

        # coordinates
        h0 = f.header[0]
        scalar = int(h0[segyio.TraceField.SourceGroupScalar])
        mult = 1.0 if scalar == 0 else (float(scalar) if scalar > 0 else 1.0 / abs(scalar))
        n = min(f.tracecount, args.scan)
        step = max(1, f.tracecount // n)
        idx = np.unique(np.append(np.arange(0, f.tracecount, step)[:n], f.tracecount - 1))
        for label, (bx, by) in {"cdp_xy@181/185": (181, 185), "source_xy@73/77": (73, 77)}.items():
            x = f.attributes(bx)[idx] * mult
            y = f.attributes(by)[idx] * mult
            if np.any(x) or np.any(y):
                info[label] = {"x_range": [round(float(x.min()), 2), round(float(x.max()), 2)],
                               "y_range": [round(float(y.min()), 2), round(float(y.max()), 2)],
                               "note": "approximate, from a sample of traces"}
        info["coordinate_scalar"] = scalar

        # amplitudes from a spread of traces
        amp = np.concatenate([f.trace[int(i)] for i in idx[:: max(1, len(idx) // 200)]]).astype(float)
        nz = amp[amp != 0]
        if len(nz):
            p = np.percentile(nz, [1, 50, 99])
            info["amplitude"] = {"min": float(amp.min()), "max": float(amp.max()), "p1": float(p[0]),
                                 "p50": float(p[1]), "p99": float(p[2]), "rms": float(np.sqrt(np.mean(nz ** 2))),
                                 "zero_pct": round(100 * float((amp == 0).mean()), 1),
                                 "display_clip_suggestion": float(np.percentile(np.abs(nz), 99))}
        header_scan = scan_headers(f, args.scan)

    pairs = [(args.iline, args.xline)] if args.iline and args.xline else BYTE_CANDIDATES
    geom = next((g for il, xl in pairs if (g := try_geometry(path, il, xl))), None)
    if geom:
        info["geometry"] = {"type": "3D post-stack" if geom["n_offsets"] == 1 else "3D pre-stack", **geom}
        full = geom["n_ilines"] * geom["n_xlines"] * geom["n_offsets"]
        info["cube_gb_as_float32"] = round(full * info["samples_per_trace"] * 4 / 1e9, 2)
        std = (geom["iline_byte"], geom["xline_byte"]) == (189, 193)
        if not std:
            info["note"] = (f"inline/crossline are in bytes {geom['iline_byte']}/{geom['xline_byte']}, not the SEG-Y rev1 "
                            "positions 189/193. Software that assumes the standard will fail to build a cube from this file.")
        info["convert_command"] = (f"python segy_to_npy.py {args.path.name} <out path without extension>"
                                   + ("" if std else f" --iline-byte {geom['iline_byte']} --xline-byte {geom['xline_byte']}"))
    else:
        info["geometry"] = {"type": "unstructured (2D line, irregular 3D, or unknown byte positions)",
                            "hint": "check header_scan and the text header, then pass --iline-byte/--xline-byte; "
                                    "for 2D lines open with ignore_geometry=True and treat traces as one section"}
        info["header_scan"] = header_scan
    print(compact_json(info))


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
        sys.exit(str(e))
