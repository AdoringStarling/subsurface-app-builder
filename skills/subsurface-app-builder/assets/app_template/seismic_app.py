"""<App name>: <one line on what it does and for whom>.

Seismic starter: inline / crossline / time-slice viewer for one 3D cube, with a fault (discontinuity) display.

Run:  streamlit run seismic_app.py      (rename to app.py when this is the app)
Needs subsurface_utils.py, subsurface_plots.py and seismic_attributes.py (from the skill's scripts/) next to
this file, and a cube prepared with:  python segy_to_npy.py <file.sgy> data/survey  [--iline-byte N --xline-byte M]
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import streamlit as st

import seismic_attributes as sa
import subsurface_plots as sp
import subsurface_utils as su

CUBE = Path(__file__).parent / "data" / "survey"       # path without extension

st.set_page_config(page_title="<App name>", layout="wide")

if not CUBE.with_suffix(".npy").exists():
    st.error("Cube not found. Prepare it with:\n\n`python segy_to_npy.py <file.sgy> data/survey`")
    st.stop()


@st.cache_resource
def cube_and_meta():
    return su.load_cube(CUBE)            # memory-mapped: opening is instant


@st.cache_data(show_spinner="Computing attribute...")
def attribute(name: str, window: int) -> np.ndarray:
    c = np.asarray(cube_and_meta()[0])   # fine for cubes that fit in memory; slice first for larger ones
    if name == "Discontinuity":
        return (1 - sa.semblance(c, window)).astype(np.float32)
    if name == "Envelope":
        return sa.envelope(c)
    return c


cube, meta = cube_and_meta()
ilines, xlines, samples = np.array(meta["ilines"]), np.array(meta["xlines"]), np.array(meta["samples"])

# ---------------------------------------------------------------- sidebar
st.sidebar.title("<App name>")
st.sidebar.caption(f"{len(ilines)} inlines x {len(xlines)} crosslines x {len(samples)} samples, {meta['sample_interval']:g} ms")
attr = st.sidebar.radio("Display", ["Amplitude", "Discontinuity", "Envelope"])
window = st.sidebar.slider("Discontinuity window (samples)", 5, 31, 11, 2, disabled=attr != "Discontinuity")
gain = st.sidebar.slider("Gain", 0.25, 4.0, 1.0, 0.25)
data = attribute(attr, window)

if attr == "Amplitude":
    style = dict(clip=meta["clip_p99"] / gain, colorscale="RdBu", colorbar_title="Amp")
elif attr == "Discontinuity":
    style = dict(clip=min(1.0, 0.6 / gain), colorscale=sp.DISCONTINUITY_SCALE, zmin=0.0, colorbar_title="1 - semblance")
else:
    style = dict(clip=float(np.percentile(data[::4, ::4, ::4], 99)) / gain, colorscale="Viridis", zmin=0.0, colorbar_title="Envelope")

tab_il, tab_xl, tab_ts = st.tabs(["Inline", "Crossline", "Time slice"])

with tab_il:
    il = st.select_slider("Inline", options=[int(v) for v in ilines], value=int(ilines[len(ilines) // 2]))
    i = int(np.searchsorted(ilines, il))
    st.plotly_chart(sp.seismic_section(data[i], x=xlines, samples=samples, x_title="Crossline",
                                       title=f"Inline {il} - {attr}", **style), width="stretch")

with tab_xl:
    xl = st.select_slider("Crossline", options=[int(v) for v in xlines], value=int(xlines[len(xlines) // 2]))
    j = int(np.searchsorted(xlines, xl))
    st.plotly_chart(sp.seismic_section(data[:, j], x=ilines, samples=samples, x_title="Inline",
                                       title=f"Crossline {xl} - {attr}", **style), width="stretch")

with tab_ts:
    t = st.select_slider("Time (ms)", options=[float(s) for s in samples], value=float(samples[len(samples) // 2]))
    k = int(np.searchsorted(samples, t))
    half = st.slider("Average over +/- samples", 0, 10, 0, help="Stacking a few slices strengthens steep faults and suppresses noise.")
    sl = data[:, :, max(0, k - half):k + half + 1].mean(axis=2)
    st.plotly_chart(sp.seismic_slice(sl, ilines, xlines, title=f"Time slice {t:.0f} ms - {attr}", **style), width="stretch")

if attr == "Discontinuity":
    st.caption("Dark = traces differ from their neighbours: faults and edges, but also zones of weak signal and steep dip. "
               "Trust lineaments that persist across slices and lines.")

st.sidebar.divider()
st.sidebar.caption("Data: <source and licence>.")
