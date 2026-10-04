"""Raqib — Regulatory risk: Basel III LCR and IFRS 9 credit portfolio."""
import altair as alt
import pandas as pd
import streamlit as st

from lib.backend import q
from lib.ui import aed, kpi, page

be = page("Regulatory Risk", "Basel III liquidity and IFRS 9 credit risk, with the AML–credit overlap")

lcr = q("SELECT * FROM RAQIB.RISK.LCR_DAILY ORDER BY AS_OF_DATE")
latest = lcr.iloc[-1]
ew = lcr[lcr.LCR_STATUS != "COMPLIANT"]
port = q("""SELECT SUM(EAD_AED) AS EAD, 100 * SUM(IFF(IS_NPL, EAD_AED, 0)) / SUM(EAD_AED) AS NPL,
                   SUM(ECL_AED) AS ECL, 100 * SUM(ECL_AED) / SUM(EAD_AED) AS COV FROM RAQIB.RISK.LOAN_ECL""").iloc[0]

k = st.columns(6)
kpi(k[0], "LCR latest", f"{latest.LCR_PCT:.1f}%", latest.LCR_STATUS, "#2F855A" if latest.LCR_PCT >= 110 else "#B7791F")
kpi(k[1], "HQLA", f"AED {latest.HQLA_TOTAL_AED_M:,.0f}M", "after haircuts & caps")
kpi(k[2], "Early-warning days", len(ew), f"low {lcr.LCR_PCT.min():.1f}%", "#B7791F" if len(ew) else "#2F855A")
kpi(k[3], "Credit exposure", aed(port.EAD), "gross EAD")
kpi(k[4], "NPL ratio", f"{port.NPL:.2f}%", "appetite < 6%", "#2F855A" if port.NPL < 6 else "#B42318")
kpi(k[5], "ECL coverage", f"{port.COV:.2f}%", aed(port.ECL))

st.markdown('<div class="rq-section">LCR drivers — HQLA vs net cash outflows (AED millions)</div>', unsafe_allow_html=True)
melt = lcr.rename(columns={"HQLA_TOTAL_AED_M": "HQLA (after haircuts & caps)", "NET_OUTFLOWS_AED_M": "Net cash outflows (30d)"}).melt(
    id_vars=["AS_OF_DATE"], value_vars=["HQLA (after haircuts & caps)", "Net cash outflows (30d)"], var_name="series", value_name="aed_m")
st.altair_chart(alt.Chart(melt).mark_line(strokeWidth=2).encode(
    x=alt.X("AS_OF_DATE:T", title=None), y=alt.Y("aed_m:Q", title="AED m"),
    color=alt.Color("series:N", scale=alt.Scale(range=["#0F766E", "#B42318"]), legend=alt.Legend(orient="top", title=None)),
    tooltip=["AS_OF_DATE:T", "series", "aed_m"]).properties(height=240), use_container_width=True)
if len(ew):
    st.warning(f"LCR below the 110% internal trigger on {len(ew)} day(s) between {ew.AS_OF_DATE.min()} and {ew.AS_OF_DATE.max()} "
               f"(trough {ew.LCR_PCT.min():.1f}%). Policy POL-LIQ-005 s.4 requires same-day ALCO notification and a remediation plan.")
    st.dataframe(ew[["AS_OF_DATE", "LCR_PCT", "HQLA_TOTAL_AED_M", "GROSS_OUTFLOWS_AED_M", "INFLOWS_CAPPED_AED_M", "NET_OUTFLOWS_AED_M"]],
                 hide_index=True, use_container_width=True)

left, right = st.columns(2)
with left:
    st.markdown('<div class="rq-section">NPL ratio by sector</div>', unsafe_allow_html=True)
    sec = q("""SELECT SECTOR, SUM(EXPOSURE_AED) AS EXPOSURE_AED,
                      100 * SUM(NPL_EXPOSURE_AED) / NULLIF(SUM(EXPOSURE_AED), 0) AS NPL_RATIO_PCT
               FROM RAQIB.RISK.CREDIT_PORTFOLIO_SUMMARY GROUP BY SECTOR ORDER BY NPL_RATIO_PCT DESC""")
    st.altair_chart(alt.Chart(sec).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("NPL_RATIO_PCT:Q", title="NPL %"), y=alt.Y("SECTOR:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
        color=alt.condition(alt.datum.NPL_RATIO_PCT > 10, alt.value("#B42318"), alt.value("#0F766E")),
        tooltip=["SECTOR", alt.Tooltip("NPL_RATIO_PCT:Q", format=".2f"), alt.Tooltip("EXPOSURE_AED:Q", format=",.0f")]
    ).properties(height=alt.Step(24)), use_container_width=True)
    st.caption("Red = above the 10% sector watch-list threshold (POL-CRD-006 s.3).")
with right:
    st.markdown('<div class="rq-section">IFRS 9 stage mix</div>', unsafe_allow_html=True)
    stg = q("""SELECT IFRS9_STAGE, COUNT(*) AS LOANS, SUM(EAD_AED) AS EXPOSURE_AED, SUM(ECL_AED) AS ECL_AED
               FROM RAQIB.RISK.LOAN_ECL GROUP BY IFRS9_STAGE ORDER BY IFRS9_STAGE""")
    stg["STAGE"] = "Stage " + stg.IFRS9_STAGE.astype(int).astype(str)
    st.altair_chart(alt.Chart(stg).mark_arc(innerRadius=60).encode(
        theta="EXPOSURE_AED:Q", color=alt.Color("STAGE:N", scale=alt.Scale(range=["#0F766E", "#B7791F", "#B42318"])),
        tooltip=["STAGE", "LOANS", alt.Tooltip("EXPOSURE_AED:Q", format=",.0f"), alt.Tooltip("ECL_AED:Q", format=",.0f")]
    ).properties(height=250), use_container_width=True)
    st.markdown('<div class="rq-section">AML–credit overlap (borrowers under AML risk)</div>', unsafe_allow_html=True)
    st.dataframe(q("SELECT * FROM RAQIB.RISK.AML_CREDIT_OVERLAP ORDER BY RISK_SCORE DESC"), hide_index=True, use_container_width=True)
