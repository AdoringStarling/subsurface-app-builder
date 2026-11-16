# Project ideas

Ideas sized for one person (or a small team) in about two days, all buildable from open data. Use this when the user asks what to build, or to suggest an extension to an existing app. Each entry gives the data, the smallest version worth showing, and the moment that lands in a demo.

When choosing, prefer an idea where (a) the data is already on disk, (b) the "aha" appears within the first day, and (c) the user has domain knowledge that makes the result credible.

## Well logs

**1. Log QC copilot.** Load any LAS, harmonise mnemonics, flag washouts, unit errors, gaps and spikes, and write a short QC report.
- Data: FORCE 2020 wells (118 wells with real defects).
- One-day cut: `inspect_las.py` output rendered as a per-well scorecard plus a log plot with flagged intervals shaded.
- Stretch: an LLM writes the QC summary from the JSON (cheap, a few hundred tokens per well).
- Demo moment: drop in a messy file and get a scorecard in seconds.

**2. Lithology prediction with honest uncertainty.** Train gradient boosting on the FORCE 2020 labels, show predicted lithology beside the logs with class probabilities, validated on blind wells.
- Data: FORCE 2020 LAS (contains `FORCE_2020_LITHOFACIES_LITHOLOGY` labels).
- One-day cut: train on about 80 wells, hold out whole wells, show a confusion matrix and a per-well lithology track.
- Demo moment: predicted vs interpreted lithology side by side on a well the model never saw.
- Trap: split by well, never by random sample, or the score is inflated.

**3. Missing-log synthesis.** Predict sonic (DTC/DTS) or density where it was not run, from the other curves.
- One-day cut: one target curve, blind-well validation, plot predicted over measured.
- Demo moment: hide a measured curve, regenerate it, reveal the overlay.

**4. Mnemonic harmoniser.** Map the thousands of vendor curve names to standard families using the alias table first and an LLM for the remainder (name + unit + description + value statistics as input).
- Demo moment: a folder with 40 different names for gamma ray collapses to one column.

**5. Quick-look pay finder.** Batch Vsh/porosity/Sw/net pay across all wells with adjustable cutoffs, ranked table, click through to the log plot.
- Demo moment: move the Sw cutoff and watch the ranking change live.

## Seismic

**6. Browser seismic viewer with attributes.** Inline/crossline/time-slice navigation over a memory-mapped cube, with envelope, instantaneous phase, RMS amplitude and a simple discontinuity attribute.
- Data: Volve sub-cube (45 MB), F3 or Kerry for larger volumes.
- Demo moment: toggle from amplitude to discontinuity and the faults appear.

**7. Seed-and-grow horizon picker.** Click a reflector, auto-track it across the volume by local cross-correlation, export the surface.
- One-day cut: track on one inline, then extend line to line.
- Demo moment: one click becomes a mapped surface, compared with an interpreter's horizon (the Volve sample includes one).

**8. SEG-Y header doctor.** Diagnose awkward SEG-Y: find inline/crossline bytes, coordinate scalars, sample format, and explain the text header in plain language.
- Demo moment: a file that will not load elsewhere is diagnosed in one command.

## Public shelf data (FactPages)

**9. Ask the shelf.** Natural-language questions over FactPages tables: the LLM writes SQL for DuckDB, the app runs it and charts the result.
- One-day cut: five tables, schema in a cached system prompt, read-only SQL, show the SQL for transparency.
- Demo moment: "Which fields have produced more than 100 million Sm3 of oil and are still producing?" answered with a chart in a few seconds.

**10. Analogue finder.** Given a discovery or prospect description (age, formation, depth, fluid, area), rank the most similar fields and wells.
- One-day cut: feature table from `field`, `discovery`, `wellbore_exploration_all`, nearest neighbours, map of results.

**11. Production decline dashboard.** Monthly production per field with fitted Arps decline, remaining reserves vs reported reserves, water-cut trend.
- Demo moment: fitted forecast against the official remaining reserves number.

**12. Exploration history explorer.** Wells through time on a map: success rates by play, age at TD, operator; an animation by year.
- Demo moment: play the timeline and watch exploration move north.

**13. CO2 storage or late-life screening.** Rank fields nearing end of life by depth, reservoir, pressure regime and infrastructure for reuse.
- Trap: be explicit that this is screening from public attributes only.

## Documents and language

**14. Completion report to structured data.** Extract tops, casing points, tests and shows from well completion reports (PDF) into tables, with page citations, and compare against FactPages values.
- Data: report links in the `wellbore_document` table; download a handful beforehand.
- Demo moment: an extracted value shown next to the official one, with the source page.

**15. Field briefing generator.** One-page briefing for any field from `field_description`, production, reserves and wells, with every number traceable to a table.

**16. Subsurface Q&A evaluation.** If a domain Q&A benchmark is provided (for example one built from Diskos reports), build a small harness comparing models or retrieval strategies, with a results dashboard.
- Demo moment: a leaderboard showing where retrieval helps and where it does not.

## Time-lapse seismic and drilling

**19. What changed? 4D screening tool.** Load two vintages, check they are comparable, match them, and produce maps of amplitude change and time shift at the reservoir with the noise floor stated. See `time-lapse-seismic.md`.
- Data: two vintages from the organisers, Sleipner 4D (large; crop first), or `make_synthetic.py --monitor`.
- One-day cut: sections with a base, monitor and difference toggle, plus one change map.
- Demo moment: tick "align monitor to base" and the false difference below the reservoir disappears.
- Extension: a language model writes a short interpretation from the map statistics and the production history of the field.

**20. Geosteering replay and assistant.** Replay a horizontal well as it was drilled: fit formation dips to the LWD gamma ray, show the curtain section, and say where to steer. See `geosteering.md`.
- Data: a horizontal well with survey and LWD log plus an offset well, Geosteering World Cup data, or `make_synthetic.py --geosteer`.
- One-day cut: the "drilled to" slider, the curtain section and the in-zone percentage.
- Demo moment: drill ahead, the gamma ray rises, the app shows the bit leaving the sand and proposes a new inclination.
- Extension: compare the automatic interpretation with a human one; add resistivity; score a whole well by metres in zone.

## Cross-domain

**17. Well-to-seismic tie.** Synthetic seismogram from sonic and density, displayed beside the seismic trace at the well location, with a stretch/shift control.
- Data: Volve (logs, deviation and seismic cover the same area). Needs a time-depth relation; start from integrated sonic.

**18. Well card.** For any wellbore name: FactPages facts, formation tops, log plot if a LAS exists, nearby wells on a map. A single place joining three data types.
- Demo moment: type a well name and everything public about it appears on one page.
