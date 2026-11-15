"""<App name>: <one line on what it does and for whom>.

Well-log starter: pick a well and an interval, see the logs, get a quick-look net pay estimate.

Run:  streamlit run app.py
Needs subsurface_utils.py and subsurface_plots.py (copied from the skill's scripts/) next to this file,
and data prepared with:  python las_to_parquet.py <folder with LAS files> data/wells.parquet
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import subsurface_plots as sp
import subsurface_utils as su

DATA = Path(__file__).parent / "data"
WELLS = DATA / "wells.parquet"
NOTES = DATA / "wells.notes.json"       # written by las_to_parquet.py: renamed curves, converted units

st.set_page_config(page_title="<App name>", layout="wide")

# Fail with instructions, not a traceback, when data has not been prepared.
if not WELLS.exists():
    st.error(f"`{WELLS.name}` not found. Prepare it with:\n\n"
             "`python las_to_parquet.py <folder with LAS files> data/wells.parquet`")
    st.stop()


@st.cache_data
def well_names() -> list[str]:
    return sorted(pd.read_parquet(WELLS, columns=["WELL"])["WELL"].astype(str).unique())


@st.cache_data(show_spinner="Loading well...")
def load_well(name: str) -> pd.DataFrame:
    df = pd.read_parquet(WELLS, filters=[("WELL", "==", name)])
    return df.dropna(axis=1, how="all").reset_index(drop=True)


@st.cache_data
def conversion_notes() -> dict:
    return json.loads(NOTES.read_text()) if NOTES.exists() else {}


# ---------------------------------------------------------------- sidebar: what to look at
st.sidebar.title("<App name>")
well = st.sidebar.selectbox("Well", well_names())
df = load_well(well)
zmin, zmax = float(df["DEPTH"].min()), float(df["DEPTH"].max())
# Keys include the well so the controls reset when the selection changes.
top, base = st.sidebar.slider("Depth interval (m MD)", zmin, zmax, (zmin, zmax), key=f"interval_{well}")
sel = df[df["DEPTH"].between(top, base)].reset_index(drop=True)

# GR clean/shale lines come from the whole well, not the selected interval, so they stay put when the slider moves.
gr = df["GR"].dropna() if "GR" in df else pd.Series([20.0, 120.0])
with st.sidebar.expander("Quick-look parameters"):
    gr_clean = st.number_input("GR clean (gAPI)", value=float(round(gr.quantile(0.05))), key=f"grc_{well}")
    gr_shale = st.number_input("GR shale (gAPI)", value=float(round(gr.quantile(0.95))), key=f"grs_{well}")
    rho_ma = st.number_input("Matrix density (g/cm3)", value=2.65, step=0.01)
    rho_fl = st.number_input("Fluid density (g/cm3)", value=1.0, step=0.01)
    rw = st.number_input("Rw (ohm.m)", value=0.05, step=0.005, format="%.3f")
with st.sidebar.expander("Net pay cutoffs"):
    cut_vsh = st.slider("Vshale max", 0.0, 1.0, 0.4, 0.05)
    cut_phi = st.slider("Porosity min", 0.0, 0.35, 0.10, 0.01)
    cut_sw = st.slider("Sw max", 0.0, 1.0, 0.6, 0.05)

# ---------------------------------------------------------------- derived results
sel["BAD_HOLE"] = su.flag_bad_hole(sel)
have = set(sel.columns)
if "GR" in have:
    sel["VSH"] = su.vshale_gr(sel["GR"], gr_clean, gr_shale)
if "RHOB" in have:
    sel["PHIT"] = np.where(sel["BAD_HOLE"], np.nan, su.porosity_density(sel["RHOB"], rho_ma, rho_fl))
    if "VSH" in sel:
        sel["PHIE"] = su.porosity_effective(sel["PHIT"], sel["VSH"])
if {"RDEP", "PHIE"} <= set(sel.columns):
    sel["SW"] = su.sw_archie(sel["RDEP"], sel["PHIE"].where(sel["PHIE"] > 0.02), rw)
can_pay = {"VSH", "PHIE", "SW"} <= set(sel.columns)

# ---------------------------------------------------------------- page
st.title(well)
c1, c2, c3 = st.columns(3)
c1.metric("Interval, m MD", f"{top:.0f} - {base:.0f}")
c2.metric("Curves", int(sel.drop(columns=["WELL", "DEPTH"]).notna().any().sum()))
c3.metric("Bad hole, %", f"{100 * sel['BAD_HOLE'].mean():.1f}")

tab_logs, tab_pay, tab_xplot, tab_data = st.tabs(["Logs", "Net pay", "Crossplot", "Data notes"])

with tab_logs:
    st.plotly_chart(sp.log_plot(sel, flag=sel["BAD_HOLE"]), width="stretch")
    st.caption("Red shading: caliper far above bit size or large density correction (density and neutron unreliable).")

with tab_pay:
    if not can_pay:
        st.warning("Net pay needs gamma ray, density and deep resistivity in this interval.")
    else:
        if (top, base) == (zmin, zmax):
            st.info("These figures cover the whole logged interval, which mixes unrelated rocks. "
                    "Narrow the depth interval to one reservoir zone and set the parameters for it.")
        res, pay, intervals = su.net_pay_flags(sel, cut_vsh, cut_phi, cut_sw)
        s = su.net_pay_summary(sel, cut_vsh, cut_phi, cut_sw)
        m = st.columns(5)
        m[0].metric("Gross, m", f"{s['gross_m']:.1f}")
        m[1].metric("Net reservoir, m", f"{s['net_reservoir_m']:.1f}")
        m[2].metric("Net pay, m", f"{s['net_pay_m']:.1f}")
        m[3].metric("Porosity in pay", "-" if s["avg_phie_pay"] is None else f"{s['avg_phie_pay']:.3f}")
        m[4].metric("Sw in pay", "-" if s["avg_sw_pay"] is None else f"{s['avg_sw_pay']:.3f}")
        st.plotly_chart(sp.log_plot(sel, tracks=[["GR"], ["RDEP"], ["RHOB", "NPHI"], ["VSH"], ["PHIE"], ["SW"]],
                                    flag=pay.fillna(False), flag_color="#2E7D32"), width="stretch")
        st.dataframe(intervals[intervals["thickness_m"] >= 0.5], width="stretch", hide_index=True)
        st.caption("Green shading: samples passing all three cutoffs. Quick-look only: density porosity, one Rw, "
                   "clean-sand Archie, no environmental corrections, measured-depth thickness.")

with tab_xplot:
    if {"NPHI", "RHOB"} <= have:
        st.plotly_chart(sp.crossplot(sel[~sel["BAD_HOLE"]], "NPHI", "RHOB", "GR" if "GR" in have else None, reverse_y=True),
                        width="stretch")
    else:
        st.info("This well has no neutron-density pair.")

with tab_data:
    note = conversion_notes().get(well, {})
    st.markdown("**Curves renamed to standard names**")
    st.write(note.get("renamed") or "None.")
    st.markdown("**Units converted on load**")
    st.write(note.get("unit_fixes") or "None.")

st.sidebar.divider()
st.sidebar.caption("Data: <source and licence>.")
