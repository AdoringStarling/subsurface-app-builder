"""Shared helpers for subsurface data: curve aliases, LAS loading, quick petrophysics.

Copy this file next to an app (or add this folder to sys.path) and import from it.
Only depends on numpy, pandas and lasio.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Canonical curve family -> mnemonics seen in the wild (upper case, first match wins).
CURVE_ALIASES: dict[str, list[str]] = {
    "GR": ["GR", "GRC", "SGR", "CGR", "HGR", "ECGR", "GRD", "GR_EDTC", "HSGR", "GAMMA", "GRGC", "GRS"],
    "CALI": ["CALI", "CAL", "HCAL", "CALS", "C1", "DCAL_RAW", "LCAL", "CALX"],
    "BS": ["BS", "BIT", "BITSIZE"],
    "RDEP": ["RDEP", "RT", "ILD", "LLD", "RLLD", "RD", "AT90", "RLA5", "HDRS", "RILD", "RES_DEEP", "P40H", "RPCEH", "HLLD"],
    "RMED": ["RMED", "ILM", "LLS", "RM", "AT30", "RLA3", "HMRS", "RILM", "RES_MED", "P28H", "RPCEL"],
    "RSHA": ["RSHA", "MSFL", "SFLU", "RXO", "AT10", "RLA1", "RS", "SFL", "LL8", "RES_SHAL"],
    "RHOB": ["RHOB", "RHOZ", "DEN", "ZDEN", "RHO", "DENS", "HRHOB", "ZDNC", "BDCX"],
    "DRHO": ["DRHO", "DRH", "HDRA", "ZCOR", "DCOR"],
    "NPHI": ["NPHI", "TNPH", "NPOR", "CNC", "NEU", "CN", "HNPHI", "NPHI_LS", "PHIN", "CNL", "NEUT"],
    "PEF": ["PEF", "PE", "PEFZ", "PEZ", "HPEF"],
    "DTC": ["DTC", "DT", "AC", "DTCO", "DT4P", "DTCOMP", "SONIC", "DT24"],
    "DTS": ["DTS", "DTSM", "DT4S", "DTSH", "DTSHEAR"],
    "SP": ["SP", "SPC", "SSP"],
    "ROP": ["ROP", "ROP5", "ROPA", "ROP_AVG"],
}

# Plausible physical ranges, used for QC flags (not hard limits).
CURVE_RANGES: dict[str, tuple[float, float]] = {
    "GR": (0, 400), "CALI": (4, 30), "BS": (4, 36), "RDEP": (0.05, 20000),
    "RMED": (0.05, 20000), "RSHA": (0.05, 20000), "RHOB": (1.0, 3.2),
    "DRHO": (-0.5, 0.5), "NPHI": (-0.15, 1.0), "PEF": (0, 15),
    "DTC": (35, 250), "DTS": (60, 600), "SP": (-400, 400), "ROP": (0, 500),
}

CURVE_UNITS: dict[str, str] = {
    "GR": "gAPI", "CALI": "in", "BS": "in", "RDEP": "ohm.m", "RMED": "ohm.m",
    "RSHA": "ohm.m", "RHOB": "g/cm3", "DRHO": "g/cm3", "NPHI": "v/v", "PEF": "b/e",
    "DTC": "us/ft", "DTS": "us/ft", "SP": "mV", "ROP": "m/h",
}

_LOOKUP = {m: fam for fam, ms in CURVE_ALIASES.items() for m in ms}


def canonical_name(mnemonic: str) -> str | None:
    """Map a raw mnemonic (e.g. 'RHOZ', 'GR:1', 'dt_edit') to a canonical family or None."""
    m = mnemonic.upper().strip()
    if m in _LOOKUP:
        return _LOOKUP[m]
    # strip lasio duplicate suffix ':1' and common tool/edit suffixes
    base = m.split(":")[0]
    for sep in ("_", "."):
        base = base.split(sep)[0] if base.split(sep)[0] in _LOOKUP else base
    return _LOOKUP.get(base)


def read_las(path: str | Path):
    """Read a LAS file tolerantly (encoding detection, wrapped files, bad headers)."""
    import lasio

    try:
        return lasio.read(str(path), ignore_header_errors=True)
    except Exception:
        return lasio.read(str(path), ignore_header_errors=True, encoding="latin-1")


def well_name(las, fallback: str = "UNKNOWN") -> str:
    for key in ("WELL", "UWI", "API"):
        try:
            val = str(las.well[key].value).strip()
        except KeyError:
            continue
        if val and val.lower() not in ("none", "nan", "unknown"):
            return val
    return fallback


def depth_in_metres(las) -> np.ndarray:
    """Return the index as metres (converts from feet when the unit says so)."""
    idx = np.asarray(las.index, dtype=float)
    unit = (las.curves[0].unit or "").upper().strip()
    if unit in ("F", "FT", "FEET", "FOOT"):
        return idx * 0.3048
    return idx


def las_to_frame(path: str | Path, canonical: bool = True, keep_unknown: bool = True, fix: bool = True) -> pd.DataFrame:
    """LAS -> tidy DataFrame with WELL, DEPTH (m) and curve columns.

    canonical=True renames known curves to their family (GR, RHOB, ...). When several
    raw curves map to one family, the one with most valid samples wins and the rest
    keep their raw names. fix=True also converts obviously wrong units (see fix_units);
    the conversions applied are listed in df.attrs["unit_fixes"].
    """
    las = read_las(path)
    df = las.df().reset_index(drop=True)
    df = df.apply(pd.to_numeric, errors="coerce")
    null = getattr(las.well, "NULL", None)
    if null is not None and null.value not in (None, ""):
        try:
            df = df.replace(float(null.value), np.nan)
        except (TypeError, ValueError):
            pass
    df = df.replace([-999.25, -9999.0, -999.0, 9999.0], np.nan)

    if canonical:
        groups: dict[str, list[str]] = {}
        for col in df.columns:
            fam = canonical_name(col)
            if fam:
                groups.setdefault(fam, []).append(col)
        rename = {}
        for fam, cols in groups.items():
            best = max(cols, key=lambda c: df[c].notna().sum())
            if fam not in df.columns or best == fam:
                rename[best] = fam
        df = df.rename(columns=rename)
        renamed = {k: v for k, v in rename.items() if k != v}
        if not keep_unknown:
            df = df[[c for c in df.columns if c in CURVE_ALIASES]]

    fixes = fix_units(df) if canonical and fix else []
    df.insert(0, "DEPTH", depth_in_metres(las))
    df.insert(0, "WELL", well_name(las, Path(path).stem))
    df.attrs["unit_fixes"] = fixes
    df.attrs["renamed"] = renamed if canonical else {}
    return df


def fix_units(df: pd.DataFrame) -> list[str]:
    """Convert canonical curves that are clearly in the wrong unit, in place. Returns what was changed.

    Detection is by median value, which is unambiguous for these cases:
    NPHI in percent, RHOB in kg/m3, DTC/DTS in us/m, CALI/BS in mm or cm.
    """
    rules = [  # (family, test on median, factor, description)
        ("NPHI", lambda m: m > 1.5, 0.01, "percent -> v/v"),
        ("RHOB", lambda m: m > 100, 0.001, "kg/m3 -> g/cm3"),
        ("DRHO", lambda m: abs(m) > 5, 0.001, "kg/m3 -> g/cm3"),
        ("DTC", lambda m: m > 260, 0.3048, "us/m -> us/ft"),
        ("DTS", lambda m: m > 700, 0.3048, "us/m -> us/ft"),
        ("CALI", lambda m: m > 100, 1 / 25.4, "mm -> in"),
        ("BS", lambda m: m > 100, 1 / 25.4, "mm -> in"),
    ]
    done = []
    for fam, test, factor, text in rules:
        if fam in df.columns and df[fam].notna().any() and test(float(df[fam].median())):
            df[fam] = df[fam] * factor
            done.append(f"{fam}: {text}")
    return done


# ---------------------------------------------------------------- petrophysics

def vshale_gr(gr, gr_clean: float | None = None, gr_shale: float | None = None, method: str = "linear"):
    """Shale volume from gamma ray, clipped to 0..1. Defaults: P5 and P95 of the input as clean/shale lines.

    The defaults depend on what is passed in: in an app, compute the clean and shale lines once per well
    or zone and pass them explicitly, or Vsh changes whenever the user moves a depth slider.
    """
    gr = np.asarray(gr, dtype=float)
    if gr_clean is None:
        gr_clean = np.nanpercentile(gr, 5)
    if gr_shale is None:
        gr_shale = np.nanpercentile(gr, 95)
    igr = np.clip((gr - gr_clean) / max(gr_shale - gr_clean, 1e-9), 0, 1)
    if method == "larionov_tertiary":
        return np.clip(0.083 * (2 ** (3.7 * igr) - 1), 0, 1)
    if method == "larionov_old":
        return np.clip(0.33 * (2 ** (2 * igr) - 1), 0, 1)
    if method == "steiber":
        return np.clip(igr / (3 - 2 * igr), 0, 1)
    return igr


def porosity_density(rhob, rho_matrix: float = 2.65, rho_fluid: float = 1.0):
    """Density porosity (v/v), clipped to 0..0.6. Matrix 2.65 sandstone, 2.71 limestone, 2.87 dolomite."""
    rhob = np.asarray(rhob, dtype=float)
    return np.clip((rho_matrix - rhob) / (rho_matrix - rho_fluid), 0, 0.6)


def porosity_density_neutron(rhob, nphi, rho_matrix: float = 2.65, rho_fluid: float = 1.0, gas: bool = False):
    """Total porosity from density and neutron (NPHI in v/v on the same matrix as rho_matrix).

    Arithmetic mean in liquid-filled rock; root-mean-square when gas=True (corrects the gas effect).
    """
    phid = (rho_matrix - np.asarray(rhob, dtype=float)) / (rho_matrix - rho_fluid)
    nphi = np.asarray(nphi, dtype=float)
    phit = np.sqrt((phid ** 2 + nphi ** 2) / 2) if gas else (phid + nphi) / 2
    return np.clip(phit, 0, 0.6)


def porosity_effective(phit, vsh, phi_shale: float = 0.1):
    """Effective porosity from total porosity with a simple shale correction."""
    return np.clip(np.asarray(phit) - np.asarray(vsh) * phi_shale, 0, 0.6)


def sw_archie(rt, phi, rw: float = 0.05, a: float = 1.0, m: float = 2.0, n: float = 2.0):
    """Archie water saturation (v/v), clipped to 0..1 (raw values above 1 mean wrong Rw or porosity).

    Clean formations only; overestimates Sw in shaly sands.
    """
    rt = np.asarray(rt, dtype=float)
    phi = np.asarray(phi, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sw = ((a * rw) / (np.power(phi, m) * rt)) ** (1.0 / n)
    return np.clip(sw, 0, 1)


def net_pay_flags(df: pd.DataFrame, vsh_max: float = 0.4, phi_min: float = 0.1, sw_max: float = 0.6,
                  depth: str = "DEPTH", vsh: str = "VSH", phi: str = "PHIE", sw: str = "SW"):
    """Boolean Series (reservoir, pay) for the cutoffs, and a table of pay intervals (top, base, thickness).

    Use the pay Series as log_plot(flag=..., flag_color="#2E7D32") and show the table under the plot.
    """
    res = (df[vsh] <= vsh_max) & (df[phi] >= phi_min)
    pay = res & (df[sw] <= sw_max)
    runs = pay.ne(pay.shift()).cumsum()
    spans = df.loc[pay, depth].groupby(runs[pay]).agg(top_m="first", base_m="last").reset_index(drop=True)
    spans["thickness_m"] = spans["base_m"] - spans["top_m"]
    return res, pay, spans.round(2)


def net_pay_summary(df: pd.DataFrame, vsh_max: float = 0.4, phi_min: float = 0.1, sw_max: float = 0.6,
                    depth: str = "DEPTH", vsh: str = "VSH", phi: str = "PHIE", sw: str = "SW") -> dict:
    """Gross, net reservoir and net pay thickness with averages, using sample spacing."""
    d = df[depth].to_numpy(dtype=float)
    step = np.gradient(d) if len(d) > 1 else np.zeros_like(d)
    # Gross is the interval with a shale-volume estimate. Requiring Sw too would drop the shales
    # (Sw is undefined at near-zero porosity) and understate gross, inflating net-to-gross.
    valid = df[vsh].notna().to_numpy()
    res = valid & (df[vsh].to_numpy() <= vsh_max) & (df[phi].to_numpy() >= phi_min)
    pay = res & (df[sw].to_numpy() <= sw_max)
    gross = float(step[valid].sum())

    def avg(col, mask):
        return float(np.average(df[col].to_numpy()[mask], weights=step[mask])) if mask.any() and step[mask].sum() > 0 else None

    return {
        "gross_m": round(gross, 2),
        "net_reservoir_m": round(float(step[res].sum()), 2),
        "net_pay_m": round(float(step[pay].sum()), 2),
        "net_to_gross": round(float(step[res].sum()) / gross, 3) if gross else None,
        "avg_phie_pay": avg(phi, pay),
        "avg_sw_pay": avg(sw, pay),
        "avg_vsh_reservoir": avg(vsh, res),
    }


def flag_bad_hole(df: pd.DataFrame, washout_in: float = 2.0, drho_max: float = 0.15) -> pd.Series:
    """True where density/neutron are unreliable: caliper far above bit size or large DRHO."""
    bad = pd.Series(False, index=df.index)
    if "CALI" in df and "BS" in df:
        bad |= (df["CALI"] - df["BS"]) > washout_in
    if "DRHO" in df:
        bad |= df["DRHO"].abs() > drho_max
    return bad


def compact_json(obj: dict) -> str:
    """JSON with one top-level key per line and one line per item of any list of dicts.

    Much shorter than indent=1 for curve tables, still easy to read and valid JSON.
    """
    import json

    parts = []
    for key, val in obj.items():
        if isinstance(val, list) and val and all(isinstance(v, dict) for v in val):
            rows = ",\n  ".join(json.dumps(v, default=str) for v in val)
            parts.append(f'{json.dumps(key)}: [\n  {rows}\n ]')
        else:
            parts.append(f"{json.dumps(key)}: {json.dumps(val, default=str)}")
    return "{\n " + ",\n ".join(parts) + "\n}"


# ------------------------------------------------------------------ lithology

# Lithology codes used by the FORCE 2020 dataset (curve FORCE_2020_LITHOFACIES_LITHOLOGY),
# with conventional display colours.
FORCE_LITHOLOGY: dict[int, tuple[str, str]] = {
    30000: ("Sandstone", "#F4E04D"), 65030: ("Sandstone/Shale", "#C2B280"), 65000: ("Shale", "#7A8B5A"),
    80000: ("Marl", "#9AD0C2"), 74000: ("Dolomite", "#B58BD6"), 70000: ("Limestone", "#5DA9E9"),
    70032: ("Chalk", "#BEE3F8"), 88000: ("Halite", "#F7A6C1"), 86000: ("Anhydrite", "#E46FA0"),
    99000: ("Tuff", "#F08A4B"), 90000: ("Coal", "#2B2B2B"), 93000: ("Basement", "#8C5A3C"),
}


# ------------------------------------------------------------------ FactPages

def read_factpages(path: str | Path) -> pd.DataFrame:
    """Read one cached FactPages CSV and clean it.

    Handles the BOM, strips padded strings, and parses dd.mm.yyyy date columns.
    """
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            s = df[col].astype("string").str.strip()
            df[col] = s.mask(s == "")
            if "date" in col.lower():
                parsed = pd.to_datetime(df[col], format="%d.%m.%Y", errors="coerce")
                if parsed.notna().sum() >= 0.5 * df[col].notna().sum():
                    df[col] = parsed
    return df


def factpages_duckdb(folder: str | Path = "data/factpages"):
    """In-memory DuckDB connection with every cached FactPages CSV registered as a table."""
    import duckdb

    con = duckdb.connect()
    for csv in sorted(Path(folder).glob("*.csv")):
        con.register(f"_{csv.stem}", read_factpages(csv))
        con.execute(f'CREATE TABLE "{csv.stem}" AS SELECT * FROM "_{csv.stem}"')
        con.unregister(f"_{csv.stem}")
    return con


def utm_to_latlon(x, y, epsg: int = 23031):
    """Projected coordinates to WGS84 lat/lon. Default EPSG:23031 = ED50 / UTM zone 31N (North Sea)."""
    from pyproj import Transformer

    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(np.asarray(x), np.asarray(y))
    return lat, lon


# -------------------------------------------------------------------- seismic

def load_cube(path_without_ext: str | Path):
    """Open a cube written by segy_to_npy.py: returns (memory-mapped array, metadata dict)."""
    import json

    p = Path(path_without_ext)
    return np.load(p.with_suffix(".npy"), mmap_mode="r"), json.loads(p.with_suffix(".json").read_text())


def xy_to_ilxl(meta: dict, x, y):
    """World coordinates -> fractional (inline, crossline) using the cube's ilxl_to_xy affine."""
    m = np.vstack([np.asarray(meta["ilxl_to_xy"]).T, [0, 0, 1]])
    ij = np.linalg.inv(m) @ np.vstack([np.atleast_1d(x), np.atleast_1d(y), np.ones(np.size(x))])
    return ij[0], ij[1]


def grid_horizon(meta: dict, x, y, z) -> np.ndarray:
    """Scattered horizon points (x, y, z) -> 2D array (inlines, crosslines) on the cube grid, NaN where empty."""
    il, xl = xy_to_ilxl(meta, x, y)
    ilines, xlines = np.asarray(meta["ilines"]), np.asarray(meta["xlines"])
    i = np.round((il - ilines[0]) / (ilines[1] - ilines[0])).astype(int)
    j = np.round((xl - xlines[0]) / (xlines[1] - xlines[0])).astype(int)
    ok = (i >= 0) & (i < len(ilines)) & (j >= 0) & (j < len(xlines))
    grid = np.full((len(ilines), len(xlines)), np.nan, dtype=np.float32)
    grid[i[ok], j[ok]] = np.asarray(z)[ok]
    return grid


def amplitude_along_horizon(cube, meta: dict, horizon: np.ndarray, window: int = 0, mode: str = "value") -> np.ndarray:
    """Extract amplitude on a gridded horizon. window = half-width in samples; mode: value | rms | max_abs."""
    samples = np.asarray(meta["samples"])
    k = np.round((horizon - samples[0]) / (samples[1] - samples[0]))
    out = np.full(horizon.shape, np.nan, dtype=np.float32)
    ok = np.isfinite(k) & (k >= window) & (k < len(samples) - window)
    ii, jj = np.nonzero(ok)
    kk = k[ok].astype(int)
    if window == 0:
        out[ii, jj] = cube[ii, jj, kk]
        return out
    stack = np.stack([cube[ii, jj, kk + d] for d in range(-window, window + 1)], axis=1)
    out[ii, jj] = np.sqrt((stack ** 2).mean(axis=1)) if mode == "rms" else np.abs(stack).max(axis=1)
    return out
