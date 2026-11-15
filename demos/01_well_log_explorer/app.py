"""Well Log Explorer: browse, QC and quick-look 118 North Sea wells (FORCE 2020 open dataset).

Run from the repo root:  streamlit run demos/01_well_log_explorer/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "subsurface-app-builder" / "scripts"))
import subsurface_plots as sp  # noqa: E402
import subsurface_utils as su  # noqa: E402

DATA = ROOT / "data" / "force2020"
WELLS = DATA / "wells.parquet"
LITH = "FORCE_2020_LITHOFACIES_LITHOLOGY"

st.set_page_config(page_title="Well Log Explorer", layout="wide")

if not WELLS.exists():
    st.error("Well data not found. Run:\n\n"
             "`python scripts/download_sample_data.py`\n\n"
             "`python skills/subsurface-app-builder/scripts/las_to_parquet.py data/force2020/las data/force2020/wells.parquet`")
    st.stop()


@st.cache_data(show_spinner="Indexing wells...")
def well_index() -> pd.DataFrame:
    cols = ["WELL", "DEPTH", "X_LOC", "Y_LOC", "GR", "RHOB", "NPHI", "RDEP", "DTC", "DTS", "PEF", LITH]
    df = pd.read_parquet(WELLS, columns=cols)
    g = df.groupby("WELL", observed=True)
    idx = g.agg(x=("X_LOC", "median"), y=("Y_LOC", "median"), top=("DEPTH", "min"), base=("DEPTH", "max")).reset_index()
    for c in ["GR", "RHOB", "NPHI", "RDEP", "DTC", "DTS", "PEF", LITH]:
        idx[f"has_{c}"] = g[c].apply(lambda s: s.notna().mean()).to_numpy()
    idx["WELL"] = idx["WELL"].astype(str)
    ok = idx["x"].notna()
    idx.loc[ok, "lat"], idx.loc[ok, "lon"] = su.utm_to_latlon(idx.loc[ok, "x"], idx.loc[ok, "y"])
    return idx.sort_values("WELL").reset_index(drop=True)


@st.cache_data(show_spinner="Loading well...")
def load_well(name: str) -> pd.DataFrame:
    df = pd.read_parquet(WELLS, filters=[("WELL", "==", name)])
    return df.dropna(axis=1, how="all").reset_index(drop=True)


@st.cache_data
def group_tops() -> pd.DataFrame:
    f = DATA / "lithostrat_groups.xlsx"
    if not f.exists():
        return pd.DataFrame(columns=["Well identifier", "Surface", "MD"])
    return pd.read_excel(f)


def petrophysics(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    out = df.copy()
    out["BAD_HOLE"] = su.flag_bad_hole(out, p["washout"], p["drho"])
    if "GR" in out:
        out["VSH"] = su.vshale_gr(out["GR"], p["gr_clean"], p["gr_shale"], p["vsh_method"])
    if "RHOB" in out:
        phit = su.porosity_density(out["RHOB"], p["rho_ma"], p["rho_fl"])
        out["PHIT"] = np.where(out["BAD_HOLE"], np.nan, phit)
        if "VSH" in out:
            out["PHIE"] = su.porosity_effective(out["PHIT"], out["VSH"], p["phi_sh"])
    if "RDEP" in out and "PHIE" in out:
        out["SW"] = su.sw_archie(out["RDEP"], out["PHIE"].where(out["PHIE"] > 0.02), p["rw"], 1.0, p["m"], p["n"])
    return out


idx = well_index()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("Well Log Explorer")
st.sidebar.caption("118 wells, Norwegian North Sea. FORCE 2020 open dataset.")
default = next((i for i, w in enumerate(idx["WELL"]) if w.startswith("15/9-13")), 0)
well = st.sidebar.selectbox("Well", idx["WELL"], index=default)
df = load_well(well)
row = idx[idx["WELL"] == well].iloc[0]

valid = df.drop(columns=["WELL"]).set_index("DEPTH").drop(columns=[c for c in ("X_LOC", "Y_LOC", "Z_LOC", "DEPTH_MD") if c in df], errors="ignore")
logged = valid.dropna(how="all").index
zmin, zmax = float(logged.min()), float(logged.max())
tops_all = group_tops()
tops_w = tops_all[tops_all["Well identifier"] == well.split(" ")[0]].dropna(subset=["MD"]).sort_values("MD")
zones = {"Whole well": (zmin, zmax)}
for i, r in enumerate(tops_w.itertuples()):
    base = float(tops_w["MD"].iloc[i + 1]) if i + 1 < len(tops_w) else zmax
    if zmin <= r.MD < base <= zmax:
        zones[str(r.Surface).replace(" Top", "")] = (float(r.MD), base)
zone = st.sidebar.selectbox("Zone (lithostratigraphic group)", list(zones), key=f"zone_{well}",
                            help="Quick-look results only mean something over one reservoir zone, not the whole well.")
interval = st.sidebar.slider("Depth interval (m MD)", zmin, zmax, zones[zone], step=1.0, key=f"int_{well}_{zone}")
sel = df[(df["DEPTH"] >= interval[0]) & (df["DEPTH"] <= interval[1])].reset_index(drop=True)

with st.sidebar.expander("Quick-look parameters", expanded=False):
    gr = sel["GR"].dropna() if "GR" in sel else pd.Series([0.0, 150.0])
    p = dict(
        vsh_method=st.selectbox("Vshale method", ["linear", "larionov_old", "larionov_tertiary", "steiber"]),
        gr_clean=st.number_input("GR clean (gAPI)", value=float(np.round(gr.quantile(0.05), 0))),
        gr_shale=st.number_input("GR shale (gAPI)", value=float(np.round(gr.quantile(0.95), 0))),
        rho_ma=st.number_input("Matrix density (g/cm3)", value=2.65, step=0.01),
        rho_fl=st.number_input("Fluid density (g/cm3)", value=1.0, step=0.01),
        phi_sh=st.number_input("Shale porosity (v/v)", value=0.10, step=0.01),
        rw=st.number_input("Rw (ohm.m)", value=0.05, step=0.005, format="%.3f"),
        m=st.number_input("Archie m", value=2.0, step=0.1),
        n=st.number_input("Archie n", value=2.0, step=0.1),
        washout=st.number_input("Washout: CALI - BS above (in)", value=2.0, step=0.5),
        drho=st.number_input("Bad density: |DRHO| above", value=0.15, step=0.01),
    )
with st.sidebar.expander("Net pay cutoffs", expanded=False):
    cut_vsh = st.slider("Vshale max", 0.0, 1.0, 0.4, 0.05)
    cut_phi = st.slider("Porosity min", 0.0, 0.35, 0.10, 0.01)
    cut_sw = st.slider("Sw max", 0.0, 1.0, 0.6, 0.05)

calc = petrophysics(sel, p)
tops = {str(r.Surface).replace(" Top", ""): float(r.MD) for r in tops_w.itertuples()
        if pd.notna(r.MD) and interval[0] <= r.MD <= interval[1]}

# ------------------------------------------------------------------ header
st.title(well)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Logged interval", f"{zmin:.0f} - {zmax:.0f} m")
c2.metric("Curves", int(valid.notna().any().sum()))
c3.metric("Bad-hole samples", f"{100 * calc['BAD_HOLE'].mean():.1f} %")
c4.metric("Group tops", len(tops_w))
c5.metric("Lithology labels", "yes" if LITH in df and df[LITH].notna().any() else "no")

tab_logs, tab_petro, tab_xplot, tab_qc, tab_map = st.tabs(["Logs", "Quick-look", "Crossplot", "QC", "Map"])

with tab_logs:
    show_flag = st.checkbox("Shade bad-hole intervals", value=True)
    fig = sp.log_plot(calc, tops=tops, flag=calc["BAD_HOLE"] if show_flag else None,
                      lithology=(LITH, su.FORCE_LITHOLOGY) if LITH in calc else None)
    st.plotly_chart(fig, width="stretch")
    st.caption("Red shading: caliper far above bit size or large density correction, so density and neutron are unreliable. "
               "Lithology strip: interpreted labels from the FORCE 2020 dataset.")

with tab_petro:
    need = {"VSH", "PHIE", "SW"}
    if zone == "Whole well" and interval == (zmin, zmax):
        st.info("These figures cover the whole well, which mixes unrelated formations. Pick a zone in the sidebar "
                "(for example a reservoir group) and set the GR lines and Rw for it.")
    if not need <= set(calc.columns):
        st.warning(f"This interval lacks the curves needed (GR, RHOB, deep resistivity). Missing: {sorted(need - set(calc.columns))}")
    else:
        s = su.net_pay_summary(calc, cut_vsh, cut_phi, cut_sw)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Gross", f"{s['gross_m']:.1f} m")
        m2.metric("Net reservoir", f"{s['net_reservoir_m']:.1f} m")
        m3.metric("Net pay", f"{s['net_pay_m']:.1f} m")
        m4.metric("Avg porosity in pay", "-" if s["avg_phie_pay"] is None else f"{s['avg_phie_pay']:.3f}")
        m5.metric("Avg Sw in pay", "-" if s["avg_sw_pay"] is None else f"{s['avg_sw_pay']:.3f}")
        pay = (calc["VSH"] <= cut_vsh) & (calc["PHIE"] >= cut_phi) & (calc["SW"] <= cut_sw)
        fig = sp.log_plot(calc, tracks=[["GR"], ["RDEP", "RMED"], ["RHOB", "NPHI"], ["VSH"], ["PHIE", "PHIT"], ["SW"]],
                          tops=tops, flag=pay.fillna(False))
        st.plotly_chart(fig, width="stretch")
        st.caption("Red shading here marks samples passing all three cutoffs (net pay). Quick-look only: no environmental "
                   "corrections, one Rw for the whole interval, clean-sand Archie, measured-depth thickness. "
                   "Narrow the depth interval to one reservoir and set GR lines and Rw for that zone.")
        st.download_button("Download computed curves (CSV)",
                           calc[["DEPTH", "VSH", "PHIT", "PHIE", "SW", "BAD_HOLE"]].to_csv(index=False),
                           file_name=f"{well.split(' ')[0].replace('/', '_')}_quicklook.csv")

with tab_xplot:
    numeric = [c for c in calc.columns if c not in ("WELL", "BAD_HOLE") and pd.api.types.is_numeric_dtype(calc[c])]
    a, b, c = st.columns(3)
    x = a.selectbox("X", numeric, index=numeric.index("NPHI") if "NPHI" in numeric else 0)
    y = b.selectbox("Y", numeric, index=numeric.index("RHOB") if "RHOB" in numeric else 0)
    col = c.selectbox("Colour", numeric, index=numeric.index("GR") if "GR" in numeric else 0)
    clean = calc[~calc["BAD_HOLE"]] if st.checkbox("Exclude bad-hole samples", value=True) else calc
    st.plotly_chart(sp.crossplot(clean, x, y, col, log_x=x.startswith("R") and x != "RHOB", reverse_y=(y == "RHOB")),
                    width="stretch")

with tab_qc:
    rows = []
    for cname in valid.columns:
        s = sel[cname] if cname in sel else pd.Series(dtype=float)
        v = s.dropna()
        fam = su.canonical_name(cname)
        flags = []
        if len(v) and fam in su.CURVE_RANGES:
            lo, hi = su.CURVE_RANGES[fam]
            out = ((v < lo) | (v > hi)).mean()
            if out > 0.02:
                flags.append(f"{out:.0%} outside {lo}-{hi}")
        if len(v) and v.nunique() == 1:
            flags.append("constant")
        rows.append({"curve": cname, "family": fam or "", "coverage %": round(100 * s.notna().mean(), 1),
                     "min": v.min() if len(v) else None, "median": v.median() if len(v) else None,
                     "max": v.max() if len(v) else None, "flags": "; ".join(flags)})
    qc = pd.DataFrame(rows).sort_values("coverage %", ascending=False)
    st.dataframe(qc, width="stretch", hide_index=True,
                 column_config={"coverage %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%")})
    st.caption("Coverage and range checks over the selected interval. Ranges are plausibility limits, not hard rules.")

with tab_map:
    m = idx.dropna(subset=["lat"])
    fig = go.Figure(go.Scattermap(
        lat=m["lat"], lon=m["lon"], text=m["WELL"], mode="markers",
        marker=dict(size=np.where(m["WELL"] == well, 16, 8), color=np.where(m["WELL"] == well, "#E53935", "#1565C0")),
        hovertemplate="%{text}<extra></extra>"))
    fig.update_layout(map=dict(style="carto-positron", center=dict(lat=float(m["lat"].mean()), lon=float(m["lon"].mean())), zoom=4.6),
                      height=650, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, width="stretch")
    st.caption("Well positions from the X_LOC/Y_LOC curves (ED50 / UTM 31N). Selected well in red. Base map needs internet.")

st.sidebar.divider()
st.sidebar.caption("Data: Bormann et al. (2020), FORCE 2020 well log and lithofacies dataset, CC-BY-4.0 / NLOD 2.0.")
