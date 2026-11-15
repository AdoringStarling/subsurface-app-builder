# App patterns (Streamlit + Plotly)

Default stack: **Streamlit + Plotly**, pure Python. One file gives a working, shareable app, which is what matters when the goal is something a geoscientist can click on within the hour. Move to another stack only when the user asks or the app needs what Streamlit cannot do (many concurrent users, fine-grained client-side interaction, custom drawing tools).

## Contents
- Starting an app
- The rerun model and caching
- Layout that works for subsurface apps
- Plots
- Maps
- Things that broke in practice
- Testing and screenshots
- Deploying
- When Streamlit is the wrong tool

## Starting an app

Copy `assets/app_template/` into the project (`app.py` is the well-log starter with quick-look net pay, `seismic_app.py` the cube viewer starter; keep the one that fits and name it `app.py`), then copy the helper modules it imports from `scripts/` (`subsurface_utils.py`, `subsurface_plots.py`, and `seismic_attributes.py` or `ask_data.py` if used) next to `app.py`. Copying keeps the app self-contained so it runs on another machine and deploys from its own repository.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Order of work: load one real file and show one plot; then add controls; then add derived results. Run the app after every step. A blank page with a traceback is easier to fix one feature at a time.

## The rerun model and caching

Streamlit reruns the whole script on every widget change. Anything slow must be cached or the app becomes unusable:

```python
@st.cache_data          # returns a copy per call: for DataFrames, arrays, computed results
def load_well(name): ...

@st.cache_resource      # returns the same object: for connections, memory-mapped cubes, models
def cube_and_meta(): return load_cube("data/survey")
```

- Cache every file read, every query, every attribute computation. Arguments are the cache key, so pass the well name or attribute name, not a large array.
- Convert data before the app starts (`las_to_parquet.py`, `segy_to_npy.py`, `fetch_factpages.py`). The app reads Parquet, `.npy` and cached CSV only.
- No network calls in the main script path. If a download is unavoidable, cache it to disk and check the file first.
- When data is missing, show the exact command to produce it and call `st.stop()`, rather than failing with a traceback.
- Widget state that must reset when the selection changes needs a key that includes the selection: `st.slider(..., key=f"interval_{well}")`.

## Layout that works for subsurface apps

- `st.set_page_config(layout="wide")` always: log tracks and sections need the width.
- Sidebar: what to look at (well, line, field) and global parameters. Put rarely changed parameters in `st.sidebar.expander`.
- A row of `st.metric` for the three to five numbers that summarise the selection.
- `st.tabs` for views of the same selection (logs, quick-look, crossplot, QC, map). Tabs all execute on every rerun, so keep each cheap or cached.
- A caption under each result saying what it shows and its limits ("quick-look only, measured-depth thickness"). Domain experts trust an app that states its assumptions.
- Default to the most interesting item (a well with a full curve set, a line through the structure), never an empty state.
- Keep metric labels short and put units in the label; long values are truncated with an ellipsis.

## Plots

Use `subsurface_plots.py`:

| Function | For |
|---|---|
| `log_plot(df, tracks, tops, flag, lithology)` | Multi-track log display, depth down, standard scales, optional tops, shaded flag intervals and lithology strip |
| `crossplot(df, x, y, color)` | Scatter crossplots (NPHI-RHOB, with colour by GR or depth) |
| `seismic_section(data2d, x, samples, clip)` | Vertical section with clipped symmetric colour scale |
| `seismic_slice(data2d, ilines, xlines, clip)` | Time or depth slice in map view |

Add to a returned figure with normal Plotly calls (`fig.add_trace(go.Scatter(...))` for a horizon line or a well path). Standard track scales live in `TRACK_STYLE`; extend it for new curves instead of styling ad hoc.

Curves that share a track keep their own scales (RHOB 1.95 to 2.95 with NPHI 0.45 to -0.15, the overlay that shows gas crossover). `log_plot` maps each onto the first curve's axis and puts the true value in the hover text.

## Maps

- Points on a base map: `go.Scattermap` or `px.scatter_map` with `map_style="carto-positron"`. **Set the centre explicitly** (`fig.update_layout(map_center=dict(lat=..., lon=...))`); with only a zoom the view can open on the wrong part of the world.
- Base-map tiles need internet; the data points do not. For a fully offline demo, plot longitude against latitude on plain axes or draw a coastline from a local file.
- Convert projected coordinates first: `utm_to_latlon(x, y, epsg)`. North Sea data is mostly ED50 / UTM 31N (EPSG:23031).
- For seismic and local grids, plot in inline/crossline or UTM on plain axes with equal aspect, not on a web map.

## Things that broke in practice

Each of these cost time while building the demos in this repository:

- **`fig.add_hrect` / `add_hline` in a loop is very slow** on multi-track figures (about 0.1 s per call, so minutes for a few hundred intervals). Build a list of shape dicts with `xref="paper", yref="y"` and assign once with `fig.update_layout(shapes=...)`. `log_plot` does this.
- **`go.Scattergl` line traces rendered blank inside multi-track subplots.** Use `go.Scatter` with decimation for log tracks. WebGL is fine for a single large scatter (crossplot).
- **`use_container_width=True` is deprecated**; use `width="stretch"` on `st.plotly_chart`, `st.dataframe` and buttons.
- **pandas 3 string columns** are a dedicated `str` dtype, not `object`. Test with `pd.api.types.is_numeric_dtype` / `is_string_dtype` instead of `dtype == object`.
- **Heatmaps with more than about a million cells** stall the browser. `seismic_section` strides the array down to at most 1500 x 1500.
- **Summaries over a whole well** (net pay, average porosity) are nonsense. Always give a zone or depth interval control, and warn when it covers everything.
- **Windows consoles** raise `UnicodeEncodeError` on Norwegian letters; set `PYTHONIOENCODING=utf-8` for scripts that print data.

## Testing and screenshots

Headless smoke test of the whole app, fast enough to run after every change:

```python
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=120).run()
assert not at.exception
at.selectbox[0].select_index(3).run()      # drive a widget, check again
assert not at.exception
```

Give `AppTest.from_file` an absolute path (`str(Path(__file__).parent / "app.py")`); a relative one is resolved against the calling file and fails from a scratch script.

`AppTest` executes the script but does not render charts, so it cannot see a blank or mis-scaled plot. Look at the app as well:

```bash
python scripts/screenshot_app.py app.py shots/      # starts the app, clicks every tab, saves one PNG per tab
```

Then read the images. It needs `pip install playwright` and `python -m playwright install chromium` once. Two of the bugs listed above were only visible this way.

## Deploying

- **Streamlit Community Cloud**: free, deploys from a public GitHub repository with `requirements.txt` at the root. Data must be fetched or bundled small: commit only tiny derived files (a cropped `.npy`, a Parquet of a few wells) whose licence allows redistribution, with attribution.
- **Secrets**: API keys go in the platform's secrets settings or `.streamlit/secrets.toml` (git-ignored), read with `st.secrets` or the environment. Never in code.
- **Local demo**: `streamlit run app.py` on the presenter's laptop is the most reliable option. Have it running before presenting.

## When Streamlit is the wrong tool

| Need | Use |
|---|---|
| Fine callback control, partial updates, many linked plots | Dash (same Plotly figures, so `subsurface_plots.py` carries over) |
| Polished multi-page product, custom interaction (drawing picks on seismic), many users | FastAPI backend + React front end; serve slices as arrays or images from the same `.npy` cubes |
| Very large seismic in the browser | Server-side slicing and image tiles; dedicated viewers |
| Notebook-first exploration | Jupyter with the same helper modules |
