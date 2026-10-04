"""
Local engine: executes the Snowflake pipeline SQL against the generated CSVs in DuckDB.

Snowflake SQL is transpiled with sqlglot. Object bodies are extracted using the repo
convention (header ... a line that is exactly "AS" ... ";"). Dynamic tables are
materialised as DuckDB tables, views as views. This lets us test detection logic,
recall on planted cases and false-positive volume before any Snowflake account exists.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import json

import duckdb
import sqlglot

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "generated"
SQL_DIR = ROOT / "sql"

RAW_TABLES = ["customers", "accounts", "counterparties", "transactions", "digital_events", "loans",
              "liquidity_daily", "country_risk", "watchlist", "planted_cases"]

OBJ_RE = re.compile(
    r"CREATE OR REPLACE (?P<kind>DYNAMIC TABLE|VIEW|SECURE VIEW)\s+(?P<name>[A-Z0-9_.]+)(?P<hdr>.*?)\nAS\n(?P<body>.*?);\s*$",
    re.S | re.M,
)
INSERT_RE = re.compile(r"INSERT INTO (?P<name>RAQIB\.[A-Z_.]+) VALUES\s*(?P<vals>.*?);\s*$", re.S | re.M)
TABLE_RE = re.compile(r"CREATE OR REPLACE TABLE (?P<name>RAQIB\.[A-Z_.]+) \((?P<cols>.*?)\)\s*COMMENT", re.S)


def to_duckdb(sql: str) -> str:
    # Snowflake-only DT hint: DYNAMIC_TABLE_REFRESH_BOUNDARY(view) -> view
    sql = re.sub(r"DYNAMIC_TABLE_REFRESH_BOUNDARY\(\s*([A-Za-z0-9_.]+)\s*\)", r"\1", sql)
    # Keep METRICS a uniform type across UNION ALL branches.
    sql = re.sub(r"OBJECT_CONSTRUCT\(", "TO_JSON(OBJECT_CONSTRUCT(", sql)
    sql = _close_object_construct(sql)
    out = sqlglot.transpile(sql, read="snowflake", write="duckdb")[0]
    return out


def _close_object_construct(sql: str) -> str:
    """Add the extra ')' for each TO_JSON(OBJECT_CONSTRUCT( we introduced."""
    res, i = [], 0
    marker = "TO_JSON(OBJECT_CONSTRUCT("
    while True:
        j = sql.find(marker, i)
        if j < 0:
            res.append(sql[i:])
            break
        res.append(sql[i:j + len(marker)])
        depth, k = 1, j + len(marker)
        while depth:
            ch = sql[k]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "'":
                k = sql.index("'", k + 1)
            k += 1
        res.append(sql[j + len(marker):k] + ")")
        i = k
    return "".join(res)


def connect(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    db_path = db_path or str(DATA / "raqib.duckdb")
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)  # catalog name = "raqib"
    for s in ["RAW", "CORE", "DETECT", "RISK", "OPS", "DOCS", "AI"]:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
    con.execute("CREATE OR REPLACE MACRO jarowinkler_similarity(a, b) AS CAST(ROUND(jaro_winkler_similarity(a, b) * 100) AS INTEGER)")
    con.execute("CREATE OR REPLACE MACRO count_if_(x) AS SUM(CASE WHEN x THEN 1 ELSE 0 END)")
    for t in RAW_TABLES:
        con.execute(f"CREATE TABLE RAW.{t.upper()} AS SELECT * FROM read_csv_auto('{DATA / (t + '.csv')}', header=true, all_varchar=false, sample_size=-1)")
    # Align with Snowflake load (empty string -> NULL is default in read_csv for non-strings; force for strings)
    for t, cols in {"COUNTERPARTIES": ["INTERNAL_ACCOUNT_ID"], "TRANSACTIONS": ["COUNTERPARTY_ID", "BRANCH_ID", "PURPOSE_CODE"]}.items():
        for c in cols:
            con.execute(f"UPDATE RAW.{t} SET {c} = NULL WHERE CAST({c} AS VARCHAR) = ''")
    con.execute("ALTER TABLE RAW.TRANSACTIONS ALTER TXN_TS TYPE TIMESTAMP")
    con.execute("ALTER TABLE RAW.DIGITAL_EVENTS ALTER EVENT_TS TYPE TIMESTAMP")
    return con


def run_file(con, filename: str, verbose=False):
    text = (SQL_DIR / filename).read_text()
    # catalog tables + seed inserts
    for m in TABLE_RE.finditer(text):
        cols = []
        for line in m.group("cols").splitlines():
            line = line.split("--")[0].strip().rstrip(",")
            if not line:
                continue
            parts = line.split()
            cols.append(f"{parts[0]} {('VARCHAR' if parts[1].startswith('VARCHAR') else 'DOUBLE' if parts[1].startswith('NUMBER') else parts[1])}")
        con.execute(f"CREATE OR REPLACE TABLE {m.group('name')} ({', '.join(cols)})")
    for m in INSERT_RE.finditer(text):
        con.execute(to_duckdb(f"INSERT INTO {m.group('name')} VALUES {m.group('vals')}"))
    for m in OBJ_RE.finditer(text):
        name, kind, body = m.group("name"), m.group("kind"), m.group("body")
        sql = to_duckdb(body)
        if verbose:
            print(f"-- {kind} {name}")
        ddl = "TABLE" if kind == "DYNAMIC TABLE" else "VIEW"
        try:
            con.execute(f"CREATE OR REPLACE {ddl} {name} AS {sql}")
        except Exception as e:  # surface the transpiled SQL for debugging
            raise RuntimeError(f"{name} failed: {e}\n---\n{sql}") from e


def build_all(verbose=False):
    con = connect()
    for f in ["03_core_pipeline.sql", "04_detection.sql", "05_risk_reporting.sql"]:
        if (SQL_DIR / f).exists():
            run_file(con, f, verbose)
    return con



# ====================================================================================
# OPS tables + LocalBackend (DuckDB stand-in for tools/raqib_tools.SnowflakeBackend)
# ====================================================================================
TYPE_MAP = {"VARIANT": "JSON", "TIMESTAMP_NTZ": "TIMESTAMP", "FLOAT": "DOUBLE"}


def create_ops_tables(con):
    text = (SQL_DIR / "07_case_management_and_tools.sql").read_text()
    text = text.replace("CREATE TABLE IF NOT EXISTS", "CREATE OR REPLACE TABLE")
    for m in TABLE_RE.finditer(text):
        cols = []
        for line in m.group("cols").splitlines():
            line = line.split("--")[0].strip().rstrip(",")
            if not line:
                continue
            name, typ = line.split()[:2]
            typ = TYPE_MAP.get(typ, "VARCHAR" if typ.startswith("VARCHAR") else "DOUBLE" if typ.startswith("NUMBER") else typ)
            cols.append(f"{name} {typ}")
        con.execute(f"CREATE OR REPLACE TABLE {m.group('name')} ({', '.join(cols)})")
    con.execute("INSERT INTO RAQIB.OPS.SETTINGS VALUES ('LLM_MODEL', 'stub-model'), ('FALLBACK_MODEL', 'stub-fallback')")
    view = re.search(r"CREATE OR REPLACE VIEW RAQIB\.OPS\.ALERT_QUEUE.*?\nAS\n(.*?);", text, re.S).group(1)
    con.execute("CREATE OR REPLACE VIEW RAQIB.OPS.ALERT_QUEUE AS " + sqlglot.transpile(view, read="snowflake", write="duckdb")[0])
    con.execute("CREATE OR REPLACE MACRO parse_json(x) AS CAST(x AS JSON)")


class LocalBackend:
    def __init__(self, con, llm=None, roles=("RAQIB_ADMIN", "RAQIB_MLRO", "RAQIB_ANALYST")):
        self.con = con
        self.llm = llm
        self.roles = set(roles)
        self.chunks = self._load_chunks()

    def _sql(self, sql):
        return sqlglot.transpile(sql, read="snowflake", write="duckdb")[0]

    def query(self, sql, params=None):
        cur = self.con.execute(self._sql(sql), params or [])
        cols = [d[0] for d in cur.description]
        out = []
        for row in cur.fetchall():
            d = {}
            for k, v in zip(cols, row):
                if isinstance(v, str) and v[:1] in "{[":
                    try:
                        v = json.loads(v)
                    except ValueError:
                        pass
                d[k.upper()] = v
            out.append(d)
        return out

    def execute(self, sql, params=None):
        self.con.execute(self._sql(sql), params or [])

    def whoami(self):
        return "LOCAL_TEST_USER", sorted(self.roles)[0]

    def has_role(self, role):
        return role in self.roles

    # keyword retrieval over policy_docs sections (stands in for Cortex Search)
    def _load_chunks(self):
        chunks = []
        for md in sorted((ROOT / "policy_docs").glob("*.md")):
            text = md.read_text()
            doc_id = re.search(r"doc_id:\s*(\S+)", text).group(1)
            title = re.search(r"title:\s*(.+)", text).group(1).strip()
            for i, sec in enumerate(re.split(r"\n(?=#{2,3} )", text)):
                head = re.match(r"#{1,3} (.+)", sec.strip())
                chunks.append({"CHUNK_ID": f"{doc_id}#{i:03d}", "DOC_ID": doc_id, "DOC_TITLE": title,
                               "SECTION": head.group(1) if head else "General", "CHUNK": sec.strip()})
        return chunks

    def search(self, query, limit=4):
        terms = [t for t in re.findall(r"[a-z0-9,]+", query.lower()) if len(t) > 2]
        scored = sorted(self.chunks, key=lambda c: -sum(c["CHUNK"].lower().count(t) for t in terms))
        return scored[:limit]

    def complete(self, prompt, model, schema=None):
        if self.llm is None:
            raise RuntimeError("LLM unavailable (stub)")
        return self.llm(prompt, model, schema)


def build_full(db_path: str | None = None):
    """Pipeline + OPS tables: everything the app and tools need, locally."""
    con = build_all() if db_path is None else _build_at(db_path)
    create_ops_tables(con)
    return con


def _build_at(db_path):
    con = connect(db_path)
    for f in ["03_core_pipeline.sql", "04_detection.sql", "05_risk_reporting.sql"]:
        run_file(con, f)
    return con
