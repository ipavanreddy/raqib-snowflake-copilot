"""Shared look-and-feel for Raqib pages."""
from __future__ import annotations

import html

import altair as alt
import streamlit as st

NAVY = "#0B3D5C"
TEAL = "#0F766E"
SEVERITY_COLORS = {"CRITICAL": "#B42318", "HIGH": "#D9480F", "MEDIUM": "#B7791F", "LOW": "#2F855A"}
BAND_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

CSS = """
<style>
  .block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1400px;}
  .rq-header {display:flex; align-items:center; gap:14px; margin-bottom: 0.4rem;}
  .rq-logo {width:42px; height:42px; border-radius:10px; background: linear-gradient(135deg,#0B3D5C,#0F766E);
            color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:20px;}
  .rq-title {font-size: 1.55rem; font-weight: 700; color:#0B3D5C; line-height:1.1;}
  .rq-sub {color:#475569; font-size:0.9rem;}
  .rq-card {background:#fff; border:1px solid #E2E8F0; border-radius:12px; padding:14px 16px; min-height:112px;}
  .rq-kpi-label {color:#64748B; font-size:0.78rem; text-transform:uppercase; letter-spacing:.04em;}
  .rq-kpi-value {color:#0F172A; font-size:1.4rem; font-weight:700; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
  .rq-kpi-note {font-size:0.8rem; margin-top:2px;}
  .rq-badge {display:inline-block; padding:2px 8px; border-radius:999px; font-size:0.74rem; font-weight:600; color:#fff;}
  .rq-pill {display:inline-block; padding:2px 8px; border-radius:6px; font-size:0.75rem; background:#EEF2F6; color:#334155; margin-right:4px;}
  .rq-mode {font-size:0.75rem; padding:3px 8px; border-radius:6px; background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0;}
  .rq-mode.off {background:#FFF7ED; color:#9A3412; border-color:#FED7AA;}
  .rq-cite {border-left:3px solid #0F766E; background:#F0FDFA; padding:8px 10px; border-radius:6px; margin:6px 0; font-size:0.85rem;}
  .rq-section {font-weight:700; color:#0B3D5C; margin: 0.6rem 0 0.2rem 0;}
</style>
"""


def page(title: str, subtitle: str):
    st.markdown(CSS, unsafe_allow_html=True)
    from lib.backend import get_backend
    be = get_backend()
    mode = ('<span class="rq-mode">Live · Snowflake Cortex</span>' if be.mode == "snowflake"
            else '<span class="rq-mode off">Offline demo · DuckDB replica</span>')
    st.markdown(f"""<div class="rq-header"><div class="rq-logo">R</div>
        <div><div class="rq-title">{html.escape(title)}</div>
        <div class="rq-sub">{html.escape(subtitle)} &nbsp; {mode}</div></div></div>""", unsafe_allow_html=True)
    sidebar(be)
    return be


def sidebar(be):
    with st.sidebar:
        st.markdown("### 🛡️ Raqib")
        st.caption("Risk, Fraud & Regulatory Intelligence Copilot · Gulf Horizon Bank (fictional, synthetic data)")
        st.session_state.setdefault("persona", "Analyst")
        st.selectbox("Persona", ["Analyst", "MLRO", "Risk / Treasury"], key="persona",
                     help="Analysts triage and draft; only the MLRO approves and files STRs.")
        st.divider()
        st.markdown("**Live demo feed**")
        scen = st.selectbox("Inject activity", ["STRUCTURING", "ATO", "BACKGROUND"], label_visibility="collapsed")
        if st.button("▶ Inject & refresh pipeline", use_container_width=True):
            with st.spinner("Writing to RAW and refreshing dynamic tables…"):
                out = be.simulate(scen)
            from lib.backend import invalidate
            invalidate()
            st.session_state["last_sim"] = out
        if st.session_state.get("last_sim"):
            st.success(st.session_state["last_sim"].get("detail", "done"))


def kpi(col, label, value, note="", color="#64748B"):
    col.markdown(f"""<div class="rq-card"><div class="rq-kpi-label">{html.escape(label)}</div>
        <div class="rq-kpi-value" title="{html.escape(str(value))}">{html.escape(str(value))}</div>
        <div class="rq-kpi-note" style="color:{color}">{html.escape(note)}</div></div>""", unsafe_allow_html=True)


def badge(text: str) -> str:
    c = SEVERITY_COLORS.get(str(text).upper(), "#475569")
    return f'<span class="rq-badge" style="background:{c}">{html.escape(str(text))}</span>'


def aed(x, decimals=0) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "-"
    if abs(x) >= 1e6:
        return f"AED {x / 1e6:,.2f}M"
    return f"AED {x:,.{decimals}f}"


def severity_scale():
    return alt.Scale(domain=list(SEVERITY_COLORS), range=list(SEVERITY_COLORS.values()))


def citation(c: dict):
    st.markdown(f"""<div class="rq-cite"><b>{html.escape(str(c.get('title') or ''))}</b>
        <span class="rq-pill">{html.escape(str(c.get('id') or ''))}</span><br>{html.escape(str(c.get('text') or '')[:380])}…</div>""",
                unsafe_allow_html=True)
