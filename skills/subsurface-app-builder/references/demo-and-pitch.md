# Showing the work: short demos and open repos

Read this when the app will be presented (hackathon, review meeting, client demo) or published.

## Build order that always leaves something to show

1. **Hour 0-1: thin end-to-end slice.** One real file loaded, one plot on screen, running app. Commit.
2. **Then one "aha" feature.** The single thing that makes a domain expert lean in (a QC flag that catches a real washout, a question answered from public data in seconds, a horizon that follows the fault). Everything else is supporting.
3. **Then robustness on the demo path.** The exact files and clicks that will be shown must work every time. Other paths can stay rough.
4. **Last: polish and README.** Stop adding features with enough time left to rehearse.

Commit at every working state. A demo falls back to the last good commit, never to "it worked an hour ago".

## Demo-proofing checklist

- Works offline: data is local, converted to Parquet/npy, no live downloads during the demo. Conference and office networks fail under load.
- Starts in under 10 seconds: heavy loading is behind `st.cache_data` / `st.cache_resource` and has been warmed by one run before presenting.
- LLM features degrade gracefully: if the API key is missing or the call fails, the app still runs and shows a clear message. Keep one saved example answer to show if the network is down.
- Sensible defaults: the app opens on the most interesting well, line or field, not an empty state.
- Text is readable from the back of a room: wide layout, large fonts, few widgets visible at once.
- A screen recording (60-90 s) of the working demo exists as a backup.

## A 4-minute presentation

| Time | Content |
|---|---|
| 0:00-0:30 | The problem, as one concrete situation a geoscientist or engineer recognises. Who has it, what it costs. |
| 0:30-2:45 | Live demo of one user journey, on real data. Say what the data is. Show the "aha" feature by 1:30. |
| 2:45-3:30 | How it works in one picture: data in, processing, model (if any), app. What is real and what is mocked. |
| 3:30-4:00 | What comes next, and the repo link on screen. |

Rules that keep it inside the time: no slides before the demo beyond one title slide; no live typing of long prompts (paste them); no installation or login on stage; one presenter drives.

Be honest about limits. "Quick-look only, not calibrated to core" earns more trust from domain experts than an overclaim, and they will spot the overclaim.

## Open repository checklist

- `README.md`: one-paragraph pitch, screenshot or GIF, how to run in three commands, data sources with licences, limitations, credits.
- `LICENSE` file (MIT or Apache-2.0 for code).
- Data is **not** committed. `data/` is in `.gitignore`; a download script and the licence of each dataset are in the repo. Check redistribution terms before committing any derived data.
- No secrets: API keys come from environment variables or `.streamlit/secrets.toml` (git-ignored). Search history before making the repo public: `git log -p | grep -i -E "sk-ant|api[_-]?key"`.
- Pinned dependencies (`requirements.txt` or `pyproject.toml`).
- Attribution lines for data, for example: "Contains data from the Norwegian Offshore Directorate, NLOD 2.0" and "Volve data, Equinor Open Data Licence".

## Being a good guest on shared resources

- Download large datasets before the event and work from local copies. Sixty people pulling the same gigabytes will take a venue network down.
- Cache every remote request. Never fetch inside a Streamlit rerun without a cache.
- Shared LLM budgets: develop against the cheapest model that works, cache prompts, send summaries and schemas to the model rather than raw data. See `llm-features.md`.
