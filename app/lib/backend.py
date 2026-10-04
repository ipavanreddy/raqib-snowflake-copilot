"""
Raqib app backend.

Two interchangeable implementations behind one interface:
  * SnowflakeBackend - Streamlit in Snowflake (active session) or local/Community Cloud with
                       credentials in st.secrets. Uses the real Cortex Agent, stored-procedure
                       tools, dynamic tables and Cortex Search.
  * OfflineBackend   - no Snowflake: rebuilds the same pipeline from the same SQL in DuckDB
                       (localdev/engine.py) and runs the same tool code with a template LLM.
                       Powers the public demo link and local development.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
AGENT_PATH = "/api/v2/databases/RAQIB/schemas/AI/agents/RAQIB_COPILOT:run"


# =====================================================================================
# Agent response parsing (shared)
# =====================================================================================
def parse_agent_events(events: list[dict]) -> dict:
    """Normalise Cortex Agent SSE events into {text, tools, sql, citations, tables}."""
    out = {"text": "", "tools": [], "sql": [], "citations": [], "tables": [], "thinking": ""}
    final = None
    for ev in events:
        name, data = ev.get("event"), ev.get("data") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {"text": data}
        if name == "response.text.delta":
            out["text"] += data.get("text", "")
        elif name == "response.thinking.delta":
            out["thinking"] += data.get("text", "")
        elif name == "response.tool_use":
            out["tools"].append({"name": data.get("name"), "type": data.get("type"), "input": data.get("input")})
        elif name == "response.tool_result":
            for c in data.get("content", []):
                j = c.get("json") or {}
                if isinstance(j, dict) and j.get("sql"):
                    out["sql"].append(j["sql"])
                for r in (j.get("searchResults") or j.get("search_results") or []) if isinstance(j, dict) else []:
                    out["citations"].append({"title": r.get("doc_title") or r.get("DOC_TITLE"),
                                             "id": r.get("doc_id") or r.get("CHUNK_ID"),
                                             "text": (r.get("text") or r.get("CHUNK") or "")[:400]})
        elif name == "response.text.annotation":
            ann = data.get("annotation", data)
            out["citations"].append({"title": ann.get("doc_title"), "id": ann.get("doc_id"),
                                     "text": (ann.get("text") or "")[:400]})
        elif name == "response.table":
            rs = (data.get("result_set") or {})
            cols = [c.get("name") for c in (rs.get("resultSetMetaData", {}).get("rowType") or [])]
            if cols:
                out["tables"].append(pd.DataFrame(rs.get("data", []), columns=cols))
        elif name == "response":
            final = data
        elif name == "error":
            out["error"] = data.get("message") or json.dumps(data)
    if final and not out["text"]:
        out["text"] = "\n".join(c.get("text", "") for c in final.get("content", []) if c.get("type") == "text")
    return out


def parse_sse(text: str) -> list[dict]:
    events, cur = [], {}
    for line in text.splitlines():
        if line.startswith("event:"):
            cur["event"] = line[6:].strip()
        elif line.startswith("data:"):
            cur["data"] = cur.get("data", "") + line[5:].strip()
        elif not line.strip() and cur:
            events.append(cur)
            cur = {}
    if cur:
        events.append(cur)
    return events


# =====================================================================================
# Snowflake
# =====================================================================================
class SnowflakeBackend:
    mode = "snowflake"

    def __init__(self, session, in_sis: bool):
        self.session = session
        self.in_sis = in_sis

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        return self.session.sql(sql, params=params or []).to_pandas()

    def execute(self, sql: str, params: list | None = None) -> None:
        self.session.sql(sql, params=params or []).collect()

    def tool(self, proc: str, *args) -> dict:
        res = self.session.call(f"RAQIB.OPS.{proc}", *args)
        return json.loads(res) if isinstance(res, str) else res

    def search(self, query: str, limit: int = 4) -> list[dict]:
        payload = json.dumps({"query": query, "columns": ["CHUNK_ID", "DOC_ID", "DOC_TITLE", "SECTION", "CHUNK"], "limit": limit})
        r = self.session.sql("SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('RAQIB.DOCS.POLICY_SEARCH', ?) AS R", params=[payload]).collect()
        return json.loads(r[0]["R"]).get("results", [])

    def agent(self, messages: list[dict]) -> dict:
        body = {"messages": messages, "stream": True}
        if self.in_sis:
            import _snowflake  # available in the Streamlit-in-Snowflake warehouse runtime
            resp = _snowflake.send_snow_api_request("POST", AGENT_PATH, {}, {}, body, None, 180000)
            if resp["status"] >= 400:
                return {"error": f"Agent API {resp['status']}: {str(resp.get('content'))[:300]}"}
            content = resp["content"]
            events = json.loads(content) if content.lstrip().startswith("[") else parse_sse(content)
            return parse_agent_events(events)
        import requests
        cfg = st.secrets["snowflake"]
        account = cfg["account"].replace("_", "-").lower()
        token = cfg.get("pat") or cfg.get("password")
        r = requests.post(f"https://{account}.snowflakecomputing.com{AGENT_PATH}", json=body, timeout=180,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                   "Accept": "text/event-stream",
                                   "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN"})
        if r.status_code >= 400:
            return {"error": f"Agent API {r.status_code}: {r.text[:300]}"}
        return parse_agent_events(parse_sse(r.text))

    def simulate(self, scenario: str) -> dict:
        return self.tool("SIMULATE_ACTIVITY", scenario)

    def audit_copilot(self, persona, question, result, latency_ms):
        self.execute("""INSERT INTO RAQIB.OPS.COPILOT_AUDIT (INTERACTION_ID, EVENT_TS, ACTOR, PERSONA, SURFACE, QUESTION,
                        ANSWER, TOOLS_USED, SQL_EXECUTED, CITATIONS, LATENCY_MS)
                        SELECT ?, CURRENT_TIMESTAMP(), CURRENT_USER(), ?, 'streamlit', ?, ?, PARSE_JSON(?), PARSE_JSON(?), PARSE_JSON(?), ?""",
                     [uuid.uuid4().hex, persona, question, result.get("text", "")[:16000],
                      json.dumps(result.get("tools", [])), json.dumps(result.get("sql", [])),
                      json.dumps(result.get("citations", [])), latency_ms])


# =====================================================================================
# Offline (DuckDB)
# =====================================================================================
class OfflineBackend:
    mode = "offline"

    def __init__(self):
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / "tools"))
        from localdev import engine  # noqa: E402
        import raqib_tools  # noqa: E402

        data = ROOT / "data" / "generated"
        if not (data / "transactions.csv").exists():
            import subprocess
            subprocess.run([sys.executable, str(ROOT / "data_gen" / "generate.py"), "--out", str(data)], check=True)
        self.engine, self.T = engine, raqib_tools
        db_dir = data / f"app_{os.getpid()}"  # file must be named raqib.duckdb: DuckDB catalog = file stem
        db_dir.mkdir(exist_ok=True)
        self.con = engine.build_full(str(db_dir / "raqib.duckdb"))
        self.be = engine.LocalBackend(self.con, llm=None)
        from lib.offline_copilot import baseline_notifications
        baseline_notifications(self)

    def df(self, sql: str, params: list | None = None) -> pd.DataFrame:
        out = self.con.execute(self.engine.to_duckdb(sql), params or []).df().rename(columns=str.upper)
        for c in out.columns:  # DuckDB returns DATE as midnight timestamps; show them as dates like Snowflake does
            if pd.api.types.is_datetime64_any_dtype(out[c]) and len(out[c].dropna()) and (out[c].dropna().dt.normalize() == out[c].dropna()).all():
                out[c] = out[c].dt.date
        return out

    def execute(self, sql: str, params: list | None = None) -> None:
        self.con.execute(self.engine.to_duckdb(sql), params or [])

    def tool(self, proc: str, *args) -> dict:
        fn = getattr(self.T, proc.lower())
        return json.loads(json.dumps(fn(self.be, *args), default=str))

    def search(self, query: str, limit: int = 4) -> list[dict]:
        return self.be.search(query, limit)

    def agent(self, messages: list[dict]) -> dict:
        from lib.offline_copilot import answer
        return answer(self, messages[-1]["content"][0]["text"])

    def simulate(self, scenario: str) -> dict:
        from lib.offline_copilot import simulate
        return simulate(self, scenario)

    def audit_copilot(self, persona, question, result, latency_ms):
        self.execute("""INSERT INTO RAQIB.OPS.COPILOT_AUDIT (INTERACTION_ID, EVENT_TS, ACTOR, PERSONA, SURFACE, QUESTION, ANSWER,
                        TOOLS_USED, SQL_EXECUTED, CITATIONS, LATENCY_MS)
                        SELECT ?, CURRENT_TIMESTAMP, 'offline-demo', ?, 'streamlit-offline', ?, ?, ?, ?, ?, ?""",
                     [uuid.uuid4().hex, persona, question, result.get("text", "")[:16000], json.dumps(result.get("tools", [])),
                      json.dumps(result.get("sql", [])), json.dumps(result.get("citations", [])), latency_ms])


# =====================================================================================
@st.cache_resource(show_spinner="Connecting to Raqib…")
def get_backend():
    if os.environ.get("RAQIB_OFFLINE") != "1":
        try:
            from snowflake.snowpark.context import get_active_session
            return SnowflakeBackend(get_active_session(), in_sis=True)
        except Exception:  # noqa: BLE001 - not running inside Snowflake
            pass
        try:
            if "snowflake" in st.secrets:
                from snowflake.snowpark import Session
                return SnowflakeBackend(Session.builder.configs(dict(st.secrets["snowflake"])).create(), in_sis=False)
        except Exception:  # noqa: BLE001 - no secrets / bad credentials -> offline demo
            pass
    return OfflineBackend()


@st.cache_resource
def _data_version() -> dict:
    """Process-wide data version: any write bumps it so every session sees fresh data."""
    return {"v": 0}


def q(sql: str, params: list | None = None) -> pd.DataFrame:
    """Cached read, invalidated globally by invalidate() after writes."""
    return _cached_q(sql, tuple(params or []), _data_version()["v"])


@st.cache_data(show_spinner=False, ttl=300)
def _cached_q(sql: str, params: tuple, version: int) -> pd.DataFrame:
    return get_backend().df(sql, list(params))


def invalidate():
    _data_version()["v"] += 1


def timed(fn, *args):
    t = time.time()
    out = fn(*args)
    return out, int((time.time() - t) * 1000)
