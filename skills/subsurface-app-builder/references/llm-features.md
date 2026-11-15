# Adding a language model to a subsurface app

Read this before putting an LLM call in an app. The rules are the same whether the budget is a shared hackathon pool or a company account: send the model descriptions and small results, never raw data, and make the app work when the model is unavailable.

For exact, current API details (model IDs, parameters, pricing) consult the `claude-api` skill or the provider documentation rather than memory; this file covers design.

## Where a model earns its place

| Good use | Why |
|---|---|
| Questions over tables (text to SQL) | The model writes a query; the database does the work. Bundled as `scripts/ask_data.py` |
| Naming and mapping (curve mnemonics, formation name variants) | Small inputs, fuzzy matching, cheap |
| Extraction from report pages into a fixed schema | Vision models read scanned tables better than OCR pipelines |
| Writing a summary from computed numbers | Pass the JSON of results; the model writes prose |

| Poor use | Do this instead |
|---|---|
| Computing porosity, averages, picks from numbers in the prompt | Compute in code; give the model the result |
| Reading a LAS or SEG-Y file | `inspect_las.py` / `inspect_segy.py` output |
| Interpreting a seismic image for faults or horizons | Attributes and tracking algorithms; the model can explain the result |
| Anything that must be exactly reproducible | Deterministic code |

## Keep tokens down

1. **Summaries, not data.** A curve table from `inspect_las.py` is about 1 000 tokens; the file it describes is millions. Send schemas, statistics and at most a few dozen rows.
2. **Cache the stable prefix.** Put instructions and schemas first in the system prompt and mark it for caching; keep it byte-identical between calls (sorted tables, no timestamps). Repeat questions then pay about a tenth for that part. `ask_data.schema_prompt` is built this way. Check `usage.cache_read_input_tokens` is non-zero on the second call.
3. **Pick the model per task.** Lookups, naming and simple extraction run well on the small, cheap model tier; multi-step reasoning over a messy schema may need a larger one. Make the model a setting (environment variable or a selector), develop on the cheap tier, and move up only where results show the need.
4. **Cap the loop.** Limit tool round-trips per question (`MAX_TURNS`) and rows returned per query (`MAX_ROWS`).
5. **Cache answers during development.** Wrap calls in `st.cache_data` keyed on the prompt while iterating on the interface, so every rerun is not a paid request.
6. **Batch offline work.** Classifying 500 curve names is one batched job before the app starts, not 500 calls at run time.

## Text to SQL with `ask_data.py`

```python
import ask_data
from subsurface_utils import factpages_duckdb

con = factpages_duckdb("data/factpages")
con.execute("SET enable_external_access = false")        # queries cannot read files or the network
system = ask_data.schema_prompt(con, ask_data.FACTPAGES_NOTES)
out = ask_data.ask(con, "Which five fields have produced the most oil?", system)
out["answer"]; out["queries"]; out["usage"]; out["messages"]   # pass messages back as history for follow-ups
```

Design points worth keeping when adapting it:

- **Dataset notes** (`FACTPAGES_NOTES`) carry what the schema cannot: units, which column holds the field name, versioned tables, casing differences. Most wrong answers come from a missing note; add one when a question fails.
- **Example values** for low-cardinality text columns are in the schema prompt so filters use real spellings.
- **Read-only guard**: a single SELECT only, on an in-memory copy, with external access disabled. Errors go back to the model as tool results so it can correct the query.
- **Show the SQL** next to every answer. A domain expert can check a query; nobody can check an unexplained number.
- **Numbers come from results.** The instructions forbid stating a figure that no query returned.

Try the questions you will demo beforehand and keep the ones that work reliably as example buttons.

## Extraction from documents

- Send only the relevant pages (find them by keyword search over extracted text first).
- Ask for a fixed JSON schema with a `page` and a short `quote` for every extracted value, and show both in the app. Values without a quote are not trusted.
- Compare extracted values with a reference where one exists (FactPages has official total depth, tops and test results). Agreement rate is a convincing demo number.

## Failure handling

- Missing credentials: the feature shows a short message and the other parts of the app keep working. Check for the key before drawing the input box.
- Wrap the call in `try/except` and show the error text in place of the answer; a demo must survive a rate limit or a network drop.
- Check the stop reason: a response can end because the output limit was hit or the request was declined, and the content is then incomplete or empty.
- Keep one recorded good answer (screenshot or saved result) for presenting if the network is down.

## Credentials

Read keys from the environment (`ANTHROPIC_API_KEY`) or the platform's secret store. Keep `.env` and `.streamlit/secrets.toml` in `.gitignore`, and search the history for keys before making a repository public. When a cloud platform (for example Microsoft Foundry or Amazon Bedrock) provides the models, use that platform's client class and model names; the rest of the code is unchanged.
