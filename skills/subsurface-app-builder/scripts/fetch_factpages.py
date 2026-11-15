"""Download Norwegian Offshore Directorate (Sodir) FactPages tables once and cache them locally.

Each table is one request for one CSV. Cached files are reused unless --max-age-days
has passed, so repeated runs (and app reruns) never touch the network.

Usage:
    python fetch_factpages.py --list
    python fetch_factpages.py field discovery wellbore_exploration_all
    python fetch_factpages.py --core --out data/factpages          # the usual starter set
    python fetch_factpages.py --all --parquet

Data licence: NLOD 2.0 (Norwegian Licence for Open Government Data). Credit "Norwegian Offshore Directorate".
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

URL = ("https://factpages.sodir.no/public?/Factpages/external/tableview/{table}"
       "&rs:Command=Render&rc:Toolbar=false&rc:Parameters=f&IpAddress=not_used"
       "&CultureCode=en&rs:Format=CSV&Top100=false")

TABLES = {
    "wellbore_exploration_all": "exploration wellbores: location, dates, depth, content, age/formation at TD",
    "wellbore_development_all": "development wellbores: purpose, field, facility, dates",
    "wellbore_all_long": "every wellbore, all attributes (largest wellbore table)",
    "wellbore_npdid_overview": "wellbore name to NPDID lookup",
    "wellbore_formation_top": "lithostratigraphic tops per wellbore (top/bottom depth)",
    "strat_litho_wellbore": "lithostratigraphy per wellbore with level (group/formation/member)",
    "wellbore_core": "cored intervals",
    "wellbore_dst": "drill stem tests: rates, pressures, choke",
    "wellbore_mud": "mud weight and viscosity by depth",
    "wellbore_casing_and_lot": "casing strings and leak-off tests",
    "wellbore_document": "links to completion reports and other documents",
    "wellbore_history": "free-text drilling history per wellbore (HTML)",
    "field": "fields: status, operator, area, discovery well, HC type",
    "field_description": "free-text field descriptions (development, reservoir, recovery, transport)",
    "field_production_monthly": "monthly oil, gas, NGL, condensate, water per field",
    "field_production_yearly": "yearly production per field",
    "field_reserves": "recoverable and remaining reserves per field",
    "field_in_place_volumes": "in-place volumes per field",
    "field_investment_yearly": "yearly investments per field",
    "discovery": "discoveries: year, HC type, activity status, resource class",
    "discovery_reserves": "recoverable resources per discovery",
    "licence": "production licences: dates, status, area",
    "company": "companies registry",
    "facility_fixed": "fixed facilities: kind, water depth, position",
}
CORE = ["wellbore_exploration_all", "field", "discovery", "field_production_monthly", "field_reserves",
        "wellbore_formation_top", "field_description"]


def fetch(table: str, out: Path, max_age_days: float, parquet: bool) -> str:
    dst = out / f"{table}.csv"
    if dst.exists() and dst.stat().st_size > 0 and (time.time() - dst.stat().st_mtime) < max_age_days * 86400:
        status = "cached"
    else:
        r = requests.get(URL.format(table=table), timeout=120, headers={"User-Agent": "subsurface-app-builder"})
        r.raise_for_status()
        if "csv" not in r.headers.get("content-type", "") or len(r.content) < 100:
            raise RuntimeError(f"unexpected response for '{table}' ({r.headers.get('content-type')}, {len(r.content)} bytes)")
        dst.write_bytes(r.content)
        status = "downloaded"
        time.sleep(1)  # be polite: this is a public government service
    if parquet:
        import pandas as pd

        pd.read_csv(dst, encoding="utf-8-sig", low_memory=False).to_parquet(dst.with_suffix(".parquet"), index=False)
    return f"{status:10s} {table:28s} {dst.stat().st_size / 1e6:6.2f} MB"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tables", nargs="*")
    ap.add_argument("--list", action="store_true", help="list known tables and exit")
    ap.add_argument("--core", action="store_true", help=f"fetch the starter set: {', '.join(CORE)}")
    ap.add_argument("--all", action="store_true", help="fetch every known table (about 40 MB)")
    ap.add_argument("--out", type=Path, default=Path("data/factpages"))
    ap.add_argument("--max-age-days", type=float, default=30)
    ap.add_argument("--parquet", action="store_true", help="also write a .parquet copy")
    args = ap.parse_args()

    if args.list:
        for name, desc in TABLES.items():
            print(f"{name:28s} {desc}")
        return
    wanted = list(TABLES) if args.all else (CORE if args.core else []) + args.tables
    if not wanted:
        ap.error("name at least one table, or use --core / --all / --list")
    args.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for t in dict.fromkeys(wanted):
        try:
            print(fetch(t, args.out, args.max_age_days, args.parquet))
        except Exception as e:
            failed += 1
            print(f"FAILED     {t}: {e}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
