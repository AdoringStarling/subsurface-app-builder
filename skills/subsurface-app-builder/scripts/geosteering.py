"""Geosteering with a type log: where is a horizontal well in the stratigraphy, and where is it heading?

Model. The formation is a stack of parallel beds whose depth changes along the well's vertical
section (VS) as a chain of straight segments, each with an apparent dip. Subtracting that structure
from the well's TVD gives the equivalent depth in the offset ("type") well, so the type log predicts
what the tool should read. Dips are adjusted until the prediction matches the measured log.

Conventions: depths in metres, angles in degrees, inclination 0 = vertical and 90 = horizontal.
Dip is the apparent dip along the section, positive = beds get deeper in the drilling direction,
so a well stays parallel to bedding at inclination 90 - dip.

Import in an app, or fit from the command line:
    python geosteering.py survey.csv lateral.las type_well.las [--zone 1950 1962] [--tvd0 1880.5]
survey.csv has columns md, inc, azi. Depends on numpy, pandas; lasio for the CLI; plotly for the figure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ trajectory
def minimum_curvature(md, inc, azi, tvd0: float = 0.0, north0: float = 0.0, east0: float = 0.0) -> pd.DataFrame:
    """Well path from survey stations by the minimum-curvature method (the industry standard).

    tvd0/north0/east0 are the position of the first station. Returns md, inc, azi, tvd, north,
    east and dls (dogleg severity in deg/30 m).
    """
    md, inc, azi = (np.asarray(v, dtype=float) for v in (md, inc, azi))
    i, a = np.radians(inc), np.radians(azi)
    dmd = np.diff(md)
    cos_dl = np.cos(i[1:] - i[:-1]) - np.sin(i[:-1]) * np.sin(i[1:]) * (1 - np.cos(a[1:] - a[:-1]))
    dl = np.arccos(np.clip(cos_dl, -1, 1))
    rf = np.where(dl > 1e-7, 2 / np.where(dl > 1e-7, dl, 1) * np.tan(dl / 2), 1.0)
    dn = dmd / 2 * (np.sin(i[:-1]) * np.cos(a[:-1]) + np.sin(i[1:]) * np.cos(a[1:])) * rf
    de = dmd / 2 * (np.sin(i[:-1]) * np.sin(a[:-1]) + np.sin(i[1:]) * np.sin(a[1:])) * rf
    dv = dmd / 2 * (np.cos(i[:-1]) + np.cos(i[1:])) * rf
    cum = lambda d, x0: np.concatenate([[x0], x0 + np.cumsum(d)])
    dls = np.concatenate([[0.0], np.degrees(dl) / np.where(dmd > 0, dmd, 1) * 30])
    return pd.DataFrame(dict(md=md, inc=inc, azi=azi, tvd=cum(dv, tvd0), north=cum(dn, north0),
                             east=cum(de, east0), dls=dls))


def vertical_section(north, east, azimuth: float) -> np.ndarray:
    """Horizontal distance projected onto the section azimuth, zero at the first point."""
    north, east = np.asarray(north, dtype=float), np.asarray(east, dtype=float)
    az = np.radians(azimuth)
    return (north - north[0]) * np.cos(az) + (east - east[0]) * np.sin(az)


def path_at(path: pd.DataFrame, md, azimuth: float | None = None) -> pd.DataFrame:
    """TVD and VS at arbitrary measured depths (e.g. log samples), interpolated between stations.

    azimuth: section direction; default is the direction from the first to the last station.
    """
    if azimuth is None:
        azimuth = float(np.degrees(np.arctan2(path["east"].iloc[-1] - path["east"].iloc[0],
                                              path["north"].iloc[-1] - path["north"].iloc[0])) % 360)
    vs = vertical_section(path["north"], path["east"], azimuth)
    md = np.asarray(md, dtype=float)
    return pd.DataFrame(dict(md=md, tvd=np.interp(md, path["md"], path["tvd"]), vs=np.interp(md, path["md"], vs),
                             inc=np.interp(md, path["md"], path["inc"])))


# ------------------------------------------------------------------ structure model
def structure_shift(vs, nodes_vs, dips_deg, start_shift: float = 0.0) -> np.ndarray:
    """Depth of the beds relative to the type well, along VS.

    Segment k runs from nodes_vs[k] to nodes_vs[k+1] with dip dips_deg[k]; the last dip continues
    beyond the last node (that is the look-ahead). start_shift is the offset at nodes_vs[0].
    """
    vs = np.asarray(vs, dtype=float)
    nodes, slopes = np.asarray(nodes_vs, dtype=float), np.tan(np.radians(np.asarray(dips_deg, dtype=float)))
    at_node = start_shift + np.concatenate([[0.0], np.cumsum(slopes[:-1] * np.diff(nodes))])
    k = np.clip(np.searchsorted(nodes, vs, side="right") - 1, 0, len(nodes) - 1)
    return at_node[k] + slopes[k] * (vs - nodes[k])


def stratigraphic_depth(tvd, vs, nodes_vs, dips_deg, start_shift: float = 0.0) -> np.ndarray:
    """Equivalent depth in the type well for each point of the lateral (TVD minus structure)."""
    return np.asarray(tvd, dtype=float) - structure_shift(vs, nodes_vs, dips_deg, start_shift)


def model_log(tvd, vs, nodes_vs, dips_deg, type_depth, type_log, start_shift: float = 0.0) -> np.ndarray:
    """What the tool should read along the lateral if the structure model is right."""
    return np.interp(stratigraphic_depth(tvd, vs, nodes_vs, dips_deg, start_shift), type_depth, type_log)


def fit_dips(vs, tvd, log, type_depth, type_log, seg_len: float = 100.0, dips=None, smooth: float = 0.05,
             beam: int = 40, start_shifts=(0.0,)) -> dict:
    """Find the dip of each segment so the type log matches the measured log (beam search).

    seg_len:      segment length along VS. Shorter follows structure more closely but invents dips
                  from noise; 50-150 m is a reasonable range.
    dips:         candidate dips in degrees (default -5 to 5 in 0.25 steps).
    smooth:       penalty per (degree of dip change)^2 between neighbouring segments, in units of
                  type-log variance. Raise it if the result zig-zags.
    start_shifts: candidate offsets between the type well and the first point, in metres. Pass a
                  range (e.g. np.arange(-15, 15.5, 0.5)) when the tie to the type well is uncertain.
    Returns nodes_vs, dips_deg, start_shift, rms_misfit (in log units) and model (predicted log).

    The answer is not unique where the log is featureless (long stretch in one uniform bed): any
    dip that keeps the well inside the bed fits. Treat the fit as a proposal to be checked.
    """
    vs, tvd, log = (np.asarray(v, dtype=float) for v in (vs, tvd, log))
    type_depth, type_log = np.asarray(type_depth, dtype=float), np.asarray(type_log, dtype=float)
    ok = np.isfinite(log) & np.isfinite(tvd) & np.isfinite(vs)
    dips = np.arange(-5, 5.01, 0.25) if dips is None else np.asarray(dips, dtype=float)
    slopes = np.tan(np.radians(dips))
    var = float(np.nanvar(type_log)) or 1.0
    nodes = np.arange(vs[ok].min(), vs[ok].max(), seg_len)
    if len(nodes) > 1 and vs[ok].max() - nodes[-1] < 0.3 * seg_len:
        nodes = nodes[:-1]                                   # merge a short tail into the previous segment

    # beams: cost, shift at the current node, chosen dip indices, start shift
    beams = [(0.0, float(s0), [], float(s0)) for s0 in start_shifts]
    for k, node in enumerate(nodes):
        end = nodes[k + 1] if k + 1 < len(nodes) else np.inf
        sel = ok & (vs >= node) & (vs < end)
        dv, tv, lg = vs[sel] - node, tvd[sel], log[sel]
        seg_end = (end - node) if np.isfinite(end) else 0.0
        cand = []
        for cost, shift, chosen, s0 in beams:
            if len(lg):
                strat = tv[None, :] - shift - slopes[:, None] * dv[None, :]
                pred = np.interp(strat.ravel(), type_depth, type_log).reshape(strat.shape)
                err = np.mean((pred - lg[None, :]) ** 2, axis=1) / var
            else:
                err = np.zeros(len(dips))
            pen = smooth * (dips - dips[chosen[-1]]) ** 2 if chosen else 0.0
            for j in np.argsort(err + pen)[:beam]:
                cand.append((cost + float(err[j] + (pen[j] if chosen else 0.0)), shift + slopes[j] * seg_end, chosen + [int(j)], s0))
        cand.sort(key=lambda c: c[0])
        beams = cand[:beam]
    cost, _, chosen, s0 = beams[0]
    best = dips[chosen]
    model = model_log(tvd, vs, nodes, best, type_depth, type_log, s0)
    return dict(nodes_vs=nodes, dips_deg=best, start_shift=s0, model=model,
                rms_misfit=float(np.sqrt(np.nanmean((model[ok] - log[ok]) ** 2))))


# ------------------------------------------------------------------ what it means for drilling
def zone_status(strat_depth, zone_top: float, zone_base: float) -> dict:
    """Share of the points inside the target zone and where the last point (the bit) sits."""
    s = np.asarray(strat_depth, dtype=float)
    inside = (s >= zone_top) & (s <= zone_base)
    return dict(in_zone_fraction=float(inside.mean()), bit_in_zone=bool(inside[-1]),
                bit_below_top_m=float(s[-1] - zone_top), bit_above_base_m=float(zone_base - s[-1]))


def steering_advice(dip_ahead: float, strat_depth_bit: float, zone_top: float, zone_base: float,
                    lookahead: float = 100.0) -> dict:
    """Inclination to stay parallel to bedding, and to reach the zone centre within `lookahead` metres."""
    centre = 0.5 * (zone_top + zone_base)
    correction = float(np.degrees(np.arctan((strat_depth_bit - centre) / lookahead)))
    return dict(hold_parallel_inc=90.0 - dip_ahead, to_centre_inc=90.0 - dip_ahead + correction,
                bit_offset_from_centre_m=float(strat_depth_bit - centre))


# ------------------------------------------------------------------ display
GR_SCALE = [[0.0, "#F7E36B"], [0.35, "#D9C97A"], [0.6, "#8D9B6A"], [1.0, "#4E5B4A"]]   # sand yellow -> shale grey-green


def curtain_figure(vs, tvd, nodes_vs, dips_deg, type_depth, type_log, start_shift: float = 0.0,
                   log=None, model=None, zone: tuple[float, float] | None = None, vs_ahead: float = 150.0,
                   log_name: str = "GR", height: int = 700, extra_structure: dict | None = None):
    """Curtain section (type-log property draped on the structure model, with the well path) above
    the measured and modelled log, sharing the VS axis.

    zone:            (top, base) of the target in type-log depth; drawn as lines following the structure.
    vs_ahead:        how far beyond the bit to extend the model with the last dip.
    extra_structure: optional dict(nodes_vs, dips_deg, start_shift, name) drawn as a dotted zone
                     outline, e.g. the true structure of a synthetic case or an earlier interpretation.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    vs, tvd = np.asarray(vs, dtype=float), np.asarray(tvd, dtype=float)
    gx = np.linspace(vs.min(), vs.max() + vs_ahead, 400)
    pad = 12.0
    lo, hi = tvd.min() - pad, tvd.max() + pad
    if zone:
        sh = structure_shift(gx, nodes_vs, dips_deg, start_shift)
        lo, hi = min(lo, (zone[0] + sh).min() - pad), max(hi, (zone[1] + sh).max() + pad)
    gy = np.linspace(lo, hi, 300)
    z = np.interp(gy[:, None] - structure_shift(gx, nodes_vs, dips_deg, start_shift)[None, :], type_depth, type_log)
    p5, p95 = np.nanpercentile(type_log, [2, 98])

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.04)
    fig.add_trace(go.Heatmap(x=gx, y=gy, z=z, colorscale=GR_SCALE, zmin=p5, zmax=p95,
                             colorbar=dict(title=log_name, thickness=12, len=0.6, y=0.68),
                             hovertemplate="VS %{x:.0f} m<br>TVD %{y:.1f} m<br>" + log_name + " %{z:.0f}<extra></extra>"), row=1, col=1)
    if zone:
        sh = structure_shift(gx, nodes_vs, dips_deg, start_shift)
        for depth, name in ((zone[0], "Zone top"), (zone[1], "Zone base")):
            fig.add_trace(go.Scatter(x=gx, y=depth + sh, mode="lines", name=name,
                                     line=dict(color="#1B1B1B", width=1.5, dash="dash"), hoverinfo="skip"), row=1, col=1)
        if extra_structure:
            sh2 = structure_shift(gx, extra_structure["nodes_vs"], extra_structure["dips_deg"], extra_structure.get("start_shift", 0.0))
            for n, depth in enumerate(zone):
                fig.add_trace(go.Scatter(x=gx, y=depth + sh2, mode="lines", name=extra_structure.get("name", "Other model"),
                                         legendgroup="extra", showlegend=n == 0,
                                         line=dict(color="#D81B60", width=1.5, dash="dot"), hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter(x=vs, y=tvd, mode="lines", name="Well path", line=dict(color="#0D47A1", width=3)), row=1, col=1)
    fig.add_trace(go.Scatter(x=[vs[-1]], y=[tvd[-1]], mode="markers", name="Bit",
                             marker=dict(color="#0D47A1", size=11, symbol="diamond")), row=1, col=1)
    for node in np.asarray(nodes_vs)[1:]:
        fig.add_vline(x=float(node), line=dict(color="rgba(0,0,0,0.25)", width=1, dash="dot"))
    if log is not None:
        fig.add_trace(go.Scatter(x=vs, y=np.asarray(log), mode="lines", name=f"Measured {log_name}",
                                 line=dict(color="#2E7D32", width=1.2)), row=2, col=1)
    if model is not None:
        fig.add_trace(go.Scatter(x=vs, y=np.asarray(model), mode="lines", name=f"Modelled {log_name}",
                                 line=dict(color="#E65100", width=1.6)), row=2, col=1)
    fig.update_yaxes(range=[hi, lo], title_text="TVD (m)", row=1, col=1)
    fig.update_yaxes(title_text=log_name, row=2, col=1)
    fig.update_xaxes(title_text="Vertical section (m)", row=2, col=1)
    fig.update_layout(height=height, plot_bgcolor="white", margin=dict(l=60, r=20, t=30, b=40),
                      legend=dict(orientation="h", y=-0.1), hovermode="x")
    return fig


if __name__ == "__main__":
    import argparse
    import json

    import lasio

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("survey", help="CSV with md, inc, azi")
    ap.add_argument("lateral", help="LAS of the horizontal well, indexed by measured depth")
    ap.add_argument("type_well", help="LAS of the offset well, indexed by true vertical depth")
    ap.add_argument("--curve", default="GR")
    ap.add_argument("--tvd0", type=float, default=0.0, help="TVD of the first survey station")
    ap.add_argument("--seg-len", type=float, default=100.0)
    ap.add_argument("--shift-range", type=float, default=0.0, metavar="M",
                    help="search the offset to the type well within +/- M metres (default: trust the depths)")
    ap.add_argument("--zone", type=float, nargs=2, metavar=("TOP", "BASE"), help="target zone in type-log depth")
    a = ap.parse_args()

    sv = pd.read_csv(a.survey)
    path = minimum_curvature(sv["md"], sv["inc"], sv["azi"], tvd0=a.tvd0)
    lat, typ = lasio.read(a.lateral), lasio.read(a.type_well)
    pts = path_at(path, lat.index)
    inside = (pts["md"] >= sv["md"].min()) & (pts["md"] <= sv["md"].max())
    pts, log = pts[inside.to_numpy()], np.asarray(lat[a.curve])[inside.to_numpy()]
    shifts = np.arange(-a.shift_range, a.shift_range + 0.25, 0.5) if a.shift_range else (0.0,)
    fit = fit_dips(pts["vs"], pts["tvd"], log, typ.index, typ[a.curve], seg_len=a.seg_len, start_shifts=shifts)
    out = dict(start_shift_m=fit["start_shift"], segments=[dict(vs_from=round(float(n), 1), dip_deg=float(d)) for n, d in zip(fit["nodes_vs"], fit["dips_deg"])],
               rms_misfit=round(fit["rms_misfit"], 2), max_dls_deg_per_30m=round(float(path["dls"].max()), 2))
    if a.zone:
        strat = stratigraphic_depth(pts["tvd"], pts["vs"], fit["nodes_vs"], fit["dips_deg"], fit["start_shift"])
        out["zone"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in zone_status(strat, *a.zone).items()}
        out["advice"] = {k: round(v, 2) for k, v in steering_advice(float(fit["dips_deg"][-1]), float(strat[-1]), *a.zone).items()}
    print(json.dumps(out, indent=1))
