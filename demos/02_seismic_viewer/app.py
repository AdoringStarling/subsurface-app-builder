"""Seismic Viewer: sections, time slices, attributes and a horizon on the Volve sub-cube.

Run from the repo root:  streamlit run demos/02_seismic_viewer/app.py
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
import seismic_attributes as sa  # noqa: E402
import subsurface_plots as sp  # noqa: E402
import subsurface_utils as su  # noqa: E402

DATA = ROOT / "data" / "volve"
CUBE = DATA / "volve_sub3d"

st.set_page_config(page_title="Seismic Viewer", layout="wide")

if not CUBE.with_suffix(".npy").exists():
    st.error("Seismic cube not found. Run:\n\n"
             "`python scripts/download_sample_data.py`\n\n"
             "`python skills/subsurface-app-builder/scripts/segy_to_npy.py "
             "data/volve/volve10r12-full-twt-sub3d.sgy data/volve/volve_sub3d`")
    st.stop()

ATTRS = {
    "Amplitude": dict(scale="RdBu", help="Migrated amplitude. Red and blue are opposite polarities."),
    "Envelope": dict(scale="Viridis", help="Reflection strength, independent of polarity. Bright = strong contrast."),
    "RMS amplitude": dict(scale="Viridis", help="Root-mean-square amplitude in a sliding 9-sample window."),
    "Instantaneous phase": dict(scale="Phase", help="Phase angle. Emphasises reflector continuity, also where amplitudes are weak."),
    "Discontinuity": dict(scale=sp.DISCONTINUITY_SCALE, help="1 - semblance over 3x3 traces. Dark lineaments are faults and edges."),
}


@st.cache_resource
def cube_and_meta():
    return su.load_cube(CUBE)


@st.cache_data(show_spinner="Computing attribute...")
def attribute(name: str) -> np.ndarray:
    cube, _ = cube_and_meta()
    c = np.asarray(cube)
    if name == "Envelope":
        return sa.envelope(c)
    if name == "RMS amplitude":
        return sa.rms_amplitude(c)
    if name == "Instantaneous phase":
        return sa.instantaneous_phase(c)
    if name == "Discontinuity":
        return (1 - sa.semblance(c)).astype(np.float32)
    return c


@st.cache_data
def horizon_grid() -> np.ndarray | None:
    f = DATA / "hor_twt_hugin_fm_top.dat"
    if not f.exists():
        return None
    _, meta = cube_and_meta()
    h = pd.read_csv(f, sep=r"\s+", names=["x", "y", "twt"])
    return su.grid_horizon(meta, h["x"], h["y"], h["twt"])


@st.cache_data
def well_path() -> pd.DataFrame | None:
    f = DATA / "well_f12_deviation.asc"
    if not f.exists():
        return None
    names = ["MD", "X", "Y", "Z", "TVD", "DX", "DY", "AZIM_TN", "INCL", "DLS", "AZIM_GN"]
    w = pd.read_csv(f, sep=r"\s+", comment="#", header=None, names=names)
    w = w.apply(pd.to_numeric, errors="coerce").dropna(subset=["MD", "X", "Y"])
    _, meta = cube_and_meta()
    w["il"], w["xl"] = su.xy_to_ilxl(meta, w["X"], w["Y"])
    return w


cube, meta = cube_and_meta()
ilines, xlines, samples = np.array(meta["ilines"]), np.array(meta["xlines"]), np.array(meta["samples"])
hor = horizon_grid()
well = well_path()

# ------------------------------------------------------------------ sidebar
st.sidebar.title("Seismic Viewer")
st.sidebar.caption(f"Volve sub-cube: {len(ilines)} inlines x {len(xlines)} crosslines x {len(samples)} samples, "
                   f"{meta['sample_interval']:.0f} ms.")
attr = st.sidebar.radio("Attribute", list(ATTRS), help="Computed once for the whole cube, then cached.")
st.sidebar.caption(ATTRS[attr]["help"])
data = attribute(attr)
dt = float(meta["sample_interval"])
t0, t1 = st.sidebar.slider("Time window (ms TWT)", float(samples[0]), float(samples[-1]), (2000.0, 3200.0), step=dt)
k0, k1 = int(np.searchsorted(samples, t0)), int(np.searchsorted(samples, t1)) + 1
gain = st.sidebar.slider("Display gain", 0.25, 4.0, 1.0, 0.25, help="Higher gain clips sooner and brightens weak events.")
show_hor = st.sidebar.checkbox("Show Hugin Fm top horizon", value=hor is not None, disabled=hor is None)

if attr == "Amplitude":
    clip = meta["clip_p99"] / gain
elif attr == "Instantaneous phase":
    clip = 180.0
else:
    clip = float(np.percentile(data[::4, ::4, k0:k1:4], 99)) / gain
scale = ATTRS[attr]["scale"]


def section(arr2d: np.ndarray, x: np.ndarray, x_title: str, hor_line: np.ndarray | None, title: str) -> go.Figure:
    fig = sp.seismic_section(arr2d[:, k0:k1], x=x, samples=samples[k0:k1], clip=clip, colorscale=scale,
                             x_title=x_title, title=title, height=680, zmin=None if attr == "Amplitude" else 0.0,
                             colorbar_title="Amp" if attr == "Amplitude" else attr)
    if show_hor and hor_line is not None:
        fig.add_trace(go.Scatter(x=x, y=hor_line, mode="lines", line=dict(color="#111", width=2), name="Hugin Fm top"))
    return fig


tab_il, tab_xl, tab_ts, tab_hor = st.tabs(["Inline", "Crossline", "Time slice", "Horizon"])

with tab_il:
    il = st.select_slider("Inline", options=[int(v) for v in ilines], value=int(ilines[len(ilines) // 2]))
    i = int(np.searchsorted(ilines, il))
    st.plotly_chart(section(data[i], xlines, "Crossline", None if hor is None else hor[i], f"Inline {il} - {attr}"),
                    width="stretch")

with tab_xl:
    xl = st.select_slider("Crossline", options=[int(v) for v in xlines], value=int(xlines[len(xlines) // 2]))
    j = int(np.searchsorted(xlines, xl))
    st.plotly_chart(section(data[:, j], ilines, "Inline", None if hor is None else hor[:, j], f"Crossline {xl} - {attr}"),
                    width="stretch")

with tab_ts:
    t = st.select_slider("Time (ms TWT)", options=[float(s) for s in samples[k0:k1]], value=float(samples[(k0 + k1) // 2]))
    k = int(np.searchsorted(samples, t))
    fig = sp.seismic_slice(data[:, :, k], ilines, xlines, clip=clip, colorscale=scale,
                           title=f"Time slice {t:.0f} ms - {attr}", height=520,
                           zmin=None if attr == "Amplitude" else 0.0, colorbar_title="Amp" if attr == "Amplitude" else attr)
    if well is not None:
        inside = well[well["il"].between(ilines[0], ilines[-1]) & well["xl"].between(xlines[0], xlines[-1])]
        if len(inside):
            fig.add_trace(go.Scatter(x=inside["xl"], y=inside["il"], mode="lines",
                                     line=dict(color="#111", width=3), name="Well F-12 path"))
    st.plotly_chart(fig, width="stretch")
    st.caption("Map view in line coordinates. Trace spacing is about 12.5 m both ways, so this sub-cube is a narrow strip. "
               "The black line is the surface projection of well F-12 where it crosses the cube.")

with tab_hor:
    if hor is None:
        st.info("Horizon file not found.")
    else:
        a, b = st.columns(2)
        win = a.slider("Extraction half-window (samples)", 0, 10, 3)
        mode = b.radio("Extraction", ["rms", "max_abs"], horizontal=True, disabled=win == 0)
        amp = su.amplitude_along_horizon(cube, meta, hor, window=win, mode=mode)
        left, right = st.columns(2)
        layout = dict(height=460, xaxis_title="Crossline", yaxis_title="Inline", margin=dict(l=60, r=20, t=60, b=40))
        f1 = go.Figure(go.Heatmap(z=hor, x=xlines, y=ilines, colorscale="Viridis_r", colorbar=dict(title="TWT ms", thickness=12)))
        f1.update_layout(title="Hugin Fm top: two-way time structure", **layout)
        left.plotly_chart(f1, width="stretch")
        f2 = go.Figure(go.Heatmap(z=amp, x=xlines, y=ilines, colorscale="RdBu" if win == 0 else "Viridis",
                                  zmid=0 if win == 0 else None, colorbar=dict(title="Amp", thickness=12)))
        f2.update_layout(title="Amplitude extracted along the horizon", **layout)
        right.plotly_chart(f2, width="stretch")
        st.caption("Left: interpreted horizon, shallow in yellow. Right: amplitude taken from the cube along that horizon. "
                   "Structure and amplitude together are the usual first screen for where a reservoir sits and whether "
                   "its seismic response changes across it.")

st.sidebar.divider()
st.sidebar.caption("Data: Volve Data Village (Equinor), sub-cube from the segysak examples, Equinor Open Data Licence.")
