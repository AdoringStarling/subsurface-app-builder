"""NCS Explorer: wells, fields and production on the Norwegian continental shelf from open FactPages data.

Run from the repo root:  streamlit run demos/03_ncs_explorer/app.py
The "Ask the data" tab needs Anthropic credentials (ANTHROPIC_API_KEY); everything else works without.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "subsurface-app-builder" / "scripts"))
import ask_data  # noqa: E402
import subsurface_utils as su  # noqa: E402

DATA = ROOT / "data" / "factpages"
st.set_page_config(page_title="NCS Explorer", layout="wide")

if not (DATA / "field.csv").exists():
    st.error("FactPages tables not found. Run:\n\n"
             "`python skills/subsurface-app-builder/scripts/fetch_factpages.py --all --out data/factpages`")
    st.stop()

CONTENT_COLOURS = {"OIL": "#2E7D32", "GAS": "#D32F2F", "OIL/GAS": "#F9A825", "GAS/CONDENSATE": "#EF6C00",
                   "DRY": "#9E9E9E", "SHOWS": "#90A4AE", "OTHER": "#5C6BC0"}


@st.cache_resource(show_spinner="Loading FactPages tables...")
def database():
    con = su.factpages_duckdb(DATA)
    con.execute("SET enable_external_access = false")  # queries cannot read files or the network
    return con


@st.cache_data
def q(sql: str) -> pd.DataFrame:
    return database().execute(sql).df()


@st.cache_data
def system_prompt() -> str:
    return ask_data.schema_prompt(database(), ask_data.FACTPAGES_NOTES)


def simplify_content(s: pd.Series) -> pd.Series:
    s = s.fillna("OTHER").str.upper()
    s = s.where(~s.str.contains("SHOWS"), "SHOWS")
    return s.where(s.isin(CONTENT_COLOURS), "OTHER")


wells = q('''SELECT wlbWellboreName AS well, wlbDrillingOperator AS operator, wlbPurpose AS purpose, wlbContent AS content,
                    wlbEntryYear AS year, wlbMainArea AS area, wlbTotalDepth AS td_m, wlbWaterDepth AS water_depth_m,
                    wlbAgeAtTd AS age_at_td, wlbFormationAtTd AS formation_at_td, wlbDiscovery AS discovery,
                    wlbNsDecDeg AS lat, wlbEwDecDeg AS lon
             FROM wellbore_exploration_all WHERE wlbNsDecDeg IS NOT NULL''')
wells["content_group"] = simplify_content(wells["content"])
wells = wells[wells["year"] > 0]

st.sidebar.title("NCS Explorer")
st.sidebar.caption("Open data from the Norwegian Offshore Directorate FactPages.")
areas = sorted(wells["area"].dropna().unique())
sel_area = st.sidebar.multiselect("Area", areas, default=areas)
y0, y1 = int(wells["year"].min()), int(wells["year"].max())
years = st.sidebar.slider("Spud year", y0, y1, (y0, y1))
sel_content = st.sidebar.multiselect("Well content", list(CONTENT_COLOURS), default=list(CONTENT_COLOURS))
w = wells[wells["area"].isin(sel_area) & wells["year"].between(*years) & wells["content_group"].isin(sel_content)]

tab_map, tab_field, tab_hist, tab_ask = st.tabs(["Exploration map", "Field production", "Exploration history", "Ask the data"])

with tab_map:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Exploration wellbores", f"{len(w):,}")
    hc = w["content_group"].isin(["OIL", "GAS", "OIL/GAS", "GAS/CONDENSATE"])
    c2.metric("With hydrocarbons", f"{100 * hc.mean():.0f} %" if len(w) else "-")
    c3.metric("Deepest", f"{w['td_m'].max():,.0f} m" if len(w) else "-")
    c4.metric("Operators", w["operator"].nunique())
    fig = px.scatter_map(w, lat="lat", lon="lon", color="content_group", color_discrete_map=CONTENT_COLOURS,
                         hover_name="well", hover_data={"operator": True, "year": True, "td_m": True, "age_at_td": True,
                                                        "lat": False, "lon": False, "content_group": False, "content": True},
                         zoom=3.6, height=680, map_style="carto-positron")
    fig.update_traces(marker=dict(size=7, opacity=0.8))
    centre = dict(lat=float(w["lat"].mean()), lon=float(w["lon"].mean())) if len(w) else dict(lat=62.0, lon=5.0)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend_title_text="Content", map_center=centre)
    st.plotly_chart(fig, width="stretch")
    st.caption("One point per exploration wellbore, coloured by what it found. Base map needs internet; the data is local.")

with tab_field:
    fields = q("SELECT DISTINCT prfInformationCarrier AS f FROM field_production_monthly ORDER BY 1")["f"].tolist()
    field = st.selectbox("Field", fields, index=fields.index("EKOFISK") if "EKOFISK" in fields else 0)
    safe = field.replace("'", "''")
    prod = q(f'''SELECT make_date(prfYear, prfMonth, 1) AS month, prfPrdOilNetMillSm3 AS oil, prfPrdGasNetBillSm3 AS gas,
                        prfPrdNGLNetMillSm3 + prfPrdCondensateNetMillSm3 AS ngl_condensate,
                        prfPrdOeNetMillSm3 AS oe, prfPrdProducedWaterInFieldMillSm3 AS water
                 FROM field_production_monthly WHERE prfInformationCarrier = '{safe}' ORDER BY 1''')
    info = q(f'''SELECT cmpLongName AS operator, fldCurrentActivitySatus AS status, fldMainArea AS area, fldHcType AS hc,
                        wlbName AS discovery_well FROM field WHERE fldName = '{safe}' ''')
    res = q(f'''SELECT fldRecoverableOE AS rec, fldRemainingOE AS rem, fldVersion AS version FROM field_reserves
                WHERE fldName = '{safe}' ORDER BY fldVersion DESC LIMIT 1''')
    m = st.columns(5)
    m[0].metric("Status", info["status"].iloc[0] if len(info) else "-")
    m[1].metric("Produced, M Sm3 o.e.", f"{prod['oe'].sum():,.1f}")
    m[2].metric("Recoverable (official)", f"{res['rec'].iloc[0]:,.1f}" if len(res) else "-")
    m[3].metric("Remaining (official)", f"{res['rem'].iloc[0]:,.1f}" if len(res) else "-")
    m[4].metric("On stream", f"{prod['month'].min():%Y}" if len(prod) else "-")
    if len(info):
        st.caption(f"Operator: {info['operator'].iloc[0]} | {info['area'].iloc[0]} | {info['hc'].iloc[0]} | "
                   f"discovery well {info['discovery_well'].iloc[0]}")

    fig = go.Figure()
    for col, name, colour in [("oil", "Oil (M Sm3)", "#2E7D32"), ("gas", "Gas (G Sm3)", "#D32F2F"),
                              ("ngl_condensate", "NGL + condensate (M Sm3)", "#EF6C00"), ("water", "Produced water (M Sm3)", "#1565C0")]:
        fig.add_trace(go.Scatter(x=prod["month"], y=prod[col], name=name, mode="lines", line=dict(color=colour, width=1.6)))
    fig.update_layout(height=430, title=f"{field}: monthly production", yaxis_title="Volume per month",
                      legend=dict(orientation="h", y=-0.15), margin=dict(l=60, r=20, t=50, b=40), hovermode="x unified")
    st.plotly_chart(fig, width="stretch")

    with st.expander("Decline fit and forecast (exponential, oil equivalents)"):
        yearly = prod.assign(year=prod["month"].dt.year).groupby("year", as_index=False)["oe"].sum()
        yearly = yearly[yearly["year"] < yearly["year"].max()]  # drop the incomplete current year
        if len(yearly) >= 6 and yearly["oe"].iloc[-1] > 0:
            n_fit = st.slider("Years used for the fit", 3, min(20, len(yearly)), min(8, len(yearly)))
            fit = yearly.tail(n_fit)
            fit = fit[fit["oe"] > 0]
            slope, intercept = np.polyfit(fit["year"], np.log(fit["oe"]), 1)
            if slope < 0:
                future = np.arange(yearly["year"].max() + 1, yearly["year"].max() + 31)
                fc = np.exp(intercept + slope * future)
                limit = st.number_input("Economic limit (M Sm3 o.e. per year)", value=round(float(yearly["oe"].iloc[-1]) * 0.1, 3), format="%.3f")
                keep = fc >= limit
                f2 = go.Figure()
                f2.add_trace(go.Bar(x=yearly["year"], y=yearly["oe"], name="Produced", marker_color="#90A4AE"))
                f2.add_trace(go.Scatter(x=future[keep], y=fc[keep], name="Forecast", line=dict(color="#D32F2F", dash="dash")))
                f2.update_layout(height=360, yaxis_title="M Sm3 o.e. per year", margin=dict(l=60, r=20, t=20, b=40))
                st.plotly_chart(f2, width="stretch")
                a, b, c = st.columns(3)
                a.metric("Decline rate", f"{100 * (1 - np.exp(slope)):.1f} % per year")
                b.metric("Forecast remaining", f"{fc[keep].sum():,.1f} M Sm3 o.e.")
                c.metric("Official remaining", f"{res['rem'].iloc[0]:,.1f} M Sm3 o.e." if len(res) else "-")
                st.caption("Exponential decline fitted to recent yearly totals and run to the economic limit. A screening estimate: "
                           "it ignores new wells, tie-ins, shut-downs and gas blow-down, which is why it can differ from the official figure.")
            else:
                st.info("Production is not declining over the fitted years, so an exponential decline does not apply.")
        else:
            st.info("Not enough production history for a decline fit.")

    desc = q(f"SELECT fldDescriptionHeading AS h, fldDescriptionText AS t FROM field_description WHERE fldName = '{safe}'")
    if len(desc):
        with st.expander("Field description (Norwegian Offshore Directorate)"):
            for r in desc.itertuples():
                st.markdown(f"**{r.h}**. {r.t}")

with tab_hist:
    by = w.groupby(["year", "content_group"]).size().reset_index(name="wells")
    fig = px.bar(by, x="year", y="wells", color="content_group", color_discrete_map=CONTENT_COLOURS,
                 category_orders={"content_group": list(CONTENT_COLOURS)}, height=420,
                 title="Exploration wellbores per year, by content")
    fig.update_layout(legend_title_text="Content", margin=dict(l=60, r=20, t=50, b=40))
    st.plotly_chart(fig, width="stretch")
    left, right = st.columns(2)
    rate = w.assign(hc=w["content_group"].isin(["OIL", "GAS", "OIL/GAS", "GAS/CONDENSATE"])).groupby("year")["hc"].agg(["mean", "size"])
    rate = rate[rate["size"] >= 5]
    f1 = go.Figure(go.Scatter(x=rate.index, y=(100 * rate["mean"]).rolling(5, min_periods=1).mean(), line=dict(color="#2E7D32", width=2)))
    f1.update_layout(title="Share of wellbores with hydrocarbons (5-year rolling mean)", yaxis_title="%", height=360,
                     margin=dict(l=60, r=20, t=50, b=40))
    left.plotly_chart(f1, width="stretch")
    top = w["age_at_td"].dropna().value_counts().head(12).sort_values()
    f2 = go.Figure(go.Bar(x=top.values, y=top.index, orientation="h", marker_color="#5C6BC0"))
    f2.update_layout(title="Most common age at total depth", height=360, margin=dict(l=160, r=20, t=50, b=40))
    right.plotly_chart(f2, width="stretch")
    st.caption("Wildcat and appraisal wellbores are counted together, so the share with hydrocarbons is higher than a wildcat discovery rate.")

with tab_ask:
    st.caption("Ask in plain language. The model writes SQL, the app runs it on the local tables, and every query is shown. "
               "The model sees the table schema and at most 40 rows per result, never the full data.")
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    model = st.selectbox("Model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
                         index=["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"].index(ask_data.MODEL)
                         if ask_data.MODEL in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5") else 0,
                         help="Opus is the most capable. Haiku costs a small fraction and is usually enough for simple lookups.")
    examples = ["Which five fields have produced the most oil in total?",
                "How many exploration wells were spudded in the Barents Sea each decade, and what share found hydrocarbons?",
                "Which producing fields have the highest produced water to oil ratio over the last 12 months?"]
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("llm_messages", [])
    cols = st.columns(len(examples))
    picked = next((e for c, e in zip(cols, examples) if c.button(e, width="stretch")), None)

    for turn in st.session_state["chat"]:
        with st.chat_message(turn["role"]):
            st.markdown(turn["text"])
            for sql, df in turn.get("queries", []):
                with st.expander("SQL"):
                    st.code(sql, language="sql")
                    if df is not None:
                        st.dataframe(df.head(200), width="stretch", hide_index=True)

    question = st.chat_input("Ask about wells, fields, discoveries, production...", disabled=not has_key) or picked
    if not has_key:
        st.info("Set the ANTHROPIC_API_KEY environment variable and restart to enable this tab. The other tabs work without it.")
    elif question:
        st.session_state["chat"].append({"role": "user", "text": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"), st.spinner("Querying..."):
            try:
                out = ask_data.ask(database(), question, system_prompt(), history=st.session_state["llm_messages"], model=model)
            except Exception as e:  # keep the demo alive whatever the API does
                out = {"answer": f"The request failed: {type(e).__name__}: {e}", "queries": [], "usage": {}, "messages": st.session_state["llm_messages"]}
            st.markdown(out["answer"])
            for sql, df in out["queries"]:
                with st.expander("SQL"):
                    st.code(sql, language="sql")
                    if df is not None:
                        st.dataframe(df.head(200), width="stretch", hide_index=True)
            if out["usage"]:
                u = out["usage"]
                st.caption(f"Tokens: {u['input']:,} in, {u['output']:,} out, {u['cache_read']:,} read from cache.")
        st.session_state["llm_messages"] = out["messages"]
        st.session_state["chat"].append({"role": "assistant", "text": out["answer"], "queries": out["queries"]})

st.sidebar.divider()
st.sidebar.caption("Contains data from the Norwegian Offshore Directorate, NLOD 2.0.")
