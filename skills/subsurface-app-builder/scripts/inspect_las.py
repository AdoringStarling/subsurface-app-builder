"""Summarise LAS files as compact JSON so the file itself never needs to be read into context.

Usage:
    python inspect_las.py WELL.las                # one file, full curve table
    python inspect_las.py data/wells/ --brief     # folder: one line per well + curve coverage matrix

A folder always gives the brief form (coverage, units of the index, flags). Run it on a single file
for the full per-curve statistics.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from subsurface_utils import CURVE_RANGES, canonical_name, compact_json, depth_in_metres, read_las, well_name  # noqa: E402


def _num(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 4)


def inspect(path: Path) -> dict:
    las = read_las(path)
    depth = depth_in_metres(las)
    header = {}
    for key in ("WELL", "UWI", "FLD", "COMP", "CTRY", "LOC", "SRVC", "DATE", "NULL"):
        if key in las.well:
            val = str(las.well[key].value).strip()
            if val:
                header[key] = val
    null = None
    try:
        null = float(las.well["NULL"].value)
    except Exception:
        pass

    curves, warnings = [], []
    for c in las.curves[1:]:
        data = np.asarray(c.data)
        if data.dtype.kind not in "fiu":
            curves.append({"mnemonic": c.mnemonic, "unit": c.unit, "note": "non-numeric"})
            continue
        data = data.astype(float)
        if null is not None:
            data[data == null] = np.nan
        data[np.isin(data, (-999.25, -9999.0, -999.0))] = np.nan
        valid = np.isfinite(data)
        fam = canonical_name(c.mnemonic)
        row = {
            "mnemonic": c.mnemonic,
            "family": fam,
            "unit": c.unit,
            "descr": (c.descr or "")[:40],
            "valid_pct": round(100 * valid.mean(), 1) if len(data) else 0.0,
        }
        if valid.any():
            v = data[valid]
            p = np.percentile(v, [5, 50, 95])
            row.update(min=_num(v.min()), p5=_num(p[0]), p50=_num(p[1]), p95=_num(p[2]), max=_num(v.max()),
                       top_m=_num(depth[valid][0]), base_m=_num(depth[valid][-1]))
            flags = []
            if np.ptp(v) == 0:
                flags.append("constant")
            if fam in CURVE_RANGES:
                lo, hi = CURVE_RANGES[fam]
                out = float(((v < lo) | (v > hi)).mean())
                if out > 0.02:
                    flags.append(f"{out:.0%} outside {lo}-{hi}")
                if fam == "NPHI" and p[1] > 1.5:
                    flags.append("looks like percent, divide by 100")
                if fam == "RHOB" and p[1] > 100:
                    flags.append("looks like kg/m3, divide by 1000")
            if flags:
                row["flags"] = flags
        else:
            row["flags"] = ["all null"]
        curves.append(row)

    step = np.diff(depth)
    if len(step) and not np.allclose(step, step[0], rtol=1e-3, atol=1e-4):
        warnings.append("irregular depth step")
    if len(step) and step[0] < 0:
        warnings.append("depth decreasing (file is bottom-up)")
    fams = [c.get("family") for c in curves if c.get("family")]
    dup = sorted({f for f in fams if fams.count(f) > 1})
    if dup:
        warnings.append(f"several curves per family: {dup}")

    return {
        "file": path.name,
        "well": well_name(las, path.stem),
        "las_version": str(las.version["VERS"].value) if "VERS" in las.version else None,
        "wrapped": str(las.version["WRAP"].value) if "WRAP" in las.version else None,
        "header": header,
        "index": {"mnemonic": las.curves[0].mnemonic, "unit": las.curves[0].unit,
                  "start_m": _num(depth[0]) if len(depth) else None, "stop_m": _num(depth[-1]) if len(depth) else None,
                  "step_m": _num(float(np.median(step))) if len(step) else None, "samples": int(len(depth))},
        "curves": curves,
        "families_present": sorted(set(fams)),
        "warnings": warnings,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path, help="LAS file or folder of LAS files")
    ap.add_argument("--brief", action="store_true", help="one compact record per well (use for folders)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N files of a folder")
    args = ap.parse_args()

    if args.path.is_dir():
        files = sorted(p for p in args.path.rglob("*") if p.suffix.lower() == ".las")
        if args.limit:
            files = files[: args.limit]
    else:
        files = [args.path]
    if not files:
        sys.exit(f"no LAS files found at {args.path}")

    results = []
    for f in files:
        try:
            results.append(inspect(f))
        except Exception as e:  # keep going: one broken file should not hide the rest
            results.append({"file": f.name, "error": f"{type(e).__name__}: {e}"})

    if args.brief or len(results) > 1:
        ok = [r for r in results if "error" not in r]
        coverage: dict[str, int] = {}
        for r in ok:
            for fam in r["families_present"]:
                coverage[fam] = coverage.get(fam, 0) + 1
        out = {
            "files": len(results),
            "errors": [r for r in results if "error" in r],
            "family_coverage_wells": dict(sorted(coverage.items(), key=lambda kv: -kv[1])),
            "wells": [{"file": r["file"], "well": r["well"], "top_m": r["index"]["start_m"], "base_m": r["index"]["stop_m"],
                       "step_m": r["index"]["step_m"], "index_unit": r["index"]["unit"], "null": r["header"].get("NULL"),
                       "families": r["families_present"],
                       "unmapped": [c["mnemonic"] for c in r["curves"] if not c.get("family")],
                       "curve_flags": {c["mnemonic"]: c["flags"] for c in r["curves"] if c.get("flags")},
                       "warnings": r["warnings"]} for r in ok],
        }
        print(compact_json(out))
    else:
        print(compact_json(results[0]))


if __name__ == "__main__":
    main()
