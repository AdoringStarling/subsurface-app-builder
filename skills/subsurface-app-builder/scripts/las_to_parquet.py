"""Convert a folder of LAS files to one tidy Parquet table (WELL, DEPTH in metres, curves).

Apps load the Parquet in milliseconds instead of re-parsing LAS on every rerun.
Also writes <dst>.notes.json listing, per well, the curves renamed and the units converted,
so the app can tell the user what was changed.

Usage:
    python las_to_parquet.py data/wells/ data/wells.parquet
    python las_to_parquet.py data/wells/ data/wells.parquet --known-only --limit 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from subsurface_utils import las_to_frame  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path, help="LAS file or folder")
    ap.add_argument("dst", type=Path, help="output .parquet")
    ap.add_argument("--raw-names", action="store_true", help="keep original mnemonics instead of canonical families")
    ap.add_argument("--known-only", action="store_true", help="drop curves that map to no canonical family")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    files = sorted(p for p in args.src.rglob("*") if p.suffix.lower() == ".las") if args.src.is_dir() else [args.src]
    if args.limit:
        files = files[: args.limit]
    frames, failed, notes = [], [], {}
    for f in files:
        try:
            frame = las_to_frame(f, canonical=not args.raw_names, keep_unknown=not args.known_only)
            if frame.attrs.get("unit_fixes"):
                print(f"unit fix {f.name}: {'; '.join(frame.attrs['unit_fixes'])}")
            notes[str(frame["WELL"].iloc[0])] = {"file": f.name, "unit_fixes": frame.attrs.get("unit_fixes", []),
                                                 "renamed": frame.attrs.get("renamed", {})}
            frames.append(frame)
        except Exception as e:
            failed.append((f.name, f"{type(e).__name__}: {e}"))
    if not frames:
        sys.exit(f"nothing converted; failures: {failed}")

    df = pd.concat(frames, ignore_index=True)
    df["WELL"] = df["WELL"].astype("category")
    # float32 halves the file; keep float64 for depth and for large values such as UTM coordinates
    for col in df.columns.drop(["WELL", "DEPTH"]):
        if df[col].dtype == "float64" and not (df[col].abs().max() > 1e5):
            df[col] = df[col].astype("float32")
    args.dst.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.dst, index=False, compression="zstd")
    print(f"wrote {args.dst}: {df['WELL'].nunique()} wells, {len(df):,} rows, {df.shape[1]} columns, "
          f"{args.dst.stat().st_size / 1e6:.1f} MB")
    import json

    side = args.dst.with_suffix(".notes.json")  # what was renamed and converted, per well, for the app to show
    side.write_text(json.dumps(notes, indent=1))
    print("columns:", ", ".join(df.columns))
    print(f"conversion notes: {side}")
    for name, err in failed:
        print(f"FAILED {name}: {err}")


if __name__ == "__main__":
    main()
