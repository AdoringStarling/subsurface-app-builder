"""Plotly figures in the layouts geoscientists expect: well-log tracks, seismic sections, crossplots.

Copy this file next to an app together with subsurface_utils.py. Depends on numpy, pandas, plotly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Standard track definitions: curve -> (scale min, scale max, colour, log scale?, reversed?)
TRACK_STYLE: dict[str, dict] = {
    "GR": dict(range=(0, 150), color="#2E7D32"),
    "CALI": dict(range=(6, 26), color="#6D4C41", dash="dot"),
    "BS": dict(range=(6, 26), color="#212121", dash="dash"),
    "SP": dict(range=(-150, 150), color="#5E35B1"),
    "RDEP": dict(range=(0.2, 2000), color="#C62828", log=True),
    "RMED": dict(range=(0.2, 2000), color="#EF6C00", log=True, dash="dash"),
    "RSHA": dict(range=(0.2, 2000), color="#F9A825", log=True, dash="dot"),
    "RHOB": dict(range=(1.95, 2.95), color="#C62828"),
    "NPHI": dict(range=(0.45, -0.15), color="#1565C0", dash="dash"),
    "PEF": dict(range=(0, 10), color="#6A1B9A"),
    "DTC": dict(range=(140, 40), color="#00838F"),
    "DTS": dict(range=(340, 40), color="#AD1457", dash="dash"),
    "VSH": dict(range=(0, 1), color="#6B8E23"),
    "PHIE": dict(range=(0.5, 0), color="#1565C0"),
    "PHIT": dict(range=(0.5, 0), color="#64B5F6", dash="dash"),
    "SW": dict(range=(1, 0), color="#0277BD"),
}
# Plotly's named "Greys" runs black (low) to white (high). For discontinuity (1 - semblance) faults are
# high values and should be dark, so use this explicit white-to-black scale.
DISCONTINUITY_SCALE = [[0.0, "#ffffff"], [1.0, "#000000"]]

DEFAULT_TRACKS = [["GR", "CALI", "BS"], ["RDEP", "RMED", "RSHA"], ["RHOB", "NPHI"], ["DTC", "DTS"]]


def decimate(df: pd.DataFrame, max_points: int = 4000) -> pd.DataFrame:
    """Thin a log table for display. Browsers stall on hundreds of thousands of points."""
    step = max(1, len(df) // max_points)
    return df.iloc[::step]


def log_plot(df: pd.DataFrame, tracks: list[list[str]] | None = None, depth: str = "DEPTH",
             tops: dict[str, float] | None = None, flag: pd.Series | None = None,
             lithology: tuple[str, dict] | None = None, height: int = 850, title: str = "",
             max_points: int = 4000, flag_color: str = "#E53935") -> go.Figure:
    """Multi-track log display, depth increasing downward, shared depth axis.

    tracks:    list of tracks, each a list of column names; missing columns are skipped.
    tops:      {name: depth} drawn as horizontal lines across all tracks.
    flag:      boolean Series (same index as df); True intervals are shaded in flag_color
               (red for bad hole by default; pass e.g. "#2E7D32" for a pay flag).
    lithology: (column, {code: (name, colour)}) adds a coloured lithology strip as the last track.
    """
    tracks = [[c for c in t if c in df.columns and df[c].notna().any()] for t in (tracks or DEFAULT_TRACKS)]
    tracks = [t for t in tracks if t]
    n = len(tracks) + (1 if lithology else 0)
    if n == 0:
        return go.Figure().update_layout(title="No plottable curves")
    widths = [1.0] * len(tracks) + ([0.35] if lithology else [])
    fig = make_subplots(rows=1, cols=n, shared_yaxes=True, horizontal_spacing=0.015, column_widths=widths)
    d = decimate(df, max_points)

    for i, track in enumerate(tracks, start=1):
        first = TRACK_STYLE.get(track[0], {})
        labels = []
        for curve in track:
            st = TRACK_STYLE.get(curve, {})
            x = d[curve].to_numpy(dtype=float)
            # Curves sharing a track keep their own scale (RHOB 1.95-2.95 with NPHI 0.45 to -0.15):
            # each is mapped linearly onto the first curve's axis and the true value goes in the hover.
            r0, r1 = first.get("range"), st.get("range")
            if r0 and r1 and r1 != r0 and not first.get("log") and not st.get("log"):
                xs = r0[0] + (x - r1[0]) / (r1[1] - r1[0]) * (r0[1] - r0[0])
            else:
                xs = x
            labels.append(f"{curve} {r1[0]:g} to {r1[1]:g}" if r1 else curve)
            # go.Scatter (SVG), not Scattergl: WebGL line traces came out blank in multi-track subplots,
            # and browsers cap the number of WebGL contexts per page. Decimation keeps SVG fast.
            fig.add_trace(go.Scatter(
                x=xs, y=d[depth], customdata=x, name=curve, mode="lines",
                line=dict(color=st.get("color"), width=1.1, dash=st.get("dash")),
                hovertemplate=f"{curve}: %{{customdata:.3g}}<br>{depth}: %{{y:.1f}} m<extra></extra>"), row=1, col=i)
        axis = dict(title_text="<br>".join(labels), side="top", showgrid=True, gridcolor="#e5e5e5", title_font_size=11,
                    showticklabels=len(track) == 1 or bool(first.get("log")))
        if first.get("log"):
            lo, hi = first["range"]
            axis.update(type="log", range=[np.log10(lo), np.log10(hi)])
        elif "range" in first:
            axis.update(range=list(first["range"]))
        fig.update_xaxes(**axis, row=1, col=i)

    if lithology:
        col, codes = lithology
        if col in df.columns:
            s = df[[depth, col]].dropna()
            if len(s):
                # collapse consecutive samples of the same code into one bar per bed
                change = s[col].ne(s[col].shift()).cumsum()
                beds = s.groupby(change).agg(top=(depth, "first"), base=(depth, "last"), code=(col, "first"))
                seen = set()
                for code, grp in beds.groupby("code"):
                    name, colour = codes.get(int(code), (str(code), "#999999"))
                    fig.add_trace(go.Bar(
                        x=[1] * len(grp), y=(grp["base"] - grp["top"]).clip(lower=0.01), base=grp["top"],
                        orientation="v", marker_color=colour, marker_line_width=0, width=1, name=name,
                        legendgroup=name, showlegend=name not in seen,
                        hovertemplate=f"{name}<br>%{{base:.1f}} m<extra></extra>"), row=1, col=n)
                    seen.add(name)
        fig.update_xaxes(title_text="Lith", side="top", showticklabels=False, range=[0.5, 1.5], row=1, col=n)

    # Shapes are built as plain dicts and assigned once. fig.add_hrect()/add_hline() per interval
    # costs ~0.1 s each on a multi-track figure, which turns a few hundred intervals into minutes.
    shapes, annotations = [], []
    if flag is not None and flag.any():
        f = pd.DataFrame({"d": df[depth].to_numpy(), "f": flag.fillna(False).to_numpy(dtype=bool)})
        runs = f["f"].ne(f["f"].shift()).cumsum()
        spans = f[f["f"]].groupby(runs[f["f"]])["d"].agg(["first", "last"])
        for y0, y1 in spans.itertuples(index=False):
            shapes.append(dict(type="rect", xref="paper", x0=0, x1=1, yref="y", y0=y0, y1=y1,
                               fillcolor=flag_color, opacity=0.15, line_width=0, layer="below"))
    for name, dep in (tops or {}).items():
        shapes.append(dict(type="line", xref="paper", x0=0, x1=1, yref="y", y0=dep, y1=dep,
                           line=dict(color="#333", width=1, dash="dash")))
        annotations.append(dict(xref="paper", x=0, yref="y", y=dep, text=name, showarrow=False,
                                xanchor="left", yanchor="bottom", font=dict(size=10)))
    fig.update_layout(shapes=shapes, annotations=annotations)

    valid = df[depth][df[[c for t in tracks for c in t]].notna().any(axis=1)] if tracks else df[depth]
    fig.update_yaxes(range=[valid.max(), valid.min()], row=1, col=1, title_text="Depth (m)")
    fig.update_layout(height=height, title=title, barmode="overlay", bargap=0, plot_bgcolor="white",
                      legend=dict(orientation="h", y=-0.03), margin=dict(l=60, r=20, t=130 if title else 100, b=40),
                      hovermode="y")
    return fig


def seismic_section(data: np.ndarray, x: np.ndarray | None = None, samples: np.ndarray | None = None,
                    clip: float | None = None, colorscale="RdBu", x_title: str = "Trace",
                    y_title: str = "TWT (ms)", height: int = 650, title: str = "",
                    max_traces: int = 1500, max_samples: int = 1500, zmin: float | None = None,
                    colorbar_title: str = "Amp") -> go.Figure:
    """Vertical seismic section. data has shape (traces, samples); time/depth increases downward.

    clip: symmetric amplitude limit (use the 99th percentile of |amplitude|, e.g. clip_p99 from
          segy_to_npy.py). Without a clip a few strong amplitudes wash the whole image out.
    zmin: lower colour limit for unsigned attributes (envelope, discontinuity). Pass a fixed value
          (usually 0) so the scale does not shift from slice to slice; signed data ignores it.
    Unsigned attributes should pass a sequential colorscale ("Viridis", or DISCONTINUITY_SCALE).
    """
    data = np.asarray(data)
    x = np.arange(data.shape[0]) if x is None else np.asarray(x)
    samples = np.arange(data.shape[1]) if samples is None else np.asarray(samples)
    sx, ss = max(1, data.shape[0] // max_traces), max(1, data.shape[1] // max_samples)
    z = data[::sx, ::ss].T
    signed = bool(np.nanmin(z) < 0)
    if clip is None:
        clip = float(np.nanpercentile(np.abs(z), 99)) or 1.0
    fig = go.Figure(go.Heatmap(
        z=z, x=x[::sx], y=samples[::ss], colorscale=colorscale,
        zmin=-clip if signed else (float(np.nanmin(z)) if zmin is None else zmin), zmax=clip,
        zsmooth="best" if z.size < 400_000 else False,
        colorbar=dict(title=colorbar_title, thickness=12),
        hovertemplate=f"{x_title} %{{x}}<br>%{{y:.0f}}<br>%{{z:.3g}}<extra></extra>"))
    fig.update_yaxes(autorange="reversed", title_text=y_title)
    fig.update_xaxes(title_text=x_title, side="top")
    fig.update_layout(height=height, title=title, margin=dict(l=60, r=20, t=90 if title else 50, b=30))
    return fig


def seismic_slice(data: np.ndarray, ilines: np.ndarray, xlines: np.ndarray, clip: float | None = None,
                  colorscale="RdBu", height: int = 550, title: str = "", zmin: float | None = None,
                  colorbar_title: str = "Amp", aspect: float | None = None) -> go.Figure:
    """Horizontal (time/depth) slice in map view. data has shape (inlines, crosslines).

    zmin:   fixed lower limit for unsigned attributes (see seismic_section).
    aspect: metres per inline number divided by metres per crossline number. When given, the map is
            drawn to true scale; leave None to fill the available width (better for narrow surveys).
    """
    signed = bool(np.nanmin(data) < 0)
    if clip is None:
        clip = float(np.nanpercentile(np.abs(data), 99)) or 1.0
    fig = go.Figure(go.Heatmap(z=np.asarray(data), x=xlines, y=ilines, colorscale=colorscale,
                               zmin=-clip if signed else (float(np.nanmin(data)) if zmin is None else zmin), zmax=clip,
                               colorbar=dict(title=colorbar_title, thickness=12),
                               hovertemplate="Inline %{y}<br>Crossline %{x}<br>%{z:.3g}<extra></extra>"))
    if aspect:
        fig.update_yaxes(scaleanchor="x", scaleratio=aspect)
    fig.update_layout(height=height, title=title, xaxis_title="Crossline", yaxis_title="Inline",
                      margin=dict(l=60, r=20, t=60 if title else 30, b=40))
    return fig


def crossplot(df: pd.DataFrame, x: str, y: str, color: str | None = None, log_x: bool = False,
              reverse_y: bool = False, max_points: int = 15000, height: int = 550, title: str = "") -> go.Figure:
    """Scatter crossplot (e.g. NPHI vs RHOB coloured by GR). Samples randomly above max_points."""
    cols = [c for c in (x, y, color) if c]
    d = df[cols].dropna()
    if len(d) > max_points:
        d = d.sample(max_points, random_state=0)
    marker = dict(size=4, opacity=0.6)
    if color:
        marker.update(color=d[color], colorscale="Viridis", showscale=True, colorbar=dict(title=color, thickness=12))
    fig = go.Figure(go.Scattergl(x=d[x], y=d[y], mode="markers", marker=marker))
    fig.update_xaxes(title_text=x, type="log" if log_x else "linear")
    fig.update_yaxes(title_text=y, autorange="reversed" if reverse_y else True)
    fig.update_layout(height=height, title=title, plot_bgcolor="white", margin=dict(l=60, r=20, t=60 if title else 30, b=50))
    return fig
