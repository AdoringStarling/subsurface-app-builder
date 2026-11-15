"""Download the open sample data used by the demos into data/ (about 230 MB, not committed to git).

    python scripts/download_sample_data.py            # everything
    python scripts/download_sample_data.py --skip-wells

Sources and licences
- FORCE 2020 well logs, 118 Norwegian wells (Bormann et al., 2020, doi:10.5281/zenodo.4351156).
  Zenodo record CC-BY-4.0; underlying data NLOD 2.0 from the Norwegian Offshore Directorate.
- Volve seismic sub-cube, horizon and well path from the segysak examples
  (github.com/trhallam/segysak), originally Equinor Volve Data Village, Equinor Open Data Licence.
- FactPages tables, Norwegian Offshore Directorate, NLOD 2.0.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ZENODO = "https://zenodo.org/api/records/4351156/files/{}/content"
SEGYSAK = "https://raw.githubusercontent.com/trhallam/segysak/main/examples/data/{}"

FILES = {
    "wells": [
        (ZENODO.format("LAS_files_Force_2020_all_wells_train_test_blind_hidden_final.zip"), "force2020/las.zip"),
        (ZENODO.format("NPD_Lithostratigraphy_groups_all_wells.xlsx"), "force2020/lithostrat_groups.xlsx"),
        (ZENODO.format("NPD_Casing_depth_most_wells.xlsx"), "force2020/casing_depths.xlsx"),
    ],
    "seismic": [
        (SEGYSAK.format("volve10r12-full-twt-sub3d.sgy"), "volve/volve10r12-full-twt-sub3d.sgy"),
        (SEGYSAK.format("hor_twt_hugin_fm_top.dat"), "volve/hor_twt_hugin_fm_top.dat"),
        (SEGYSAK.format("well_f12_deviation.asc"), "volve/well_f12_deviation.asc"),
        (SEGYSAK.format("licence"), "volve/LICENCE.txt"),
    ],
}


def download(url: str, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size > 0:
        print(f"have       {dst.relative_to(ROOT)}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with requests.get(url, stream=True, timeout=120, headers={"User-Agent": "subsurface-app-builder"}) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
    tmp.replace(dst)
    print(f"downloaded {dst.relative_to(ROOT)} ({dst.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-wells", action="store_true")
    ap.add_argument("--skip-seismic", action="store_true")
    ap.add_argument("--skip-factpages", action="store_true")
    args = ap.parse_args()

    if not args.skip_wells:
        for url, rel in FILES["wells"]:
            download(url, DATA / rel)
        las_dir = DATA / "force2020" / "las"
        if not las_dir.exists():
            with zipfile.ZipFile(DATA / "force2020" / "las.zip") as z:
                for m in z.infolist():  # flatten and guard against paths escaping the folder
                    if m.filename.lower().endswith(".las"):
                        target = las_dir / Path(m.filename).name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(z.read(m))
            print(f"extracted  {len(list(las_dir.glob('*')))} LAS files to {las_dir.relative_to(ROOT)}")
    if not args.skip_seismic:
        for url, rel in FILES["seismic"]:
            download(url, DATA / rel)
    if not args.skip_factpages:
        script = ROOT / "skills" / "subsurface-app-builder" / "scripts" / "fetch_factpages.py"
        subprocess.run([sys.executable, str(script), "--all", "--out", str(DATA / "factpages")], check=False)


if __name__ == "__main__":
    main()
