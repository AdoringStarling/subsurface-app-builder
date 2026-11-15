# Open data for the Norwegian continental shelf

Where to get real subsurface data, what each source contains, and its licence. Download before an event and work from local copies.

## Contents
- FactPages (Norwegian Offshore Directorate)
- Well logs: FORCE 2020
- Seismic: Volve and other open surveys
- Reports and text
- Diskos
- Licences and attribution
- Joining the sources

## FactPages (Norwegian Offshore Directorate)

The public register of the shelf: every wellbore, field, discovery, licence, company and facility, plus production and reserves. Each table is a single CSV download.

```bash
python scripts/fetch_factpages.py --list                 # the 24 tables known to the script
python scripts/fetch_factpages.py --core                 # starter set of 7 tables
python scripts/fetch_factpages.py --all --out data/factpages   # everything, about 40 MB
```

Files are cached and reused for 30 days, with a one-second pause between requests. The whole set is 24 requests; never fetch inside an app rerun.

URL pattern, should a table not in the script be needed (names follow the table views on factpages.sodir.no):

```
https://factpages.sodir.no/public?/Factpages/external/tableview/<table>&rs:Command=Render&rc:Toolbar=false&rc:Parameters=f&IpAddress=not_used&CultureCode=en&rs:Format=CSV&Top100=false
```

Load with the helpers, which deal with the quirks below:

```python
from subsurface_utils import read_factpages, factpages_duckdb
df = read_factpages("data/factpages/field.csv")
con = factpages_duckdb("data/factpages")        # all cached tables in DuckDB, about 2 s
```

### Tables that matter most

| Table | Rows | Use |
|---|---|---|
| `wellbore_exploration_all` | 2 200 | One row per exploration wellbore: position (`wlbNsDecDeg`, `wlbEwDecDeg`), dates, total depth, water depth, content, age and formation at TD, operator, discovery |
| `wellbore_development_all` | larger | Production and injection wells with field and facility |
| `wellbore_formation_top` | 41 500 | Lithostratigraphic tops per wellbore: `lsuTopDepth`, `lsuBottomDepth`, `lsuName`, `lsuLevel` |
| `field` | 142 | Status, operator, area, hydrocarbon type, discovery well |
| `field_production_monthly` | 28 500 | Oil, gas, NGL, condensate, oil equivalents, produced water per field and month |
| `field_reserves` | 2 300 | Recoverable and remaining volumes per field **per year version** |
| `field_description` | 710 | Free text per field under five headings: Development, Reservoir, Recovery strategy, Transport, Status |
| `discovery` | 650 | Discovery year, hydrocarbon type, activity status |
| `wellbore_document` | 10 500 | Links to completion reports and other PDFs per wellbore |
| `wellbore_dst`, `wellbore_core`, `wellbore_mud`, `wellbore_casing_and_lot` | | Tests, cores, mud weights, casing and leak-off tests |
| `wellbore_history` | | Free-text drilling history per wellbore (HTML) |

### Quirks

- **Units**: oil, NGL, condensate and oil equivalents in million Sm3; gas in billion Sm3; produced water in million Sm3. 1 Sm3 oil is about 6.29 barrels.
- **Dates** are `dd.mm.yyyy` strings; `read_factpages` parses columns with `date` in the name.
- **Strings are padded** with trailing spaces in some columns (`'TOR FM              '`); `read_factpages` strips them.
- **Column names keep the source's typos**: `fldCurrentActivitySatus`, `wlbMaxInclation`. Copy names from the file, do not retype from memory.
- **Production tables name the field in `prfInformationCarrier`** (upper case), not `fldName`.
- **`field_reserves` has one row per field per `fldVersion`**. Take the latest version per field or totals are multiplied.
- **Casing differs between tables**: `North sea` in `field`, `NORTH SEA` in wellbore tables. Compare with `ILIKE` or `.str.upper()`.
- **Encoding** is UTF-8 with a BOM (`encoding="utf-8-sig"`). Norwegian letters (ø, å, æ) appear in names; on Windows set `PYTHONIOENCODING=utf-8` when printing to a console.
- **Keys**: join on the NPDID columns (`wlbNpdidWellbore`, `fldNpdidField`, `dscNpdidDiscovery`), which are stable, rather than on names.
- Positions are in ED50. The difference from WGS84 is on the order of 100 m, invisible on a shelf-scale map, relevant when overlaying on seismic.

FactMaps (factmaps.sodir.no) and the directorate's ArcGIS REST services hold the geometries (licence blocks, field outlines, structural elements) when a map needs polygons.

## Well logs: FORCE 2020

118 wells from the Norwegian North Sea with standard log suites and interpreted lithology, released for the FORCE 2020 machine-learning competition.

- Source: Zenodo record 4351156, `LAS_files_Force_2020_all_wells_train_test_blind_hidden_final.zip` (170 MB), plus spreadsheets of lithostratigraphic group and formation tops and casing depths.
- Every well has GR, RHOB, NPHI, deep resistivity, DTC and caliper; shear sonic (DTS) in 46 wells; PEF in 88.
- Extra curves: `FORCE_2020_LITHOFACIES_LITHOLOGY` (12 classes, coded) with a confidence curve, and `X_LOC`, `Y_LOC`, `Z_LOC` positions in ED50 / UTM 31N.
- Real defects are present (washouts, gaps, spliced runs), which makes it good for QC demos.
- Cite: Bormann P., Aursand P., Dilib F., Dischington P., Manral S. (2020). FORCE 2020 Well well log and lithofacies dataset for machine learning competition. doi:10.5281/zenodo.4351156.

## Seismic: Volve and other open surveys

- **Volve** (Equinor, North Sea, block 15/9): a complete released field dataset, about 40 000 files: seismic (ST0202, ST10010), well logs, reports, production, reservoir models. The full set is terabytes, obtained through Equinor's data portal after accepting the licence.
- **Volve sub-cube for quick work**: the segysak examples include `volve10r12-full-twt-sub3d.sgy` (45 MB, 61 x 202 traces, 850 samples at 4 ms, time-migrated), a Hugin Formation top horizon as `x y twt`, and the deviation of well F-12. Small enough to commit to nothing and download in seconds.
- Not Norwegian but open and commonly used: **F3** (Dutch North Sea, about 1 GB) and **Kerry-3D** (New Zealand, about 1 GB) via the SEG wiki open data page; **Penobscot** (Canada); **Poseidon** (Australia).
- The **Smeaheia** and **Sleipner** CO2 storage datasets (co2datashare.org) include seismic and models under open licences.

## Reports and text

- `wellbore_document` in FactPages links completion reports and other PDFs per wellbore; download the few needed, not the whole list.
- Zenodo record 10775273: a large text corpus extracted from public Norwegian, UK and Dutch oil and gas documents (CC-BY-4.0). The Diskos reports file alone is 5.7 GB of CSV; the Norwegian relinquishment reports file is 25 MB and a far better starting point.
- Scanned older reports need OCR; expect tables to come out badly. Vision-capable LLMs read report pages (as images or PDF) more reliably than OCR plus text parsing, at higher token cost, so use them on selected pages.

## Diskos

Diskos is Norway's national data repository for seismic, well and production data, run for the Norwegian Offshore Directorate. Full access is for member companies; released data becomes public after the confidentiality period (normally two years for well data, and `wlbReleasedDate` in FactPages gives the date). At hackathons the organisers typically provide an extract.

A question-and-answer benchmark built from Diskos reports for testing language models on subsurface knowledge has been described publicly (about 1100 question-answer pairs). Its format was not verified when this was written. When handed an unfamiliar dataset like this, profile it before designing anything: file types and sizes, a schema and row count per table (`duckdb.sql("DESCRIBE SELECT * FROM 'file.csv'")`), a handful of sample records, the licence, and what key joins it to wellbores or fields.

## Licences and attribution

| Data | Licence | Attribution line |
|---|---|---|
| FactPages and other directorate open data | NLOD 2.0 | "Contains data from the Norwegian Offshore Directorate (NLOD 2.0)" |
| FORCE 2020 well logs | CC-BY-4.0 on Zenodo; underlying data NLOD 2.0 | Cite Bormann et al. (2020), doi:10.5281/zenodo.4351156 |
| Volve | Equinor Open Data Licence | "Volve data, Equinor Open Data Licence" plus a link to the licence |
| Zenodo 10775273 text corpus | CC-BY-4.0 | Cite the record |

Keep data out of the code repository: add `data/` to `.gitignore` and ship a download script. The licences allow reuse with attribution, but large binary files make a repository unusable and redistribution terms differ per dataset.

## Joining the sources

The wellbore name is the common key: `15/9-13` (quadrant/block-well number, optional suffixes `S`, `A`, `T2` for sidetracks and re-entries).

- LAS file names often replace `/` with `_` and may append a field name: normalise with `name.split(" ")[0].replace("_", "/")`.
- FactPages: `wlbWellboreName` in wellbore tables, `wlbName` in tops, tests and document tables.
- From a wellbore you reach its field (`fldNpdidField`), discovery (`dscNpdidDiscovery`), tops, tests, documents and position, and with position, any seismic that covers it.

That chain (log file, wellbore facts, tops, field, production) is what makes cross-domain apps possible with open data alone.
