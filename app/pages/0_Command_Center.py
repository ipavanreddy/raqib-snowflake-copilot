"""Raqib — Command Center (home page)."""
import altair as alt
import pandas as pd
import streamlit as st

from lib.backend import q
from lib.ui import BAND_ORDER, SEVERITY_COLORS, aed, kpi, page, severity_scale

be = page("Command Center", "Financial-crime signals, liquidity and credit risk at a glance")

k = q("""
SELECT
  (SELECT COUNT(*) FROM RAQIB.OPS.ALERT_QUEUE WHERE STATUS IN ('NEW', 'IN_REVIEW', 'ESCALATED'))               AS OPEN_ALERTS,
  (SELECT COUNT(*) FROM RAQIB.OPS.ALERT_QUEUE WHERE SEVERITY = 'CRITICAL' AND STATUS IN ('NEW', 'IN_REVIEW'))     AS CRITICAL_ALERTS,
  (SELECT COUNT(*) FROM RAQIB.DETECT.CUSTOMER_RISK WHERE RISK_BAND = 'CRITICAL')                                  AS CRITICAL_CUSTOMERS,
  (SELECT SUM(AMOUNT_AED) FROM RAQIB.DETECT.ALERTS)                                                               AS ALERTED_AED,
  (SELECT LCR_PCT FROM RAQIB.RISK.LCR_DAILY ORDER BY AS_OF_DATE DESC LIMIT 1)                                     AS LCR,
  (SELECT MIN(LCR_PCT) FROM RAQIB.RISK.LCR_DAILY)                                                                 AS LCR_MIN,
  (SELECT 100 * SUM(IFF(IS_NPL, EAD_AED, 0)) / SUM(EAD_AED) FROM RAQIB.RISK.LOAN_ECL)                             AS NPL,
  (SELECT COUNT(*) FROM RAQIB.OPS.CASES WHERE STATUS IN ('OPEN', 'PENDING_MLRO'))                                 AS OPEN_CASES
""").iloc[0]

c = st.columns(6)
kpi(c[0], "Open alerts", f"{int(k.OPEN_ALERTS):,}", f"{int(k.CRITICAL_ALERTS)} critical untriaged", SEVERITY_COLORS["CRITICAL"])
kpi(c[1], "Critical customers", int(k.CRITICAL_CUSTOMERS), "same-day review (TM s.6)", SEVERITY_COLORS["CRITICAL"])
kpi(c[2], "Value under alert", aed(k.ALERTED_AED), "review period")
kpi(c[3], "Open cases", int(k.OPEN_CASES), "incl. pending MLRO")
lcr_color = "#2F855A" if k.LCR >= 110 else ("#B7791F" if k.LCR >= 100 else "#B42318")
kpi(c[4], "LCR (latest)", f"{k.LCR:.1f}%", f"low {k.LCR_MIN:.1f}% · trigger 110%", lcr_color)
kpi(c[5], "NPL ratio", f"{k.NPL:.2f}%", "appetite < 6%", "#2F855A" if k.NPL < 6 else "#B42318")

st.write("")
left, right = st.columns([1.35, 1])

with left:
    st.markdown('<div class="rq-section">Priority queue — highest-risk customers</div>', unsafe_allow_html=True)
    top = q("""SELECT CUSTOMER_ID, FULL_NAME, RISK_SCORE, RISK_BAND, RULE_IDS, ALERT_COUNT, ALERTED_AMOUNT_AED
               FROM RAQIB.DETECT.CUSTOMER_RISK WHERE RULES_HIT > 0
               ORDER BY RISK_SCORE DESC, ALERTED_AMOUNT_AED DESC LIMIT 12""")
    st.dataframe(
        top, hide_index=True, use_container_width=True, height=420,
        column_config={
            "RISK_SCORE": st.column_config.ProgressColumn("Risk score", min_value=0, max_value=100, format="%d"),
            "ALERTED_AMOUNT_AED": st.column_config.NumberColumn("Alerted (AED)", format="%.0f"),
            "FULL_NAME": "Customer", "CUSTOMER_ID": "ID", "CUSTOMER_TYPE": "Type", "RISK_BAND": "Band",
            "RULE_IDS": "Rules hit", "ALERT_COUNT": "Alerts",
        })
    st.caption("Open **Investigate** to see evidence, or ask the **Copilot**: “Explain why the top customer is critical.”")

with right:
    st.markdown('<div class="rq-section">Alerts by rule and severity</div>', unsafe_allow_html=True)
    by_rule = q("""SELECT RULE_ID, RULE_NAME, SEVERITY, COUNT(*) AS ALERTS FROM RAQIB.DETECT.ALERTS
                   GROUP BY RULE_ID, RULE_NAME, SEVERITY ORDER BY RULE_ID""")
    st.altair_chart(
        alt.Chart(by_rule).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("ALERTS:Q", title="Alerts"),
            y=alt.Y("RULE_ID:N", sort=None, title=None, axis=alt.Axis(labelOverlap=False)),
            color=alt.Color("SEVERITY:N", scale=severity_scale(), legend=alt.Legend(orient="top", title=None)),
            tooltip=["RULE_ID", "RULE_NAME", "SEVERITY", "ALERTS"]).properties(height=alt.Step(26)),
        use_container_width=True)
    st.markdown('<div class="rq-section">Customer risk distribution</div>', unsafe_allow_html=True)
    bands = q("SELECT RISK_BAND, COUNT(*) AS CUSTOMERS FROM RAQIB.DETECT.CUSTOMER_RISK GROUP BY RISK_BAND")
    st.altair_chart(
        alt.Chart(bands).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("CUSTOMERS:Q", scale=alt.Scale(type="symlog"), title="Customers (log scale)"),
            y=alt.Y("RISK_BAND:N", sort=BAND_ORDER, title=None, axis=alt.Axis(labelOverlap=False)),
            color=alt.Color("RISK_BAND:N", scale=severity_scale(), legend=None),
            tooltip=["RISK_BAND", "CUSTOMERS"]).properties(height=alt.Step(30)),
        use_container_width=True)

st.markdown('<div class="rq-section">Liquidity Coverage Ratio — 180 days</div>', unsafe_allow_html=True)
lcr = q("SELECT AS_OF_DATE, LCR_PCT, LCR_STATUS FROM RAQIB.RISK.LCR_DAILY ORDER BY AS_OF_DATE")
base = alt.Chart(lcr).encode(x=alt.X("AS_OF_DATE:T", title=None))
rules = alt.Chart(
    pd.DataFrame({"y": [100, 110], "label": ["Regulatory minimum 100%", "Early-warning trigger 110%"]})
).mark_rule(strokeDash=[5, 4]).encode(y="y:Q", color=alt.Color("label:N", scale=alt.Scale(domain=["Regulatory minimum 100%", "Early-warning trigger 110%"], range=["#B42318", "#B7791F"]),
                                                                legend=alt.Legend(orient="top", title=None)))
st.altair_chart(
    (base.mark_area(opacity=0.12, color="#0F766E").encode(y=alt.Y("LCR_PCT:Q", scale=alt.Scale(domain=[90, 170]), title="LCR %"))
     + base.mark_line(color="#0F766E", strokeWidth=2).encode(y="LCR_PCT:Q", tooltip=["AS_OF_DATE:T", "LCR_PCT:Q", "LCR_STATUS:N"])
     + rules).properties(height=220, padding={"left": 12}),
    use_container_width=True)

notes = q("""SELECT CREATED_AT, SEVERITY, TITLE, BODY FROM RAQIB.OPS.NOTIFICATIONS
             WHERE STATUS IN ('PENDING', 'SENT') ORDER BY CREATED_AT DESC LIMIT 5""")
if not notes.empty:
    st.markdown('<div class="rq-section">Latest notifications (routed to Slack by the CoCo MCP automation)</div>', unsafe_allow_html=True)
    for _, n in notes.iterrows():
        st.markdown(f"**{n.TITLE}** — {n.BODY}")
