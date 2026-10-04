"""Raqib — Investigate: signal -> evidence -> decision for a single alert / customer."""
import json

import altair as alt
import pandas as pd
import streamlit as st

from lib.backend import invalidate, q
from lib.policy_queries import RULE_POLICY_QUERIES
from lib.ui import SEVERITY_COLORS, aed, badge, citation, kpi, page

be = page("Investigate", "From signal to evidence: alert facts, customer 360, money flows and the governing policy")

f1, f2, f3 = st.columns(3)
sev = f1.multiselect("Severity", ["CRITICAL", "HIGH", "MEDIUM"], default=["CRITICAL", "HIGH"])
status = f2.multiselect("Status", ["NEW", "IN_REVIEW", "ESCALATED", "CLOSED_FALSE_POSITIVE", "CLOSED_NO_ACTION", "STR_FILED"],
                        default=["NEW", "IN_REVIEW", "ESCALATED"])
rule = f3.multiselect("Rule", ["TM-01", "TM-02", "TM-03", "TM-04", "TM-05", "TM-06", "TM-07", "FR-01"])

queue = q("""SELECT ALERT_ID, SEVERITY, RULE_ID, RULE_NAME, CUSTOMER_ID, FULL_NAME, RISK_SCORE, RISK_BAND, AMOUNT_AED,
                    STATUS, ALERT_DATE, TRIGGER_SUMMARY
             FROM RAQIB.OPS.ALERT_QUEUE ORDER BY RISK_SCORE DESC, AMOUNT_AED DESC""")
view = queue[queue.SEVERITY.isin(sev or queue.SEVERITY.unique()) & queue.STATUS.isin(status or queue.STATUS.unique())]
if rule:
    view = view[view.RULE_ID.isin(rule)]

st.caption(f"{len(view)} alert(s) in queue")
sel = st.dataframe(view[["ALERT_ID", "SEVERITY", "RULE_ID", "FULL_NAME", "RISK_SCORE", "AMOUNT_AED", "STATUS", "ALERT_DATE"]],
                   hide_index=True, use_container_width=True, height=240, on_select="rerun", selection_mode="single-row",
                   column_config={"RISK_SCORE": st.column_config.ProgressColumn("Risk", min_value=0, max_value=100, format="%d"),
                                  "AMOUNT_AED": st.column_config.NumberColumn("Amount (AED)", format="%.0f")})
rows = sel.selection.rows if hasattr(sel, "selection") else []
default_id = view.iloc[rows[0]].ALERT_ID if rows else (view.iloc[0].ALERT_ID if len(view) else None)
if default_id is None:
    st.info("No alerts match the filters.")
    st.stop()
alert_id = st.selectbox("Alert", view.ALERT_ID.tolist(), index=view.ALERT_ID.tolist().index(default_id))

ev = be.tool("GET_ALERT_EVIDENCE", alert_id)
if not ev.get("ok"):
    st.error(ev.get("error"))
    st.stop()
a, cust = ev["alert"], ev["customer"] or {}
metrics = a["METRICS"] if isinstance(a["METRICS"], dict) else json.loads(a["METRICS"])

st.markdown(f"### {badge(a['SEVERITY'])} &nbsp; {a['RULE_ID']} · {a['RULE_NAME']}", unsafe_allow_html=True)
st.markdown(f"**Why it fired:** {a['TRIGGER_SUMMARY']}")
st.caption(f"Rule logic: {a['LOGIC_SUMMARY']} · Policy: {a['POLICY_REFERENCE']} · Window {str(a['WINDOW_START'])[:16]} → {str(a['WINDOW_END'])[:16]}")

c360 = be.tool("GET_CUSTOMER_360", a["CUSTOMER_ID"])
k = st.columns(5)
kpi(k[0], "Customer", cust.get("FULL_NAME", ""), f"{a['CUSTOMER_ID']} · {cust.get('CUSTOMER_TYPE', '').title()} · {cust.get('OCCUPATION') or cust.get('INDUSTRY') or ''}")
kpi(k[1], "Risk score", f"{c360['risk_score']:g}", c360["risk_band"], SEVERITY_COLORS.get(c360["risk_band"], "#64748B"))
kpi(k[2], "KYC rating", cust.get("KYC_RISK_RATING", ""), "review overdue" if cust.get("KYC_REVIEW_OVERDUE") else "review current")
kpi(k[3], "Declared turnover", aed(cust.get("EXPECTED_MONTHLY_TURNOVER_AED")), "per month")
kpi(k[4], "Evidence", f"{ev['evidence_count']} txns", aed(ev["evidence_total_aed"]))

tab_ev, tab_flow, tab_360, tab_policy = st.tabs(["Evidence transactions", "Money flow", "Customer 360 & score", "Policy basis"])

with tab_ev:
    tx = pd.DataFrame(ev["evidence_transactions"])
    if not tx.empty:
        st.dataframe(tx, hide_index=True, use_container_width=True,
                     column_config={"AMOUNT_AED": st.column_config.NumberColumn("AED", format="%.2f")})
        tx["DAY"] = pd.to_datetime(tx["TXN_TS"]).dt.date
        st.altair_chart(alt.Chart(tx).mark_circle(size=140, opacity=0.8).encode(
            x=alt.X("TXN_TS:T", title=None), y=alt.Y("AMOUNT_AED:Q", title="AED"),
            color=alt.Color("CHANNEL:N", legend=alt.Legend(orient="bottom")),
            tooltip=["TXN_ID", "TXN_TS", "CHANNEL", "AMOUNT_AED", "COUNTERPARTY_NAME", "COUNTERPARTY_COUNTRY", "BRANCH_ID"]
        ).properties(height=220), use_container_width=True)
    st.json(metrics, expanded=False)

with tab_flow:
    tx = pd.DataFrame(ev["evidence_transactions"])
    if tx.empty:
        st.info("No counterparties in evidence.")
    else:
        me = cust.get("FULL_NAME", a["CUSTOMER_ID"]).replace('"', "'")
        lines = ['digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];',
                 f'"{me}" [fillcolor="#0B3D5C", fontcolor="white"];']
        agg = tx.assign(CP=tx.COUNTERPARTY_NAME.fillna(tx.CHANNEL + " @ " + tx.BRANCH_ID.fillna("branch")))
        agg = agg.groupby(["CP", "DIRECTION", "COUNTERPARTY_COUNTRY", "COUNTERPARTY_COUNTRY_RISK"], dropna=False)["AMOUNT_AED"].agg(["sum", "count"]).reset_index()
        for _, r in agg.iterrows():
            cp = str(r.CP).replace('"', "'")
            risk = str(r.COUNTERPARTY_COUNTRY_RISK)
            fill = {"PROHIBITED": "#FDE2E1", "HIGH": "#FFEDD5"}.get(risk, "#EEF2F6")
            label = f"{cp}\\n{r.COUNTERPARTY_COUNTRY if pd.notna(r.COUNTERPARTY_COUNTRY) else ''} {risk if risk not in ('nan', 'None', 'UNKNOWN') else ''}"
            lines.append(f'"{cp}" [label="{label}", fillcolor="{fill}"];')
            edge = f'"{cp}" -> "{me}"' if r.DIRECTION == "CREDIT" else f'"{me}" -> "{cp}"'
            lines.append(f'{edge} [label="AED {r["sum"]:,.0f} ({int(r["count"])})", fontsize=9];')
        lines.append("}")
        st.graphviz_chart("\n".join(lines), use_container_width=True)
        st.caption("Red/orange nodes are counterparties in PROHIBITED / HIGH-risk jurisdictions.")

with tab_360:
    left, right = st.columns([1, 1.2])
    bd = pd.DataFrame([{"component": kk.replace("PTS_", "").replace("_", " ").title(), "points": v}
                       for kk, v in c360["score_breakdown"].items() if v])
    with left:
        st.markdown("**Explainable risk score**")
        if not bd.empty:
            st.altair_chart(alt.Chart(bd).mark_bar(color="#0F766E", cornerRadiusEnd=4).encode(
                x="points:Q", y=alt.Y("component:N", sort="-x", title=None), tooltip=["component", "points"]
            ).properties(height=200), use_container_width=True)
        st.markdown("**All alerts for this customer**")
        st.dataframe(pd.DataFrame(c360["alerts"])[["RULE_ID", "SEVERITY", "AMOUNT_AED", "TRIGGER_SUMMARY"]], hide_index=True, use_container_width=True)
    with right:
        st.markdown("**Top counterparties**")
        st.dataframe(pd.DataFrame(c360["top_counterparties"]), hide_index=True, use_container_width=True)
        st.markdown("**Accounts**")
        st.dataframe(pd.DataFrame(c360["accounts"]), hide_index=True, use_container_width=True)
        if c360["loans"]:
            st.markdown("**Credit exposure** (AML–credit overlap, POL-CRD-006 s.5)")
            st.dataframe(pd.DataFrame(c360["loans"]), hide_index=True, use_container_width=True)

with tab_policy:
    for p in be.search(RULE_POLICY_QUERIES.get(a["RULE_ID"], a["RULE_NAME"]), 3):
        citation({"title": f"{p.get('DOC_TITLE')} — {p.get('SECTION')}", "id": p.get("CHUNK_ID"), "text": p.get("CHUNK", "")})

st.divider()
st.markdown("#### Decision")
d1, d2, d3 = st.columns([1, 1, 1.4])
if d1.button("Mark in review", use_container_width=True):
    st.toast(str(be.tool("UPDATE_ALERT_STATUS", alert_id, "IN_REVIEW", "Picked up for review")))
    invalidate()
if d2.button("Open case & escalate", type="primary", use_container_width=True):
    out = be.tool("CREATE_CASE", a["CUSTOMER_ID"], f"{a['RULE_ID']}: {a['TRIGGER_SUMMARY'][:150]}")
    if out.get("ok"):
        st.success(f"Case {out['case_id']} ({out.get('priority', '')}) opened · {out.get('linked_alerts', 'existing')} alerts linked. "
                   "Go to Cases & Reports to draft the STR.")
    else:
        st.error(out.get("error"))
    invalidate()
with d3.form("close"):
    reason = st.text_area("Close as false positive — rationale (min 25 chars, reference the evidence)", height=70)
    if st.form_submit_button("Close alert"):
        out = be.tool("UPDATE_ALERT_STATUS", alert_id, "CLOSED_FALSE_POSITIVE", reason)
        (st.success if out.get("ok") else st.error)(out.get("error") or f"Closed {alert_id}")
        invalidate()
