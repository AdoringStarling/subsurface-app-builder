"""Geosteering replay: follow a horizontal well as it is drilled and keep it in the target sand.

Runs on a SYNTHETIC well with known formation dips, so the interpretation can be checked.

Run from the repository root:
    python scripts/prepare_synthetic.py
    streamlit run demos/05_geosteering/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "subsurface-app-builder" / "scripts"))
import geosteering as gs  # noqa: E402
import subsurface_utils as su  # noqa: E402

DATA = ROOT / "data" / "synthetic" / "geosteer"

st.set_page_config(page_title="Geosteering replay", layout="wide")

if not (DATA / "lateral.las").exists():
    st.error("Synthetic well not found. Create it with:\n\n`python scripts/prepare_synthetic.py`")
    st.stop()


@st.cache_data
def load():
    truth = json.loads((DATA / "truth.json").read_text())
    survey = pd.read_csv(DATA / "survey.csv")
    lateral = su.las_to_frame(DATA / "lateral.las")[["DEPTH", "GR"]].dropna()
    type_well = su.las_to_frame(DATA / "type_well.las")[["DEPTH", "GR"]].dropna()
    return truth, survey, lateral, type_well


@st.cache_data(show_spinner="Fitting formation dips...")
def interpret(md_bit: float, seg_len: float, smooth: float):
    """Everything known when the bit is at md_bit: stations and log samples up to there, and the fit."""
    truth, survey, lateral, type_well = load()
    sv = survey[survey["md"] <= md_bit]
    path = gs.minimum_curvature(sv["md"], sv["inc"], sv["azi"], tvd0=truth["tvd_at_first_station"])
    lat = lateral[lateral["DEPTH"] <= sv["md"].max()]
    pts = gs.path_at(path, lat["DEPTH"], truth["azimuth"])
    fit = gs.fit_dips(pts["vs"], pts["tvd"], lat["GR"], type_well["DEPTH"], type_well["GR"], seg_len=seg_len, smooth=smooth)
    return path, pts, lat["GR"].to_numpy(), fit


truth, survey, lateral, type_well = load()
zone = (truth["zone_top"], truth["zone_base"])

# ---------------------------------------------------------------- sidebar
st.sidebar.title("Geosteering replay")
st.sidebar.warning("Synthetic well with known formation dips. Not a real well.")
stations = [float(m) for m in survey["md"] if m >= survey["md"].iloc[0] + 300]
md_bit = st.sidebar.select_slider("Drilled to (m MD)", options=stations, value=stations[len(stations) // 2],
                                  help="Move right to drill ahead. Only data behind the bit is used.")
with st.sidebar.expander("Interpretation settings"):
    seg_len = st.slider("Segment length (m)", 50, 250, 100, 25)
    smooth = st.select_slider("Dip smoothing", options=[0.0, 0.01, 0.05, 0.2, 1.0], value=0.05)
    manual = st.checkbox("Override the dip of the last segment")
    dip_override = st.number_input("Dip of last segment (deg, positive = beds deepen ahead)", -6.0, 6.0, 0.0, 0.25, disabled=not manual)
show_truth = st.sidebar.checkbox("Show the true structure", False, help="Possible only because the well is synthetic.")

path, pts, gr, fit = interpret(md_bit, float(seg_len), float(smooth))
dips = np.array(fit["dips_deg"], dtype=float)
if manual:
    dips[-1] = dip_override
model = gs.model_log(pts["tvd"], pts["vs"], fit["nodes_vs"], dips, type_well["DEPTH"], type_well["GR"], fit["start_shift"])
strat = gs.stratigraphic_depth(pts["tvd"], pts["vs"], fit["nodes_vs"], dips, fit["start_shift"])
lateral_part = pts["inc"].to_numpy() > 86
status = gs.zone_status(strat[lateral_part] if lateral_part.any() else strat, *zone)
advice = gs.steering_advice(float(dips[-1]), float(strat[-1]), *zone)
misfit = float(np.sqrt(np.mean((model - gr) ** 2)))

# ---------------------------------------------------------------- page
st.title("Where is the bit, and where should it go?")
c = st.columns(5)
c[0].metric("Lateral in zone, %", f"{100 * status['in_zone_fraction']:.0f}")
if status["bit_in_zone"]:
    c[1].metric("Bit position", "In zone", f"{status['bit_below_top_m']:.1f} m below top", delta_color="off", delta_arrow="off")
elif status["bit_below_top_m"] < 0:
    c[1].metric("Bit position", "Above zone", f"{-status['bit_below_top_m']:.1f} m above top", delta_color="inverse", delta_arrow="off")
else:
    c[1].metric("Bit position", "Below zone", f"{-status['bit_above_base_m']:.1f} m below base", delta_color="inverse", delta_arrow="off")
c[2].metric("Formation dip at bit, deg", f"{dips[-1]:+.2f}")
c[3].metric("Inclination now, deg", f"{float(pts['inc'].iloc[-1]):.1f}")
c[4].metric("Steer to, deg", f"{advice['to_centre_inc']:.1f}", f"{advice['to_centre_inc'] - float(pts['inc'].iloc[-1]):+.1f} vs now", delta_color="off")

tab_curtain, tab_type, tab_table = st.tabs(["Curtain section", "Type log", "Segments and survey"])

with tab_curtain:
    extra = dict(nodes_vs=truth["nodes_vs"], dips_deg=truth["dips_deg"], name="True zone") if show_truth else None
    st.plotly_chart(gs.curtain_figure(pts["vs"], pts["tvd"], fit["nodes_vs"], dips, type_well["DEPTH"], type_well["GR"],
                                      fit["start_shift"], log=gr, model=model, zone=zone, extra_structure=extra), width="stretch")
    st.caption(f"Colours: gamma ray of the offset well draped on the interpreted structure (yellow = sand). Dashed lines: target zone. Vertical scale is exaggerated. "
               f"Right of the bit is a projection with the last dip. Log match RMS {misfit:.1f} gAPI. "
               f"To stay parallel to bedding hold {advice['hold_parallel_inc']:.1f} deg; to reach the zone centre within 100 m "
               f"steer to {advice['to_centre_inc']:.1f} deg.")

with tab_type:
    import plotly.graph_objects as go

    t = type_well[(type_well["DEPTH"] > zone[0] - 25) & (type_well["DEPTH"] < zone[1] + 25)]
    fig = go.Figure(go.Scatter(x=t["GR"], y=t["DEPTH"], mode="lines", line=dict(color="#2E7D32", width=1.3), name="Type log GR"))
    fig.add_hrect(y0=zone[0], y1=zone[1], fillcolor="#F7E36B", opacity=0.35, line_width=0)
    fig.add_hline(y=float(strat[-1]), line=dict(color="#0D47A1", width=2), annotation_text="Bit (interpreted)")
    fig.update_yaxes(autorange="reversed", title_text="Type-well depth (m TVD)")
    fig.update_xaxes(title_text="GR (gAPI)", range=[0, 170], side="top")
    fig.update_layout(height=650, plot_bgcolor="white", margin=dict(l=60, r=20, t=50, b=30), showlegend=False)
    left, right = st.columns([1, 2])
    left.plotly_chart(fig, width="stretch")
    right.markdown(
        "**How to read this.** The offset well gives the gamma-ray signature of every bed. The horizontal well crosses the same "
        "beds very slowly, so its log is a stretched and sometimes mirrored copy of this one. Sliding the structure up and down "
        "until the stretched copy fits tells where the bit is in the sequence.\n\n"
        "**Markers that help here:** the hot shale 3 to 6 m above the sand, the thin shale streak in the middle of the sand, "
        "and the clean stringer 7 m below the base.\n\n"
        "**Limits.** Inside a thick uniform bed the log is flat and many dips fit equally well; the interpretation only tightens "
        "when the well meets a boundary or a marker. Gamma ray alone cannot tell whether a boundary was crossed from above or "
        "below unless an azimuthal tool or the bed sequence resolves it.")

with tab_table:
    seg = pd.DataFrame({"From VS (m)": np.round(fit["nodes_vs"], 0), "Dip (deg)": dips})
    seg["Parallel inclination (deg)"] = 90 - seg["Dip (deg)"]
    left, right = st.columns(2)
    left.markdown("**Interpreted segments**")
    left.dataframe(seg, width="stretch", hide_index=True)
    right.markdown("**Survey (minimum curvature)**")
    right.dataframe(path.round(2), width="stretch", hide_index=True)
    if show_truth:
        st.write("True dips (deg) from VS " + ", ".join(f"{n:.0f} m: {d:+.1f}" for n, d in zip(truth["nodes_vs"], truth["dips_deg"])))

st.sidebar.divider()
st.sidebar.caption("Data: synthetic, generated by make_synthetic.py --geosteer.")
