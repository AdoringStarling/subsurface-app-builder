"""Time-lapse (4D) seismic: what changed in the reservoir between two surveys, and can the change be trusted?

Runs on a SYNTHETIC base and monitor survey with a known production effect, so the answer can be checked.

Run from the repository root:
    python scripts/prepare_synthetic.py
    streamlit run demos/04_time_lapse/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "subsurface-app-builder" / "scripts"))
import subsurface_plots as sp  # noqa: E402
import subsurface_utils as su  # noqa: E402
import time_lapse as tl  # noqa: E402

DATA = ROOT / "data" / "synthetic"

st.set_page_config(page_title="Time-lapse seismic", layout="wide")

if not (DATA / "monitor.npy").exists():
    st.error("Synthetic surveys not found. Create them with:\n\n`python scripts/prepare_synthetic.py`")
    st.stop()


@st.cache_resource
def surveys():
    base, meta = su.load_cube(DATA / "base")
    monitor, meta_m = su.load_cube(DATA / "monitor")
    truth = json.loads((DATA / "synthetic_4d_truth.json").read_text())
    return np.asarray(base), np.asarray(monitor), meta, meta_m, truth


@st.cache_data(show_spinner="Matching monitor to base...")
def matched_monitor(k0: int, k1: int):
    base, monitor, *_ = surveys()
    return tl.match(base, monitor, k0, k1)


@st.cache_data(show_spinner="Estimating time shifts...")
def shifts(do_match: bool, k0: int, k1: int, window: int):
    base, monitor, *_ = surveys()
    mon = matched_monitor(k0, k1)[0] if do_match else monitor
    return tl.time_shift(base, mon, window=window, max_lag=3)


base, monitor_raw, meta, meta_m, truth = surveys()
problems = tl.same_geometry(meta, meta_m)
if problems:
    st.error("The two surveys do not share geometry, so they cannot be compared sample by sample: " + "; ".join(problems))
    st.stop()

ilines, xlines, samples = np.array(meta["ilines"]), np.array(meta["xlines"]), np.array(meta["samples"])
dt = float(meta["sample_interval"])
horizon = np.array(truth["horizon_sample"])

# ---------------------------------------------------------------- sidebar
st.sidebar.title("Time-lapse seismic")
st.sidebar.warning("Synthetic data with a planted production effect. Not a real field.")
st.sidebar.subheader("1. Match the surveys")
do_match = st.sidebar.checkbox("Remove bulk shift and amplitude difference", True)
q0, q1 = st.sidebar.slider("Quiet window (ms): overburden with no expected change", float(samples[0]), float(samples[-1]),
                           (float(samples[0]), float(samples[60])), step=dt)
k0, k1 = int(np.searchsorted(samples, q0)), max(int(np.searchsorted(samples, q1)), int(np.searchsorted(samples, q0)) + 10)
st.sidebar.subheader("2. Separate time shift from amplitude change")
do_align = st.sidebar.checkbox("Align monitor to base before differencing", False,
                               help="Removes the difference caused purely by events arriving later below the reservoir.")
window = st.sidebar.slider("Time-shift window (samples)", 11, 51, 25, 2)
gain = st.sidebar.slider("Difference gain", 1.0, 8.0, 3.0, 0.5, help="The difference is shown at base clip divided by this.")

monitor, report = matched_monitor(k0, k1) if do_match else (monitor_raw, None)
ts = shifts(do_match, k0, k1, window)
aligned = tl.apply_shift(monitor, ts) if do_align else monitor
diff = aligned - base
clip = float(meta["clip_p99"])

# ---------------------------------------------------------------- headline numbers
st.title("What changed between the surveys?")
quiet_before = tl.nrms(base[..., k0:k1], monitor_raw[..., k0:k1])
quiet_now = tl.nrms(base[..., k0:k1], monitor[..., k0:k1])
change_map = tl.rms_along_horizon(diff, horizon, half=4)
shift_map = tl.value_along_horizon(ts, horizon, offset=30) * dt
background = float(np.median(change_map))
anomaly = change_map > 3 * background
c = st.columns(4)
c[0].metric("NRMS in quiet window, %", f"{quiet_now:.1f}", f"{quiet_now - quiet_before:+.1f} vs unmatched", delta_color="inverse")
c[1].metric("Bulk shift removed, ms", "-" if report is None else f"{report['bulk_shift_samples'] * dt:.2f}")
c[2].metric("Area of change, traces", f"{int(anomaly.sum())} of {anomaly.size}")
c[3].metric("Largest slow-down below reservoir, ms", f"{float(np.percentile(shift_map, 99)):.1f}")

tab_sec, tab_map, tab_ts, tab_rep = st.tabs(["Sections", "Change map", "Time shift", "Repeatability"])

with tab_sec:
    cc = st.columns([3, 1])
    il = cc[0].select_slider("Inline", options=[int(v) for v in ilines], value=int(ilines[len(ilines) // 2]))
    view = cc[1].radio("Show", ["Difference", "Base", "Monitor"], horizontal=True)
    i = int(np.searchsorted(ilines, il))
    if view == "Difference":
        fig = sp.seismic_section(diff[i], x=xlines, samples=samples, x_title="Crossline", clip=clip / gain,
                                 title=f"Inline {il} - monitor minus base (clip = base clip / {gain:g})")
    else:
        fig = sp.seismic_section((base if view == "Base" else aligned)[i], x=xlines, samples=samples,
                                 x_title="Crossline", clip=clip, title=f"Inline {il} - {view.lower()}")
    fig.add_trace(go.Scatter(x=xlines, y=samples[horizon[i]], mode="lines", name="Reservoir horizon",
                             line=dict(color="#00C853", width=1.5, dash="dot")))
    st.plotly_chart(fig, width="stretch")
    st.caption("Without alignment the difference continues below the reservoir although nothing changed there: "
               "those events only arrive later. Tick 'Align monitor to base' and the deeper difference disappears, "
               "leaving the amplitude change at the reservoir.")

with tab_map:
    left, right = st.columns(2)
    left.plotly_chart(sp.seismic_slice(change_map, ilines, xlines, colorscale="Viridis", zmin=0.0,
                                       clip=float(np.percentile(change_map, 99.5)), colorbar_title="RMS diff",
                                       title="RMS of the difference, +/- 16 ms around the reservoir"), width="stretch")
    show_truth = right.checkbox("Show the planted effect (possible only because the data is synthetic)", True)
    if show_truth:
        right.plotly_chart(sp.seismic_slice(np.array(truth["footprint"]), ilines, xlines, colorscale="Viridis", zmin=0.0, clip=1.0,
                                            colorbar_title="Weight", title="Truth: where production changed the rock"), width="stretch")
    st.caption(f"Change is called where the difference exceeds three times the survey median ({background:.3f}).")

with tab_ts:
    left, right = st.columns(2)
    lim = max(1.0, float(np.percentile(np.abs(shift_map), 99.5)))
    left.plotly_chart(sp.seismic_slice(shift_map, ilines, xlines, clip=lim, colorbar_title="ms",
                                       title="Time shift 120 ms below the reservoir (red = monitor later)",
                                       colorscale="RdBu_r"), width="stretch")
    il2 = right.select_slider("Inline ", options=[int(v) for v in ilines], value=int(ilines[len(ilines) // 2]))
    right.plotly_chart(sp.seismic_section(ts[int(np.searchsorted(ilines, il2))] * dt, x=xlines, samples=samples, x_title="Crossline",
                                          clip=lim, colorscale="RdBu_r", colorbar_title="ms", height=500,
                                          title=f"Inline {il2} - time shift"), width="stretch")
    st.caption(f"Planted slow-down: {truth['slowdown_ms']:g} ms. Shifts come from windowed cross-correlation, so they are "
               "smeared over the window length and noisy where reflections are weak.")

with tab_rep:
    left, right = st.columns(2)
    nm_raw = tl.nrms_map(base, monitor_raw, k0, k1)
    nm = tl.nrms_map(base, monitor, k0, k1)
    top = float(max(np.percentile(nm_raw, 99), 1))
    left.plotly_chart(sp.seismic_slice(nm_raw, ilines, xlines, colorscale="Viridis", zmin=0.0, clip=top, colorbar_title="NRMS %",
                                       title=f"Before matching: median {np.median(nm_raw):.0f} %"), width="stretch")
    right.plotly_chart(sp.seismic_slice(nm, ilines, xlines, colorscale="Viridis", zmin=0.0, clip=top, colorbar_title="NRMS %",
                                        title=f"After matching: median {np.median(nm):.0f} %"), width="stretch")
    if report:
        st.write(f"Matching removed a bulk shift of **{report['bulk_shift_samples'] * dt:.2f} ms** and scaled the monitor by "
                 f"**{report['amplitude_scale']:.3f}**. (Planted: {truth['static_ms']:g} ms and {truth['amplitude_scale']:g}x.)")
    st.caption("NRMS = 200 x rms(monitor - base) / (rms(monitor) + rms(base)), measured where nothing should have changed. "
               "It is the noise floor: a 4D difference is believable only where it stands clearly above it.")

st.sidebar.divider()
st.sidebar.caption("Data: synthetic, generated by make_synthetic.py --monitor.")
