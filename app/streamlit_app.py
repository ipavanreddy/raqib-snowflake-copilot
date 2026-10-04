"""Raqib — entry point and navigation (Streamlit in Snowflake MAIN_FILE)."""
import streamlit as st

st.set_page_config(page_title="Raqib · Risk, Fraud & Regulatory Copilot", page_icon="🛡️", layout="wide")

nav = st.navigation([
    st.Page("pages/0_Command_Center.py", title="Command Center", icon="🧭", default=True),
    st.Page("pages/1_Copilot.py", title="Copilot", icon="💬", url_path="copilot"),
    st.Page("pages/2_Investigate.py", title="Investigate", icon="🔎", url_path="investigate"),
    st.Page("pages/3_Cases_and_Reports.py", title="Cases & Reports", icon="📁", url_path="cases"),
    st.Page("pages/4_Regulatory_Risk.py", title="Regulatory Risk", icon="🏦", url_path="regulatory"),
    st.Page("pages/5_Governance_and_Audit.py", title="Governance & Audit", icon="🛡️", url_path="governance"),
])
nav.run()
