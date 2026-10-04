"""Raqib — Governance & Audit: who asked what, which tools acted, controls and detection quality."""
import pandas as pd
import streamlit as st

from lib.backend import q
from lib.ui import page

be = page("Governance & Audit", "Every question, tool action and control — reviewable by Compliance, Audit and Model Risk")

t1, t2, t3, t4, t5 = st.tabs(["Tool audit trail", "Copilot Q&A log", "Notification outbox", "Rules & controls", "Detection quality"])

with t1:
    st.dataframe(q("SELECT EVENT_TS, ACTOR, ACTOR_ROLE, ACTION, OBJECT_TYPE, OBJECT_ID, DETAILS FROM RAQIB.OPS.AUDIT_LOG ORDER BY EVENT_TS DESC LIMIT 500"),
                 hide_index=True, use_container_width=True)

with t2:
    st.dataframe(q("""SELECT EVENT_TS, ACTOR, PERSONA, SURFACE, QUESTION, LATENCY_MS, TOOLS_USED, CITATIONS
                      FROM RAQIB.OPS.COPILOT_AUDIT ORDER BY EVENT_TS DESC LIMIT 500"""), hide_index=True, use_container_width=True)

with t3:
    st.caption("PENDING items are posted to Slack / Jira by the CoCo automation using MCP connectors, then marked SENT.")
    st.dataframe(q("""SELECT CREATED_AT, STATUS, SEVERITY, TITLE, BODY, OBJECT_ID FROM RAQIB.OPS.NOTIFICATIONS
                      WHERE STATUS <> 'SKIPPED' ORDER BY CREATED_AT DESC"""), hide_index=True, use_container_width=True)

with t4:
    st.markdown("**Detection rules** (versioned in code, mirrored in the Transaction Monitoring Rulebook)")
    st.dataframe(q("SELECT * FROM RAQIB.DETECT.RULE_CATALOG ORDER BY RULE_ID"), hide_index=True, use_container_width=True)
    st.markdown("**Built-in controls**")
    st.markdown("""
- **PII masking** — Emirates ID, phone, email, DOB are masked for analysts; visible to the MLRO role (`OPS.MASK_PII_STRING`, `OPS.MASK_DOB`, tag `OPS.PII_TYPE`).
- **Segregation of duties** — the agent has no filing tool; `APPROVE_REPORT` runs with caller's rights and requires `RAQIB_MLRO`.
- **Evidence-only drafting** — STR narratives are validated: every AED amount reconciled to evidence, citations checked, tipping-off language removed.
- **Workflow rules** — closing an alert requires a rationale (≥ 25 chars); `STR_FILED` can only be set by an MLRO approval.
- **Graceful fallback** — model fallback chain, then a deterministic template; tool errors return safe messages, never stack traces.
- **Full audit** — every tool action (`OPS.AUDIT_LOG`) and every question/answer (`OPS.COPILOT_AUDIT`).
- **Ground truth isolation** — planted test cases are not granted to business roles.
""")

with t5:
    st.caption("Back-test against the planted typologies in the synthetic data (platform owner only).")
    try:
        rec = q("""WITH exp AS (SELECT p.SCENARIO_ID, p.TYPOLOGY, p.CUSTOMER_ID, s.VALUE::VARCHAR AS RULE_ID
                                FROM RAQIB.RAW.PLANTED_CASES p, LATERAL FLATTEN(INPUT => SPLIT(p.EXPECTED_RULE, '|')) s)
                   SELECT e.RULE_ID, COUNT(*) AS PLANTED,
                          COUNT_IF(EXISTS (SELECT 1 FROM RAQIB.DETECT.ALERTS a WHERE a.CUSTOMER_ID = e.CUSTOMER_ID AND a.RULE_ID = e.RULE_ID)) AS DETECTED
                   FROM exp e GROUP BY e.RULE_ID ORDER BY e.RULE_ID""")
    except Exception:  # offline DuckDB has no LATERAL FLATTEN; use an equivalent query
        rec = q("""WITH exp AS (SELECT CUSTOMER_ID, UNNEST(STRING_SPLIT(EXPECTED_RULE, '|')) AS RULE_ID FROM RAQIB.RAW.PLANTED_CASES)
                   SELECT RULE_ID, COUNT(*) AS PLANTED,
                          SUM(CASE WHEN EXISTS (SELECT 1 FROM RAQIB.DETECT.ALERTS a WHERE a.CUSTOMER_ID = e.CUSTOMER_ID AND a.RULE_ID = e.RULE_ID) THEN 1 ELSE 0 END) AS DETECTED
                   FROM exp e GROUP BY RULE_ID ORDER BY RULE_ID""")
    rec["RECALL"] = rec.DETECTED / rec.PLANTED
    fp = q("""SELECT RULE_ID, COUNT(*) AS ALERTS_ON_NON_PLANTED FROM RAQIB.DETECT.ALERTS
              WHERE CUSTOMER_ID NOT IN (SELECT CUSTOMER_ID FROM RAQIB.RAW.PLANTED_CASES) GROUP BY RULE_ID""")
    out = rec.merge(fp, on="RULE_ID", how="left").fillna({"ALERTS_ON_NON_PLANTED": 0})
    c1, c2 = st.columns(2)
    c1.metric("Recall on planted typologies", f"{out.DETECTED.sum() / out.PLANTED.sum():.0%}")
    c2.metric("Alerts on non-planted customers", int(out.ALERTS_ON_NON_PLANTED.sum()))
    st.dataframe(out, hide_index=True, use_container_width=True,
                 column_config={"RECALL": st.column_config.ProgressColumn("Recall", min_value=0, max_value=1, format="%.0f%%")})
