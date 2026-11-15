"""ask_data.py with a scripted stand-in for the model: checks the tool loop, SQL guard and usage totals."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "subsurface-app-builder" / "scripts"))
import ask_data  # noqa: E402


class FakeClient:
    """Replays a list of responses and records the requests it was sent."""

    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.messages = NS(create=self._create)

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})  # snapshot: the caller keeps appending
        return self.responses.pop(0)


def usage():
    return NS(input_tokens=100, output_tokens=20, cache_read_input_tokens=50, cache_creation_input_tokens=0)


def tool_call(sql, id_="t1"):
    return NS(stop_reason="tool_use", usage=usage(), content=[NS(type="tool_use", id=id_, name="run_sql", input={"sql": sql})])


def final(text):
    return NS(stop_reason="end_turn", usage=usage(), content=[NS(type="text", text=text)])


def make_con():
    con = duckdb.connect()
    con.register("_f", pd.DataFrame({"name": ["A", "B", "C"], "oil": [3.0, 10.0, 1.5], "status": ["Producing", "Shut down", "Producing"]}))
    con.execute("CREATE TABLE fields AS SELECT * FROM _f")
    return con


def test_schema_prompt_is_stable_and_lists_values():
    con = make_con()
    p = ask_data.schema_prompt(con, "note")
    assert p == ask_data.schema_prompt(con, "note")  # byte-identical, so the prompt cache hits
    assert '"fields" (3 rows)' in p and "Producing | Shut down" in p


def test_loop_runs_sql_and_returns_answer():
    con = make_con()
    client = FakeClient([tool_call("SELECT name FROM fields ORDER BY oil DESC LIMIT 1"), final("B has produced the most oil.")])
    out = ask_data.ask(con, "Which field produced most?", "sys", client=client)
    assert out["answer"] == "B has produced the most oil."
    assert out["queries"][0][1]["name"].tolist() == ["B"]
    assert out["usage"] == {"input": 200, "output": 40, "cache_read": 100, "cache_write": 0}
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "t1" and "B" in result["content"]
    assert client.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_write_statements_are_rejected_and_reported_to_model():
    con = make_con()
    client = FakeClient([tool_call("DROP TABLE fields"), tool_call("SELECT 1; DELETE FROM fields", "t2"), final("ok")])
    out = ask_data.ask(con, "delete it", "sys", client=client)
    assert all(df is None for _, df in out["queries"])
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True
    assert con.execute("SELECT count(*) FROM fields").fetchone()[0] == 3


def test_sql_error_is_returned_not_raised():
    df, text = ask_data.run_sql(make_con(), "SELECT nope FROM fields")
    assert df is None and text.startswith("SQL error")


def test_gives_up_after_max_turns():
    con = make_con()
    client = FakeClient([tool_call("SELECT 1", f"t{i}") for i in range(ask_data.MAX_TURNS)])
    out = ask_data.ask(con, "loop", "sys", client=client)
    assert "too many" in out["answer"] and len(out["queries"]) == ask_data.MAX_TURNS
