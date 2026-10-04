"""Raqib — Cases & Reports: documented findings, STR drafting, MLRO approval and filing."""
import json

import pandas as pd
import streamlit as st

from lib.backend import invalidate, q
from lib.ui import page

be = page("Cases & Reports", "Documented findings: evidence-backed STR drafts with automated validation and MLRO sign-off")

persona = st.session_state.get("persona", "Analyst")
cases = q("""SELECT c.CASE_ID, c.PRIORITY, c.STATUS, c.CUSTOMER_ID, r.FULL_NAME, r.RISK_SCORE, c.SUMMARY, c.OPENED_BY, c.OPENED_AT
             FROM RAQIB.OPS.CASES c JOIN RAQIB.DETECT.CUSTOMER_RISK r ON r.CUSTOMER_ID = c.CUSTOMER_ID
             ORDER BY c.OPENED_AT DESC""")

tab_cases, tab_reports, tab_reg = st.tabs(["Cases", "STR reports", "Regulatory reports"])

with tab_cases:
    if cases.empty:
        st.info("No cases yet. Open one from **Investigate** or ask the Copilot: “Open a case for Tariq Mahmoud Haddad and draft the STR.”")
    else:
        st.dataframe(cases, hide_index=True, use_container_width=True)
        cid = st.selectbox("Case", cases.CASE_ID.tolist())
        alerts = q("""SELECT ca.ALERT_ID, a.RULE_ID, a.SEVERITY, a.AMOUNT_AED, a.TRIGGER_SUMMARY
                      FROM RAQIB.OPS.CASE_ALERTS ca JOIN RAQIB.DETECT.ALERTS a ON a.ALERT_ID = ca.ALERT_ID WHERE ca.CASE_ID = ?""", [cid])
        st.dataframe(alerts, hide_index=True, use_container_width=True)
        if st.button("✍️ Draft STR with Raqib", type="primary"):
            with st.spinner("Collecting evidence, retrieving policy, drafting and validating…"):
                out = be.tool("DRAFT_STR", cid)
            if out.get("ok"):
                st.session_state["open_report"] = out["report_id"]
                v = out["validation"]
                (st.success if v["passed"] else st.warning)(
                    f"{out['report_id']} drafted with {out['model']} — validation {'passed' if v['passed'] else 'needs review'} "
                    f"(confidence {v['confidence']}). See the STR reports tab.")
            else:
                st.error(out.get("error"))
            invalidate()

with tab_reports:
    reps = q("""SELECT REPORT_ID, CASE_ID, SUBJECT, STATUS, CONFIDENCE, MODEL, CREATED_AT, APPROVED_BY, GOAML_REF
                FROM RAQIB.OPS.REPORTS WHERE REPORT_TYPE = 'STR' ORDER BY CREATED_AT DESC""")
    if reps.empty:
        st.info("No STR drafts yet.")
    else:
        st.dataframe(reps, hide_index=True, use_container_width=True,
                     column_config={"CONFIDENCE": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=1, format="%.2f")})
        ids = reps.REPORT_ID.tolist()
        rid = st.selectbox("Report", ids, index=ids.index(st.session_state["open_report"]) if st.session_state.get("open_report") in ids else 0)
        rep = q("SELECT * FROM RAQIB.OPS.REPORTS WHERE REPORT_ID = ?", [rid]).iloc[0]
        val = rep.VALIDATION if isinstance(rep.VALIDATION, dict) else json.loads(rep.VALIDATION or "{}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Status", rep.STATUS)
        c2.metric("Amounts reconciled", f"{val.get('amounts_checked', 0) - len(val.get('unmatched_amounts', []))}/{val.get('amounts_checked', 0)}")
        c3.metric("Citations valid", "Yes" if val.get("has_citations") else "No")
        c4.metric("Tipping-off check", "Clear" if not val.get("tipping_off_flags") else "Flagged")
        st.markdown(rep.CONTENT_MD)
        st.download_button("⬇ Download STR (markdown)", rep.CONTENT_MD, file_name=f"{rid}.md")
        st.divider()
        if persona != "MLRO":
            st.info("Only the **MLRO** can approve and file. Switch persona in the sidebar (in Snowflake this is enforced by role: "
                    "APPROVE_REPORT runs with caller's rights and checks RAQIB_MLRO).")
        elif rep.STATUS in ("DRAFT", "DRAFT_NEEDS_REVIEW"):
            with st.form("mlro"):
                comment = st.text_area("MLRO comment")
                ref = st.text_input("goAML reference (leave blank to generate a demo reference)")
                a, b = st.columns(2)
                approve = a.form_submit_button("✅ Approve & file", type="primary")
                reject = b.form_submit_button("↩ Reject")
            if approve or reject:
                out = be.tool("APPROVE_REPORT", rid, "APPROVE_AND_FILE" if approve else "REJECT", ref or None, comment)
                (st.success if out.get("ok") else st.error)(out.get("error") or f"{rid} → {out['status']} {out.get('goaml_ref', '')}")
                invalidate()

with tab_reg:
    c = st.columns(3)
    for col, (rtype, label) in zip(c, [("LCR", "Liquidity (LCR) report"), ("CREDIT", "Credit & IFRS 9 report"), ("AML_MI", "AML MI report")]):
        if col.button(f"Generate {label}", use_container_width=True):
            with st.spinner(f"Generating {label}…"):
                out = be.tool("GENERATE_REGULATORY_REPORT", rtype)
            st.session_state["open_reg"] = out.get("report_id")
            invalidate()
    regs = q("""SELECT REPORT_ID, REPORT_TYPE, STATUS, MODEL, CREATED_AT, CONTENT_MD FROM RAQIB.OPS.REPORTS
                WHERE REPORT_TYPE <> 'STR' ORDER BY CREATED_AT DESC""")
    if not regs.empty:
        st.dataframe(regs.drop(columns=["CONTENT_MD"]), hide_index=True, use_container_width=True)
        rid = st.selectbox("Regulatory report", regs.REPORT_ID.tolist())
        st.markdown(regs[regs.REPORT_ID == rid].iloc[0].CONTENT_MD)
