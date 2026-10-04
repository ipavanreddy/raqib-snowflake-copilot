"""
Raqib agent tools.

One module, two runtimes:
  * Snowflake: registered as Python stored procedures (sql/07_tools.sql) and exposed to the
    Cortex Agent as custom tools. `SnowflakeBackend` wraps the Snowpark session and uses
    SNOWFLAKE.CORTEX.SEARCH_PREVIEW + AI_COMPLETE.
  * Local tests: `tests/` passes a DuckDB-backed backend with a stub LLM and keyword search,
    so the business logic and guardrails are unit-tested without a Snowflake account.

Every tool returns a JSON-serialisable dict and writes an audit record.

Guardrails implemented here (not just prompted):
  - evidence-only drafting: the LLM only sees retrieved evidence and policy passages
  - amount reconciliation: every AED amount in a generated narrative must match evidence
  - citation check: cited chunk IDs must be among the retrieved passages
  - tipping-off filter: narratives that suggest informing the subject are rejected
  - workflow rules: closure needs a rationale; only the MLRO can approve / file
  - graceful fallback: deterministic template narrative if the LLM is unavailable
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime
from decimal import Decimal

DEFAULT_MODEL = "claude-sonnet-4-5"
FALLBACK_MODEL = "llama3.3-70b"

VALID_ALERT_STATUSES = {"NEW", "IN_REVIEW", "ESCALATED", "CLOSED_FALSE_POSITIVE", "CLOSED_NO_ACTION"}
CLOSING_STATUSES = {"CLOSED_FALSE_POSITIVE", "CLOSED_NO_ACTION"}
MIN_RATIONALE_CHARS = 25
TIPPING_OFF_PATTERNS = [
    r"\b(inform|notify|tell|alert|advise|warn)\w*\s+(the\s+)?(customer|client|subject|account holder)\b.{0,40}\b(str|report|suspicion|investigation)",
    r"\blet\s+(the\s+)?(customer|client|subject)\s+know\b",
]

RULE_POLICY_QUERIES = {
    "TM-01": "cash structuring deposits below AED 55,000 reporting threshold",
    "TM-02": "rapid pass-through layering funds forwarded within 48 hours",
    "TM-03": "money mule fan-in many unrelated senders new account",
    "TM-04": "high-risk jurisdiction prohibited FATF call for action payments",
    "TM-05": "dormant account reactivation 180 days",
    "TM-06": "sanctions watchlist name match freeze without delay",
    "TM-07": "activity inconsistent with expected monthly turnover profile",
    "FR-01": "account takeover new device beneficiary added password reset",
}


# =====================================================================================
# Backends
# =====================================================================================
def _jsonable(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


class SnowflakeBackend:
    """Runs inside a Snowflake stored procedure (Snowpark session)."""

    def __init__(self, session):
        self.session = session

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        rows = self.session.sql(sql, params=params or []).collect()
        return [{k: _jsonable(v) for k, v in r.as_dict().items()} for r in rows]

    def execute(self, sql: str, params: list | None = None) -> None:
        self.session.sql(sql, params=params or []).collect()

    def whoami(self) -> tuple[str, str]:
        r = self.session.sql("SELECT CURRENT_USER() AS U, CURRENT_ROLE() AS R").collect()[0]
        return r["U"], r["R"]

    def has_role(self, role: str) -> bool:
        return bool(self.session.sql("SELECT IS_ROLE_IN_SESSION(?) AS OK", params=[role]).collect()[0]["OK"])

    def search(self, query: str, limit: int = 4) -> list[dict]:
        payload = json.dumps({"query": query, "columns": ["CHUNK_ID", "DOC_ID", "DOC_TITLE", "SECTION", "CHUNK"],
                              "limit": limit})
        r = self.session.sql("SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('RAQIB.DOCS.POLICY_SEARCH', ?) AS R",
                             params=[payload]).collect()[0]["R"]
        return json.loads(r).get("results", [])

    def complete(self, prompt: str, model: str, schema: dict | None = None) -> str:
        if schema:
            sql = (f"SELECT AI_COMPLETE(model => ?, prompt => ?, "
                   f"model_parameters => {{'temperature': 0, 'max_tokens': 4096, 'guardrails': TRUE}}, "
                   f"response_format => {_sql_object_literal({'type': 'json', 'schema': schema})}) AS R")
        else:
            sql = ("SELECT AI_COMPLETE(model => ?, prompt => ?, "
                   "model_parameters => {'temperature': 0, 'max_tokens': 4096, 'guardrails': TRUE}) AS R")
        r = self.session.sql(sql, params=[model, prompt]).collect()[0]["R"]
        return r if isinstance(r, str) else json.dumps(r)


def _sql_object_literal(obj) -> str:
    """Python value -> Snowflake semi-structured literal ({'k': v}, [..])."""
    if isinstance(obj, dict):
        return "{" + ", ".join(f"'{k}': {_sql_object_literal(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ", ".join(_sql_object_literal(v) for v in obj) + "]"
    if isinstance(obj, bool):
        return "TRUE" if obj else "FALSE"
    if isinstance(obj, (int, float)):
        return str(obj)
    return "'" + str(obj).replace("'", "''") + "'"


# =====================================================================================
# Helpers
# =====================================================================================
def _new_id(prefix: str) -> str:
    return f"{prefix}-{datetime.utcnow():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _audit(be, action: str, object_type: str, object_id: str, details: dict):
    user, role = be.whoami()
    be.execute(
        "INSERT INTO RAQIB.OPS.AUDIT_LOG (EVENT_ID, EVENT_TS, ACTOR, ACTOR_ROLE, ACTION, OBJECT_TYPE, OBJECT_ID, DETAILS) "
        "SELECT ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, PARSE_JSON(?)",
        [uuid.uuid4().hex, user, role, action, object_type, object_id, json.dumps(details, default=str)])


def _setting(be, key: str, default: str) -> str:
    rows = be.query("SELECT VALUE FROM RAQIB.OPS.SETTINGS WHERE KEY = ?", [key])
    return rows[0]["VALUE"] if rows else default


def _fmt_aed(x) -> str:
    return f"AED {float(x):,.2f}"


# =====================================================================================
# Read tools
# =====================================================================================
def get_alert_evidence(be, alert_id: str, max_txns: int = 50) -> dict:
    alerts = be.query("""
        SELECT a.ALERT_ID, a.RULE_ID, a.RULE_NAME, a.TYPOLOGY, a.SEVERITY, a.CUSTOMER_ID, a.ACCOUNT_ID,
               a.WINDOW_START, a.WINDOW_END, a.AMOUNT_AED, a.TXN_COUNT, a.METRICS, a.TRIGGER_SUMMARY,
               a.POLICY_REFERENCE, rc.LOGIC_SUMMARY, COALESCE(w.STATUS, 'NEW') AS STATUS
        FROM RAQIB.DETECT.ALERTS a
        JOIN RAQIB.DETECT.RULE_CATALOG rc ON rc.RULE_ID = a.RULE_ID
        LEFT JOIN RAQIB.OPS.ALERT_WORKFLOW w ON w.ALERT_ID = a.ALERT_ID
        WHERE a.ALERT_ID = ?""", [alert_id])
    if not alerts:
        return {"ok": False, "error": f"Alert {alert_id} not found. Use the alert queue to find valid IDs."}
    alert = alerts[0]
    txns = be.query("""
        SELECT TXN_ID, TXN_TS, DIRECTION, CHANNEL, AMOUNT, CURRENCY, AMOUNT_AED, COUNTERPARTY_NAME,
               COUNTERPARTY_COUNTRY, COUNTERPARTY_COUNTRY_RISK, BRANCH_ID, DESCRIPTION
        FROM RAQIB.DETECT.ALERT_EVIDENCE WHERE ALERT_ID = ? ORDER BY TXN_TS LIMIT ?""", [alert_id, max_txns])
    profile = be.query("""
        SELECT CUSTOMER_ID, FULL_NAME, CUSTOMER_TYPE, SEGMENT, NATIONALITY, OCCUPATION, INDUSTRY, TENURE_DAYS,
               KYC_RISK_RATING, PEP_FLAG, EXPECTED_MONTHLY_TURNOVER_AED, KYC_REVIEW_OVERDUE, DAYS_SINCE_KYC_REVIEW
        FROM RAQIB.CORE.CUSTOMER_PROFILE WHERE CUSTOMER_ID = ?""", [alert["CUSTOMER_ID"]])
    out = {"ok": True, "alert": alert, "customer": profile[0] if profile else None,
           "evidence_transactions": txns, "evidence_count": len(txns),
           "evidence_total_aed": round(sum(float(t["AMOUNT_AED"]) for t in txns), 2)}
    _audit(be, "VIEW_EVIDENCE", "ALERT", alert_id, {"evidence_count": len(txns)})
    return out


def get_customer_360(be, customer_id: str) -> dict:
    risk = be.query("SELECT * FROM RAQIB.DETECT.CUSTOMER_RISK WHERE CUSTOMER_ID = ?", [customer_id])
    if not risk:
        return {"ok": False, "error": f"Customer {customer_id} not found."}
    alerts = be.query("""SELECT ALERT_ID, RULE_ID, RULE_NAME, SEVERITY, AMOUNT_AED, WINDOW_START, WINDOW_END, TRIGGER_SUMMARY
                         FROM RAQIB.DETECT.ALERTS WHERE CUSTOMER_ID = ? ORDER BY BASE_SCORE DESC""", [customer_id])
    accounts = be.query("""SELECT ACCOUNT_ID, IBAN, ACCOUNT_TYPE, CURRENCY, OPEN_DATE, STATUS, HOME_BRANCH
                           FROM RAQIB.RAW.ACCOUNTS WHERE CUSTOMER_ID = ?""", [customer_id])
    loans = be.query("""SELECT LOAN_ID, PRODUCT, EAD_AED, DAYS_PAST_DUE, IFRS9_STAGE, ECL_AED
                        FROM RAQIB.RISK.LOAN_ECL WHERE CUSTOMER_ID = ?""", [customer_id])
    top_cp = be.query("""
        SELECT COUNTERPARTY_NAME, COUNTERPARTY_COUNTRY, COUNTERPARTY_COUNTRY_RISK, DIRECTION,
               COUNT(*) AS TXNS, ROUND(SUM(AMOUNT_AED), 2) AS TOTAL_AED
        FROM RAQIB.CORE.TXN_ENRICHED
        WHERE CUSTOMER_ID = ? AND COUNTERPARTY_NAME IS NOT NULL
        GROUP BY COUNTERPARTY_NAME, COUNTERPARTY_COUNTRY, COUNTERPARTY_COUNTRY_RISK, DIRECTION
        ORDER BY TOTAL_AED DESC LIMIT 8""", [customer_id])
    r = risk[0]
    breakdown = {k: r[k] for k in r if k.startswith("PTS_")}
    _audit(be, "VIEW_CUSTOMER_360", "CUSTOMER", customer_id, {})
    return {"ok": True, "profile": r, "risk_score": r["RISK_SCORE"], "risk_band": r["RISK_BAND"],
            "score_breakdown": breakdown, "alerts": alerts, "accounts": accounts, "loans": loans,
            "top_counterparties": top_cp}


def search_policy(be, query: str, limit: int = 4) -> list[dict]:
    try:
        return be.search(query, limit)
    except Exception as e:  # search outage must not break investigations
        return [{"CHUNK_ID": None, "DOC_TITLE": "Policy search unavailable", "SECTION": "", "CHUNK": str(e)[:200]}]


# =====================================================================================
# Action tools
# =====================================================================================
def update_alert_status(be, alert_id: str, status: str, rationale: str = "", assignee: str | None = None) -> dict:
    status = (status or "").upper().strip()
    if status == "STR_FILED":
        return {"ok": False, "error": "STR_FILED is set only by the MLRO when approving an STR report."}
    if status not in VALID_ALERT_STATUSES:
        return {"ok": False, "error": f"Invalid status '{status}'. Allowed: {sorted(VALID_ALERT_STATUSES)}"}
    if status in CLOSING_STATUSES and len((rationale or "").strip()) < MIN_RATIONALE_CHARS:
        return {"ok": False, "error": f"Closing an alert requires a rationale of at least {MIN_RATIONALE_CHARS} "
                                      "characters referencing the evidence reviewed (TM Rulebook s.2.4)."}
    if not be.query("SELECT 1 AS X FROM RAQIB.DETECT.ALERTS WHERE ALERT_ID = ?", [alert_id]):
        return {"ok": False, "error": f"Alert {alert_id} not found."}
    user, _ = be.whoami()
    be.execute("DELETE FROM RAQIB.OPS.ALERT_WORKFLOW WHERE ALERT_ID = ?", [alert_id])
    be.execute("""INSERT INTO RAQIB.OPS.ALERT_WORKFLOW (ALERT_ID, STATUS, ASSIGNEE, RATIONALE, UPDATED_BY, UPDATED_AT)
                  SELECT ?, ?, ?, ?, ?, CURRENT_TIMESTAMP""", [alert_id, status, assignee or user, rationale, user])
    _audit(be, "UPDATE_ALERT_STATUS", "ALERT", alert_id, {"status": status, "rationale": rationale})
    return {"ok": True, "alert_id": alert_id, "status": status}


def create_case(be, customer_id: str, summary: str, priority: str | None = None) -> dict:
    risk = be.query("SELECT RISK_BAND, RISK_SCORE, FULL_NAME FROM RAQIB.DETECT.CUSTOMER_RISK WHERE CUSTOMER_ID = ?", [customer_id])
    if not risk:
        return {"ok": False, "error": f"Customer {customer_id} not found."}
    open_case = be.query("""SELECT CASE_ID FROM RAQIB.OPS.CASES WHERE CUSTOMER_ID = ?
                            AND STATUS IN ('OPEN', 'PENDING_MLRO')""", [customer_id])
    if open_case:
        return {"ok": True, "case_id": open_case[0]["CASE_ID"], "note": "An open case already exists for this customer; reused it."}
    alerts = be.query("SELECT ALERT_ID FROM RAQIB.DETECT.ALERTS WHERE CUSTOMER_ID = ?", [customer_id])
    priority = (priority or {"CRITICAL": "P1", "HIGH": "P2"}.get(risk[0]["RISK_BAND"], "P3")).upper()
    case_id = _new_id("CASE")
    user, _ = be.whoami()
    be.execute("""INSERT INTO RAQIB.OPS.CASES (CASE_ID, CUSTOMER_ID, STATUS, PRIORITY, SUMMARY, OPENED_BY, OPENED_AT, UPDATED_AT)
                  SELECT ?, ?, 'OPEN', ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP""",
               [case_id, customer_id, priority, summary, user])
    for a in alerts:
        be.execute("INSERT INTO RAQIB.OPS.CASE_ALERTS (CASE_ID, ALERT_ID) SELECT ?, ?", [case_id, a["ALERT_ID"]])
        be.execute("DELETE FROM RAQIB.OPS.ALERT_WORKFLOW WHERE ALERT_ID = ?", [a["ALERT_ID"]])
        be.execute("""INSERT INTO RAQIB.OPS.ALERT_WORKFLOW (ALERT_ID, STATUS, ASSIGNEE, RATIONALE, CASE_ID, UPDATED_BY, UPDATED_AT)
                      SELECT ?, 'ESCALATED', ?, 'Escalated to case', ?, ?, CURRENT_TIMESTAMP""",
                   [a["ALERT_ID"], user, case_id, user])
    _notify(be, "HIGH" if priority != "P1" else "CRITICAL", f"Case {case_id} opened ({priority})",
            f"{risk[0]['FULL_NAME']} ({customer_id}), risk {risk[0]['RISK_SCORE']} {risk[0]['RISK_BAND']}: {summary}", case_id)
    _audit(be, "CREATE_CASE", "CASE", case_id, {"customer_id": customer_id, "alerts": len(alerts), "priority": priority})
    return {"ok": True, "case_id": case_id, "priority": priority, "linked_alerts": len(alerts)}


def _notify(be, severity: str, title: str, body: str, object_id: str):
    be.execute("""INSERT INTO RAQIB.OPS.NOTIFICATIONS (NOTIFICATION_ID, CREATED_AT, CHANNEL, SEVERITY, TITLE, BODY, OBJECT_ID, STATUS)
                  SELECT ?, CURRENT_TIMESTAMP, 'slack', ?, ?, ?, ?, 'PENDING'""",
               [uuid.uuid4().hex, severity, title, body, object_id])


# =====================================================================================
# Report drafting (STR + regulatory)
# =====================================================================================
STR_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "grounds_for_suspicion": {"type": "string"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "grounds_for_suspicion", "red_flags", "recommended_action", "citations"],
}

STR_PROMPT = """You are drafting a Suspicious Transaction Report (STR) narrative for the MLRO of Gulf Horizon Bank.
Write ONLY from the EVIDENCE and POLICY PASSAGES below. Do not invent facts, amounts, dates or names.
Rules:
- Grounds for suspicion: factual, chronological, answering who/what/when/where/why/how (STR Filing Guide s.2.5).
- Every AED amount you mention must appear in the evidence exactly (rounded to 2 decimals or whole AED).
- Compare activity with the KYC profile (occupation/industry, expected monthly turnover).
- Reference the triggered rule IDs and cite policy passages by their chunk_id in "citations".
- Never suggest informing the customer about the report or investigation (tipping-off prohibition).
- Neutral tone; no opinion on guilt.

EVIDENCE (JSON):
{evidence}

POLICY PASSAGES:
{passages}

Return JSON with keys: summary (2-3 sentences), grounds_for_suspicion (markdown paragraphs), red_flags (list),
recommended_action (one paragraph), citations (list of chunk_id strings)."""


def _collect_case_evidence(be, case_id: str) -> dict | None:
    case = be.query("SELECT * FROM RAQIB.OPS.CASES WHERE CASE_ID = ?", [case_id])
    if not case:
        return None
    case = case[0]
    c360 = get_customer_360(be, case["CUSTOMER_ID"])
    alert_ids = [r["ALERT_ID"] for r in be.query("SELECT ALERT_ID FROM RAQIB.OPS.CASE_ALERTS WHERE CASE_ID = ?", [case_id])]
    alerts = [get_alert_evidence(be, a, max_txns=25) for a in alert_ids]
    p = c360["profile"]
    return {
        "case": {"case_id": case_id, "priority": case["PRIORITY"], "summary": case["SUMMARY"]},
        "subject": {k: p.get(k) for k in ["CUSTOMER_ID", "FULL_NAME", "CUSTOMER_TYPE", "SEGMENT", "NATIONALITY",
                                         "OCCUPATION", "INDUSTRY", "KYC_RISK_RATING", "PEP_FLAG", "RISK_SCORE",
                                         "RISK_BAND", "KYC_REVIEW_OVERDUE"]},
        "expected_monthly_turnover_aed": next((a["customer"]["EXPECTED_MONTHLY_TURNOVER_AED"] for a in alerts
                                               if a.get("ok") and a.get("customer")), None),
        "accounts": c360["accounts"],
        "alerts": [{"alert_id": a["alert"]["ALERT_ID"], "rule_id": a["alert"]["RULE_ID"],
                    "rule_name": a["alert"]["RULE_NAME"], "trigger_summary": a["alert"]["TRIGGER_SUMMARY"],
                    "amount_aed": a["alert"]["AMOUNT_AED"], "metrics": a["alert"]["METRICS"],
                    "policy_reference": a["alert"]["POLICY_REFERENCE"],
                    "transactions": a["evidence_transactions"]} for a in alerts if a.get("ok")],
    }


def _evidence_amounts(obj) -> list[float]:
    """All numeric values in the evidence, plus simple aggregates, for reconciliation."""
    nums: list[float] = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums.append(float(v))
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    for a in obj.get("alerts", []):
        tx = a.get("transactions", [])
        for direction in ("CREDIT", "DEBIT", None):
            s = sum(float(t["AMOUNT_AED"]) for t in tx if direction is None or t["DIRECTION"] == direction)
            nums.append(s)
        by_channel: dict = {}
        for t in tx:
            by_channel[t["CHANNEL"]] = by_channel.get(t["CHANNEL"], 0) + float(t["AMOUNT_AED"])
        nums += list(by_channel.values())
    return nums


AMOUNT_RE = re.compile(r"(?:AED|USD)\s?([0-9][0-9,]*(?:\.[0-9]+)?)(?:\s?(k|K|m|M|million)\b)?")


def validate_narrative(text: str, evidence: dict, retrieved_chunk_ids: list[str], cited: list[str]) -> dict:
    known = _evidence_amounts(evidence)
    usd_known = [k / 3.6725 for k in known]
    found, unmatched = [], []
    for m in AMOUNT_RE.finditer(text):
        val = float(m.group(1).replace(",", ""))
        mult = {"k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "million": 1e6}.get(m.group(2) or "", 1)
        val *= mult
        found.append(val)
        tol = max(1.0, 0.005 * val) if mult == 1 else 0.06 * val  # rounded "260k" style allowed ~6%
        policy_constants = {55000, 45000, 54999, 50000, 100000, 200000, 20000}
        if val in policy_constants:
            continue
        pool = usd_known if m.group(0).startswith("USD") else known
        if not any(abs(val - k) <= tol for k in pool):
            unmatched.append(m.group(0).strip())
    bad_cites = [c for c in cited if c not in retrieved_chunk_ids]
    tipping = [p for p in TIPPING_OFF_PATTERNS if re.search(p, text, re.I | re.S)]
    checks = len(found) + len(cited) + 1
    failures = len(unmatched) + len(bad_cites) + (3 if tipping else 0)
    confidence = round(max(0.0, 1 - failures / max(checks, 1)), 2)
    return {"amounts_checked": len(found), "unmatched_amounts": unmatched, "invalid_citations": bad_cites,
            "tipping_off_flags": len(tipping), "has_citations": bool(cited) and not bad_cites,
            "confidence": confidence,
            "passed": not unmatched and not bad_cites and not tipping and bool(cited)}


def _template_str(ev: dict, passages: list[dict]) -> dict:
    """Deterministic fallback when the LLM is unavailable: still evidence-backed and cited."""
    s = ev["subject"]
    lines = []
    for a in ev["alerts"]:
        lines.append(f"- **{a['rule_id']} {a['rule_name']}**: {a['trigger_summary']} (policy: {a['policy_reference']}).")
    return {
        "summary": f"{s['FULL_NAME']} ({s['CUSTOMER_ID']}), a {s.get('OCCUPATION') or s.get('INDUSTRY') or s['CUSTOMER_TYPE'].lower()} "
                   f"rated {s['KYC_RISK_RATING']} risk, triggered {len(ev['alerts'])} monitoring rule(s) with a Raqib risk score of "
                   f"{s['RISK_SCORE']} ({s['RISK_BAND']}).",
        "grounds_for_suspicion": "The following activity was identified by automated monitoring and reviewed:\n\n" + "\n".join(lines)
                                 + f"\n\nDeclared expected monthly turnover: AED {float(ev.get('expected_monthly_turnover_aed') or 0):,.2f}.",
        "red_flags": [a["rule_name"] for a in ev["alerts"]],
        "recommended_action": "MLRO to review the evidence and decide on filing; apply enhanced monitoring; do not inform the subject.",
        "citations": [p["CHUNK_ID"] for p in passages if p.get("CHUNK_ID")][:4],
    }


def draft_str(be, case_id: str) -> dict:
    ev = _collect_case_evidence(be, case_id)
    if not ev:
        return {"ok": False, "error": f"Case {case_id} not found."}
    if not ev["alerts"]:
        return {"ok": False, "error": "Case has no linked alerts; nothing to report."}
    passages, seen = [], set()
    for a in ev["alerts"]:
        for p in search_policy(be, RULE_POLICY_QUERIES.get(a["rule_id"], a["rule_name"]), 2):
            if p.get("CHUNK_ID") and p["CHUNK_ID"] not in seen:
                seen.add(p["CHUNK_ID"])
                passages.append(p)
    for p in search_policy(be, "STR narrative grounds for suspicion structure tipping-off", 2):
        if p.get("CHUNK_ID") and p["CHUNK_ID"] not in seen:
            seen.add(p["CHUNK_ID"])
            passages.append(p)
    passages_txt = "\n\n".join(f"[chunk_id: {p['CHUNK_ID']}] {p.get('DOC_TITLE', '')} / {p.get('SECTION', '')}\n{p.get('CHUNK', '')[:1200]}"
                               for p in passages)
    model = _setting(be, "LLM_MODEL", DEFAULT_MODEL)
    used_model, draft, llm_error = model, None, None
    for m in (model, _setting(be, "FALLBACK_MODEL", FALLBACK_MODEL)):
        try:
            raw = be.complete(STR_PROMPT.format(evidence=json.dumps(ev, default=str)[:60000], passages=passages_txt), m, STR_SCHEMA)
            draft = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(draft, str):
                draft = json.loads(draft)
            used_model = m
            break
        except Exception as e:  # noqa: BLE001 - fall through to next model / template
            llm_error = str(e)[:300]
    if draft is None:
        draft, used_model = _template_str(ev, passages), "template-fallback"
    narrative_text = " ".join([draft.get("summary", ""), draft.get("grounds_for_suspicion", ""),
                               " ".join(draft.get("red_flags", [])), draft.get("recommended_action", "")])
    validation = validate_narrative(narrative_text, ev, [p["CHUNK_ID"] for p in passages], draft.get("citations", []))
    if validation["tipping_off_flags"]:
        draft["recommended_action"] = ("[Removed by guardrail: text suggested informing the subject.] "
                                       "MLRO to decide on filing; do not inform the subject.")
    content_md = render_str_markdown(ev, draft, validation, used_model, passages)
    report_id = _new_id("STR")
    status = "DRAFT" if validation["passed"] else "DRAFT_NEEDS_REVIEW"
    user, _ = be.whoami()
    be.execute("""INSERT INTO RAQIB.OPS.REPORTS (REPORT_ID, REPORT_TYPE, CASE_ID, SUBJECT, STATUS, CONTENT_MD, EVIDENCE,
                      CITATIONS, VALIDATION, CONFIDENCE, MODEL, CREATED_BY, CREATED_AT)
                  SELECT ?, 'STR', ?, ?, ?, ?, PARSE_JSON(?), PARSE_JSON(?), PARSE_JSON(?), ?, ?, ?, CURRENT_TIMESTAMP""",
               [report_id, case_id, ev["subject"]["FULL_NAME"], status, content_md, json.dumps(ev, default=str),
                json.dumps(passages, default=str), json.dumps(validation), validation["confidence"], used_model, user])
    be.execute("UPDATE RAQIB.OPS.CASES SET STATUS = 'PENDING_MLRO', UPDATED_AT = CURRENT_TIMESTAMP WHERE CASE_ID = ?", [case_id])
    _notify(be, "HIGH", f"STR draft {report_id} ready for MLRO",
            f"Case {case_id} — {ev['subject']['FULL_NAME']}; validation {'passed' if validation['passed'] else 'needs review'} "
            f"(confidence {validation['confidence']}).", report_id)
    _audit(be, "DRAFT_STR", "REPORT", report_id, {"case_id": case_id, "model": used_model, "validation": validation,
                                                  "llm_error": llm_error})
    return {"ok": True, "report_id": report_id, "status": status, "model": used_model, "validation": validation,
            "content_md": content_md}


def render_str_markdown(ev, draft, validation, model, passages) -> str:
    s = ev["subject"]
    rows = []
    for a in ev["alerts"]:
        for t in a["transactions"]:
            rows.append(f"| {str(t['TXN_TS'])[:16]} | {t['TXN_ID']} | {t['DIRECTION']} | {t['CHANNEL']} | "
                        f"{float(t['AMOUNT']):,.2f} {t['CURRENCY']} | {float(t['AMOUNT_AED']):,.2f} | "
                        f"{t.get('COUNTERPARTY_NAME') or '-'} | {t.get('COUNTERPARTY_COUNTRY') or '-'} | {a['rule_id']} |")
    seen, uniq = set(), []
    for r in rows:
        key = r.split("|")[2]
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    cites = "\n".join(f"- `{p['CHUNK_ID']}` — {p.get('DOC_TITLE', '')}, {p.get('SECTION', '')}"
                      for p in passages if p.get("CHUNK_ID") in set(draft.get("citations", [])))
    v = validation
    return f"""# Suspicious Transaction Report — DRAFT

**Reporting entity:** Gulf Horizon Bank (fictional) · **Case:** {ev['case']['case_id']} · **Priority:** {ev['case']['priority']}
**Status:** Draft for MLRO review — not filed · **Generated by:** Raqib ({model})

## 1. Subject
| Field | Value |
|---|---|
| Name | {s['FULL_NAME']} |
| Customer ID | {s['CUSTOMER_ID']} |
| Type / segment | {s['CUSTOMER_TYPE']} / {s['SEGMENT']} |
| Nationality | {s['NATIONALITY']} |
| Occupation / industry | {s.get('OCCUPATION') or s.get('INDUSTRY') or '-'} |
| KYC risk rating | {s['KYC_RISK_RATING']} (review overdue: {s['KYC_REVIEW_OVERDUE']}) |
| PEP | {s['PEP_FLAG']} |
| Raqib risk score | {s['RISK_SCORE']} ({s['RISK_BAND']}) |
| Accounts | {', '.join(a['IBAN'] for a in ev['accounts'])} |

## 2. Summary
{draft.get('summary', '')}

## 3. Grounds for suspicion
{draft.get('grounds_for_suspicion', '')}

## 4. Red-flag indicators
{chr(10).join('- ' + f for f in draft.get('red_flags', []))}

## 5. Transactions relied upon
| Timestamp | Txn ID | Dir | Channel | Amount | AED | Counterparty | Country | Rule |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(uniq[:60])}

## 6. Recommended action
{draft.get('recommended_action', '')}

## 7. Policy basis (citations)
{cites or '- (no valid citations — see validation)'}

## 8. Automated validation (Raqib guardrails)
- Amounts reconciled to evidence: {v['amounts_checked'] - len(v['unmatched_amounts'])}/{v['amounts_checked']}{' — unmatched: ' + ', '.join(v['unmatched_amounts']) if v['unmatched_amounts'] else ''}
- Citations valid: {v['has_citations']}{' — invalid: ' + ', '.join(v['invalid_citations']) if v['invalid_citations'] else ''}
- Tipping-off language detected: {'YES (removed)' if v['tipping_off_flags'] else 'No'}
- Confidence: **{v['confidence']}** → {'ready for MLRO review' if v['passed'] else 'analyst must correct before MLRO review'}

> Confidential. Disclosure to the subject is prohibited (tipping-off). Only the MLRO may approve and file this report.
"""


REG_PROMPT = """You are a regulatory reporting analyst at Gulf Horizon Bank. Using ONLY the DATA and POLICY PASSAGES,
write a concise, regulator-ready {title} in markdown with sections: Executive summary, Key metrics, Drivers / analysis,
Policy assessment (cite chunk_ids in square brackets), Actions & escalation. Every number must come from DATA.
DATA (JSON):
{data}
POLICY PASSAGES:
{passages}"""


def generate_regulatory_report(be, report_type: str) -> dict:
    report_type = (report_type or "").upper()
    if report_type == "LCR":
        data = {
            "latest": be.query("SELECT * FROM RAQIB.RISK.LCR_DAILY ORDER BY AS_OF_DATE DESC LIMIT 1"),
            "trough_30d": be.query("""SELECT * FROM RAQIB.RISK.LCR_DAILY
                                      WHERE AS_OF_DATE > (SELECT DATEADD('day', -30, MAX(AS_OF_DATE)) FROM RAQIB.RISK.LCR_DAILY)
                                      ORDER BY LCR_PCT LIMIT 1"""),
            "early_warning_days": be.query("""SELECT AS_OF_DATE, LCR_PCT, HQLA_TOTAL_AED_M, NET_OUTFLOWS_AED_M
                                              FROM RAQIB.RISK.LCR_DAILY WHERE LCR_STATUS <> 'COMPLIANT' ORDER BY AS_OF_DATE"""),
            "baseline_90d_median": be.query("""SELECT MEDIAN(LCR_PCT) AS MEDIAN_LCR_PCT, MEDIAN(HQLA_TOTAL_AED_M) AS MEDIAN_HQLA_AED_M,
                                                      MEDIAN(NET_OUTFLOWS_AED_M) AS MEDIAN_NET_OUTFLOWS_AED_M FROM RAQIB.RISK.LCR_DAILY"""),
        }
        title, q = "Liquidity Coverage Ratio report", "LCR early warning trigger 110% escalation ALCO run-off rates"
    elif report_type == "CREDIT":
        data = {
            "portfolio": be.query("""SELECT ROUND(SUM(EAD_AED), 0) AS EXPOSURE_AED,
                                            ROUND(100 * SUM(IFF(IS_NPL, EAD_AED, 0)) / SUM(EAD_AED), 2) AS NPL_RATIO_PCT,
                                            ROUND(SUM(ECL_AED), 0) AS ECL_AED,
                                            ROUND(100 * SUM(ECL_AED) / SUM(EAD_AED), 2) AS COVERAGE_PCT FROM RAQIB.RISK.LOAN_ECL"""),
            "by_sector": be.query("""SELECT SECTOR, SUM(EXPOSURE_AED) AS EXPOSURE_AED, SUM(NPL_EXPOSURE_AED) AS NPL_AED,
                                            ROUND(100 * SUM(NPL_EXPOSURE_AED) / NULLIF(SUM(EXPOSURE_AED), 0), 2) AS NPL_RATIO_PCT
                                     FROM RAQIB.RISK.CREDIT_PORTFOLIO_SUMMARY GROUP BY SECTOR ORDER BY NPL_RATIO_PCT DESC"""),
            "aml_overlap": be.query("SELECT * FROM RAQIB.RISK.AML_CREDIT_OVERLAP ORDER BY RISK_SCORE DESC LIMIT 10"),
        }
        title, q = "Credit risk & IFRS 9 portfolio report", "NPL ratio risk appetite IFRS 9 staging coverage concentration"
    elif report_type == "AML_MI":
        data = {
            "alerts_by_rule": be.query("""SELECT RULE_ID, RULE_NAME, SEVERITY, COUNT(*) AS ALERTS, ROUND(SUM(AMOUNT_AED), 0) AS AMOUNT_AED
                                          FROM RAQIB.DETECT.ALERTS GROUP BY RULE_ID, RULE_NAME, SEVERITY ORDER BY RULE_ID"""),
            "risk_bands": be.query("SELECT RISK_BAND, COUNT(*) AS CUSTOMERS FROM RAQIB.DETECT.CUSTOMER_RISK GROUP BY RISK_BAND"),
            "workflow": be.query("""SELECT COALESCE(w.STATUS, 'NEW') AS STATUS, COUNT(*) AS ALERTS FROM RAQIB.DETECT.ALERTS a
                                    LEFT JOIN RAQIB.OPS.ALERT_WORKFLOW w ON w.ALERT_ID = a.ALERT_ID GROUP BY 1"""),
            "cases": be.query("SELECT STATUS, COUNT(*) AS CASES FROM RAQIB.OPS.CASES GROUP BY STATUS"),
        }
        title, q = "AML/CFT management information report", "alert triage timelines investigation SLA governance board reporting"
    else:
        return {"ok": False, "error": "report_type must be one of LCR, CREDIT, AML_MI"}
    passages = search_policy(be, q, 3)
    passages_txt = "\n\n".join(f"[chunk_id: {p.get('CHUNK_ID')}] {p.get('DOC_TITLE', '')}\n{p.get('CHUNK', '')[:1200]}" for p in passages)
    model, content, used = _setting(be, "LLM_MODEL", DEFAULT_MODEL), None, None
    for m in (model, _setting(be, "FALLBACK_MODEL", FALLBACK_MODEL)):
        try:
            content = be.complete(REG_PROMPT.format(title=title, data=json.dumps(data, default=str), passages=passages_txt), m)
            used = m
            break
        except Exception:  # noqa: BLE001
            continue
    if content is None:
        used = "template-fallback"
        content = f"# {title}\n\n```json\n{json.dumps(data, default=str, indent=2)}\n```\n"
    validation = validate_narrative(content, {"alerts": [], "data": data}, [p.get("CHUNK_ID") for p in passages],
                                    [c for c in re.findall(r"\[([A-Z]+-[A-Z]+-\d{3}#\d{3})\]", content)])
    report_id = _new_id(report_type)
    user, _ = be.whoami()
    be.execute("""INSERT INTO RAQIB.OPS.REPORTS (REPORT_ID, REPORT_TYPE, CASE_ID, SUBJECT, STATUS, CONTENT_MD, EVIDENCE,
                      CITATIONS, VALIDATION, CONFIDENCE, MODEL, CREATED_BY, CREATED_AT)
                  SELECT ?, ?, NULL, ?, 'DRAFT', ?, PARSE_JSON(?), PARSE_JSON(?), PARSE_JSON(?), ?, ?, ?, CURRENT_TIMESTAMP""",
               [report_id, report_type, title, content, json.dumps(data, default=str), json.dumps(passages, default=str),
                json.dumps(validation), validation["confidence"], used, user])
    _audit(be, "GENERATE_REPORT", "REPORT", report_id, {"type": report_type, "model": used})
    return {"ok": True, "report_id": report_id, "model": used, "validation": validation, "content_md": content}


def approve_report(be, report_id: str, decision: str, goaml_ref: str | None = None, comment: str = "") -> dict:
    """MLRO-only. decision: APPROVE_AND_FILE | REJECT."""
    if not be.has_role("RAQIB_MLRO"):
        return {"ok": False, "error": "Only the MLRO role can approve or file reports (AML/CFT Policy s.3.2)."}
    rep = be.query("SELECT REPORT_ID, REPORT_TYPE, CASE_ID, STATUS FROM RAQIB.OPS.REPORTS WHERE REPORT_ID = ?", [report_id])
    if not rep:
        return {"ok": False, "error": f"Report {report_id} not found."}
    rep = rep[0]
    decision = (decision or "").upper()
    user, _ = be.whoami()
    if decision == "REJECT":
        be.execute("""UPDATE RAQIB.OPS.REPORTS SET STATUS = 'REJECTED', APPROVED_BY = ?, APPROVED_AT = CURRENT_TIMESTAMP,
                      REVIEW_COMMENT = ? WHERE REPORT_ID = ?""", [user, comment, report_id])
        if rep["CASE_ID"]:
            be.execute("UPDATE RAQIB.OPS.CASES SET STATUS = 'OPEN', UPDATED_AT = CURRENT_TIMESTAMP WHERE CASE_ID = ?", [rep["CASE_ID"]])
        _audit(be, "REJECT_REPORT", "REPORT", report_id, {"comment": comment})
        return {"ok": True, "report_id": report_id, "status": "REJECTED"}
    if decision != "APPROVE_AND_FILE":
        return {"ok": False, "error": "decision must be APPROVE_AND_FILE or REJECT"}
    if rep["STATUS"] == "DRAFT_NEEDS_REVIEW":
        return {"ok": False, "error": "Report failed automated validation; correct and re-draft before filing."}
    ref = goaml_ref or f"GOAML-DEMO-{uuid.uuid4().hex[:8].upper()}"
    be.execute("""UPDATE RAQIB.OPS.REPORTS SET STATUS = 'FILED', APPROVED_BY = ?, APPROVED_AT = CURRENT_TIMESTAMP,
                  GOAML_REF = ?, REVIEW_COMMENT = ? WHERE REPORT_ID = ?""", [user, ref, comment, report_id])
    if rep["CASE_ID"]:
        be.execute("UPDATE RAQIB.OPS.CASES SET STATUS = 'STR_FILED', UPDATED_AT = CURRENT_TIMESTAMP WHERE CASE_ID = ?", [rep["CASE_ID"]])
        be.execute("""UPDATE RAQIB.OPS.ALERT_WORKFLOW SET STATUS = 'STR_FILED', UPDATED_BY = ?, UPDATED_AT = CURRENT_TIMESTAMP
                      WHERE CASE_ID = ?""", [user, rep["CASE_ID"]])
    _audit(be, "FILE_REPORT", "REPORT", report_id, {"goaml_ref": ref})
    return {"ok": True, "report_id": report_id, "status": "FILED", "goaml_ref": ref}


# =====================================================================================
# Stored-procedure entry points (Snowpark handlers)
# =====================================================================================
def _sp(fn):
    def handler(session, *args):
        try:
            return json.loads(json.dumps(fn(SnowflakeBackend(session), *args), default=str))
        except Exception as e:  # never surface a stack trace to the agent; return a safe error
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:400]}"}
    return handler


sp_get_alert_evidence = _sp(get_alert_evidence)
sp_get_customer_360 = _sp(get_customer_360)
sp_update_alert_status = _sp(update_alert_status)
sp_create_case = _sp(create_case)
sp_draft_str = _sp(draft_str)
sp_generate_regulatory_report = _sp(generate_regulatory_report)
sp_approve_report = _sp(approve_report)
