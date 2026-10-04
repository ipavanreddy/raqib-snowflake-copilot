"""Unit tests for agent tools + guardrails (tools/raqib_tools.py) on the local DuckDB backend."""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import raqib_tools as T  # noqa: E402
from local_backend import LocalBackend, create_ops_tables  # noqa: E402
from sql_harness import build_all  # noqa: E402


@pytest.fixture(scope="module")
def con():
    c = build_all()
    create_ops_tables(c)
    return c


def hero_id(be):
    return be.query("SELECT CUSTOMER_ID FROM RAQIB.RAW.CUSTOMERS WHERE FULL_NAME = 'Tariq Mahmoud Haddad'")[0]["CUSTOMER_ID"]


def faithful_llm(prompt, model, schema):
    """Stub LLM that writes a narrative using only amounts present in the evidence."""
    ev = json.loads(prompt.split("EVIDENCE (JSON):\n", 1)[1].split("\n\nPOLICY PASSAGES:", 1)[0])
    chunk_ids = re.findall(r"\[chunk_id: ([^\]]+)\]", prompt)
    a = ev["alerts"][0]
    return json.dumps({
        "summary": f"{ev['subject']['FULL_NAME']} triggered {len(ev['alerts'])} rules.",
        "grounds_for_suspicion": f"Rule {a['rule_id']}: total AED {float(a['amount_aed']):,.2f}.",
        "red_flags": [x["rule_name"] for x in ev["alerts"]],
        "recommended_action": "MLRO to consider filing; apply enhanced monitoring.",
        "citations": chunk_ids[:2]})


def hallucinating_llm(prompt, model, schema):
    chunk_ids = re.findall(r"\[chunk_id: ([^\]]+)\]", prompt)
    return json.dumps({"summary": "Subject moved AED 9,999,999.00 offshore.",
                       "grounds_for_suspicion": "We recommend you inform the customer about the STR investigation.",
                       "red_flags": ["x"], "recommended_action": "Tell the customer about the report and investigation.",
                       "citations": chunk_ids[:1] + ["POL-FAKE-999#001"]})


def test_evidence_tool(con):
    be = LocalBackend(con)
    aid = be.query("SELECT ALERT_ID FROM RAQIB.DETECT.ALERTS WHERE RULE_ID = 'TM-01' LIMIT 1")[0]["ALERT_ID"]
    out = T.get_alert_evidence(be, aid)
    assert out["ok"] and out["evidence_count"] >= 3 and out["customer"]["CUSTOMER_ID"]
    assert T.get_alert_evidence(be, "AL-NOPE")["ok"] is False


def test_customer_360_explains_score(con):
    be = LocalBackend(con)
    out = T.get_customer_360(be, hero_id(be))
    assert out["risk_band"] == "CRITICAL"
    assert sum(v for v in out["score_breakdown"].values()) >= out["risk_score"]


def test_workflow_guardrails(con):
    be = LocalBackend(con)
    aid = be.query("SELECT ALERT_ID FROM RAQIB.DETECT.ALERTS LIMIT 1")[0]["ALERT_ID"]
    assert not T.update_alert_status(be, aid, "CLOSED_FALSE_POSITIVE", "looks ok")["ok"]
    assert not T.update_alert_status(be, aid, "STR_FILED")["ok"]
    assert T.update_alert_status(be, aid, "IN_REVIEW")["ok"]
    assert T.update_alert_status(be, aid, "CLOSED_FALSE_POSITIVE",
                                 "Salary arrears paid in one lump sum; employer letter on file reviewed.")["ok"]


def test_case_and_faithful_str(con):
    be = LocalBackend(con, llm=faithful_llm)
    case = T.create_case(be, hero_id(be), "Structuring and sanctions near-match")
    assert case["ok"] and case["linked_alerts"] >= 4
    again = T.create_case(be, hero_id(be), "dup")
    assert again["case_id"] == case["case_id"]
    rep = T.draft_str(be, case["case_id"])
    assert rep["ok"] and rep["validation"]["passed"], rep["validation"]
    assert rep["status"] == "DRAFT" and "Transactions relied upon" in rep["content_md"]
    notes = be.query("SELECT COUNT(*) AS N FROM RAQIB.OPS.NOTIFICATIONS")[0]["N"]
    audit = be.query("SELECT COUNT(*) AS N FROM RAQIB.OPS.AUDIT_LOG WHERE ACTION = 'DRAFT_STR'")[0]["N"]
    assert notes >= 2 and audit == 1


def test_guardrails_catch_hallucination_and_tipping_off(con):
    be = LocalBackend(con, llm=hallucinating_llm)
    cid = be.query("SELECT CUSTOMER_ID FROM RAQIB.DETECT.ALERTS WHERE RULE_ID = 'TM-03' LIMIT 1")[0]["CUSTOMER_ID"]
    case = T.create_case(be, cid, "mule")
    rep = T.draft_str(be, case["case_id"])
    v = rep["validation"]
    assert rep["status"] == "DRAFT_NEEDS_REVIEW"
    assert "AED 9,999,999.00" in v["unmatched_amounts"]
    assert v["invalid_citations"] == ["POL-FAKE-999#001"] and v["tipping_off_flags"] >= 1
    assert "Removed by guardrail" in rep["content_md"]


def test_llm_outage_falls_back_to_template(con):
    be = LocalBackend(con, llm=None)
    cid = be.query("SELECT CUSTOMER_ID FROM RAQIB.DETECT.ALERTS WHERE RULE_ID = 'FR-01' LIMIT 1")[0]["CUSTOMER_ID"]
    case = T.create_case(be, cid, "ATO")
    rep = T.draft_str(be, case["case_id"])
    assert rep["ok"] and rep["model"] == "template-fallback" and rep["validation"]["passed"], rep["validation"]


def test_only_mlro_can_file(con):
    analyst = LocalBackend(con, llm=faithful_llm, roles=("RAQIB_ANALYST",))
    mlro = LocalBackend(con, llm=faithful_llm)
    rid = mlro.query("SELECT REPORT_ID FROM RAQIB.OPS.REPORTS WHERE STATUS = 'DRAFT' LIMIT 1")[0]["REPORT_ID"]
    assert not T.approve_report(analyst, rid, "APPROVE_AND_FILE")["ok"]
    out = T.approve_report(mlro, rid, "APPROVE_AND_FILE")
    assert out["ok"] and out["goaml_ref"].startswith("GOAML-DEMO-")
    bad = mlro.query("SELECT REPORT_ID FROM RAQIB.OPS.REPORTS WHERE STATUS = 'DRAFT_NEEDS_REVIEW' LIMIT 1")[0]["REPORT_ID"]
    assert not T.approve_report(mlro, bad, "APPROVE_AND_FILE")["ok"]


@pytest.mark.parametrize("rtype", ["LCR", "CREDIT", "AML_MI"])
def test_regulatory_reports_fallback(con, rtype):
    out = T.generate_regulatory_report(LocalBackend(con), rtype)
    assert out["ok"] and out["model"] == "template-fallback" and "{" in out["content_md"]
