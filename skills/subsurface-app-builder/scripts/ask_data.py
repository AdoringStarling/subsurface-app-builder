"""Natural-language questions over tables in DuckDB, answered by Claude writing SQL.

The model never sees the data itself, only the schema (cached) and at most MAX_ROWS rows of
each query result, so a question costs a few thousand tokens however large the tables are.

Use from an app:
    from ask_data import ask, schema_prompt
    result = ask(con, "Which five fields have produced the most oil?", system=schema_prompt(con, notes))
    result["answer"], result["queries"]  # text, [(sql, DataFrame), ...]

Or from the shell (FactPages tables cached by fetch_factpages.py):
    python ask_data.py "Which five fields have produced the most oil?" --data data/factpages

Credentials come from the environment (ANTHROPIC_API_KEY or an `ant auth login` profile).
"""
from __future__ import annotations

import json
import os
import re

import pandas as pd

MODEL = os.environ.get("SUBSURFACE_LLM_MODEL", "claude-opus-5-5")
MAX_ROWS = 40          # rows of each result shown to the model
MAX_TURNS = 8          # tool round-trips per question
_READ_ONLY = re.compile(r"^\s*(select|with|describe|show|summarize|pragma\s+table_info)\b", re.I)

SQL_TOOL = {
    "name": "run_sql",
    "description": "Run one read-only DuckDB SQL query against the tables described in the system prompt "
                   "and get the first rows back as CSV. Aggregate in SQL; do not fetch raw rows to add up yourself.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "A single SELECT (or WITH ... SELECT) statement."}},
        "required": ["sql"],
        "additionalProperties": False,
    },
}

INSTRUCTIONS = """You answer questions about tabular data by querying it with the run_sql tool (DuckDB dialect).

How to work:
- Query before answering. Never state a number that did not come from a query result.
- Quote identifiers exactly as listed, in double quotes. String matching is case sensitive: use ILIKE when unsure of casing.
- If a result is empty or surprising, check the distinct values of the column you filtered on and retry.
- Keep the final answer short: the answer first, with units, then one line on how it was computed if not obvious.
- Say so plainly when the tables cannot answer the question.
"""


def schema_prompt(con, notes: str = "", sample_values: int = 8) -> str:
    """Deterministic description of every table: columns, types, example values of low-cardinality text columns.

    The text is stable across calls (sorted tables, no timestamps), so the prompt cache hits.
    """
    parts = [INSTRUCTIONS]
    if notes:
        parts.append("Notes on this dataset:\n" + notes.strip())
    parts.append("Tables:")
    for (table,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
        n = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        cols = con.execute(f'DESCRIBE "{table}"').fetchall()
        lines = []
        for name, ctype, *_ in cols:
            extra = ""
            if ctype == "VARCHAR":
                distinct = con.execute(f'SELECT count(DISTINCT "{name}") FROM "{table}"').fetchone()[0]
                if 0 < distinct <= sample_values * 3:
                    vals = [r[0] for r in con.execute(
                        f'SELECT DISTINCT "{name}" FROM "{table}" WHERE "{name}" IS NOT NULL ORDER BY 1 LIMIT {sample_values}').fetchall()]
                    extra = " e.g. " + " | ".join(str(v)[:40] for v in vals)
            lines.append(f"  {name} {ctype}{extra}")
        parts.append(f'\n"{table}" ({n} rows)\n' + "\n".join(lines))
    return "\n".join(parts)


def run_sql(con, sql: str) -> tuple[pd.DataFrame | None, str]:
    """Execute a read-only query. Returns (frame, text for the model)."""
    if not _READ_ONLY.match(sql) or ";" in sql.strip().rstrip(";"):
        return None, "Rejected: only a single read-only SELECT statement is allowed."
    try:
        df = con.execute(sql).df()
    except Exception as e:  # the error text lets the model fix its own query
        return None, f"SQL error: {e}"
    head = df.head(MAX_ROWS)
    note = f"\n({len(df)} rows in total, first {MAX_ROWS} shown)" if len(df) > MAX_ROWS else f"\n({len(df)} rows)"
    return df, head.to_csv(index=False)[:6000] + note


def ask(con, question: str, system: str, history: list | None = None, model: str = MODEL,
        effort: str = "low", client=None) -> dict:
    """Answer one question. `history` is the earlier messages list returned as result["messages"]."""
    import anthropic

    client = client or anthropic.Anthropic()
    messages = list(history or []) + [{"role": "user", "content": question}]
    queries: list[tuple[str, pd.DataFrame | None]] = []
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=[SQL_TOOL],
            output_config={"effort": effort},
            messages=messages,
        )
        u = response.usage
        usage["input"] += u.input_tokens
        usage["output"] += u.output_tokens
        usage["cache_read"] += u.cache_read_input_tokens or 0
        usage["cache_write"] += u.cache_creation_input_tokens or 0
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "refusal":
            return {"answer": "The model declined to answer this request.", "queries": queries, "usage": usage, "messages": messages}
        if response.stop_reason != "tool_use":
            break
        results = []
        for block in response.content:
            if block.type == "tool_use":
                sql = block.input.get("sql", "") if isinstance(block.input, dict) else ""
                df, text = run_sql(con, sql)
                queries.append((sql, df))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": df is None})
        messages.append({"role": "user", "content": results})

    answer = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "tool_use":
        answer = answer or "Stopped after too many query attempts without reaching an answer."
    elif response.stop_reason == "max_tokens":
        answer += "\n\n(Answer cut off at the output limit.)"
    return {"answer": answer, "queries": queries, "usage": usage, "messages": messages}


FACTPAGES_NOTES = """Norwegian Offshore Directorate FactPages (Norwegian continental shelf).
- Volumes: oil, NGL, condensate and oil equivalents in million Sm3; gas in billion Sm3; produced water in million Sm3.
- field_production_monthly / _yearly: the field name is in prfInformationCarrier (upper case).
- field_reserves has one row per field per fldVersion (year); use the latest fldVersion per field for current figures.
- Column names keep the source's spelling, including typos: fldCurrentActivitySatus, wlbMaxInclation.
- Area names differ in casing between tables ('North sea' in field, 'NORTH SEA' in wellbores): compare with ILIKE.
- Wellbore names look like '15/9-13' (quadrant/block-well). wlbNsDecDeg / wlbEwDecDeg are latitude / longitude (ED50).
- Depths are metres measured depth relative to the kelly bushing unless the column says otherwise.
- wellbore_formation_top: lsuLevel is GROUP, FORMATION, MEMBER or SUBGROUP; names end in ' GP', ' FM', ' MBR'.
"""

if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from subsurface_utils import factpages_duckdb

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--data", default="data/factpages")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--show-prompt", action="store_true", help="print the system prompt and exit (no API call)")
    a = ap.parse_args()
    con = factpages_duckdb(a.data)
    system = schema_prompt(con, FACTPAGES_NOTES)
    if a.show_prompt:
        print(system)
        sys.exit()
    out = ask(con, a.question, system, model=a.model)
    for sql, df in out["queries"]:
        print("SQL>", sql)
    print("\n" + out["answer"])
    print("\ntokens:", json.dumps(out["usage"]))
