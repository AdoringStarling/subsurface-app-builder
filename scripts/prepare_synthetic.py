"""Create the synthetic data used by demos 04 (time-lapse seismic) and 05 (geosteering) in data/synthetic/.

    python scripts/prepare_synthetic.py

Takes a few seconds and needs no network. Everything it writes is invented data.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "subsurface-app-builder" / "scripts"
OUT = ROOT / "data" / "synthetic"


def run(script: str, *args) -> None:
    subprocess.run([sys.executable, str(SKILL / script), *map(str, args)], check=True)


def main() -> None:
    run("make_synthetic.py", OUT, "--wells", 3, "--monitor", "--geosteer")
    run("segy_to_npy.py", OUT / "synthetic_cube.sgy", OUT / "base")
    run("segy_to_npy.py", OUT / "synthetic_monitor.sgy", OUT / "monitor")


if __name__ == "__main__":
    main()
