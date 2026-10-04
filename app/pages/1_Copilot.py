"""Raqib — Copilot: natural-language questions answered by the Cortex Agent with evidence."""
import streamlit as st

from lib.backend import invalidate, timed
from lib.ui import citation, page

be = page("Copilot", "Ask in plain language — governed answers with SQL, evidence and policy citations")

SAMPLES = [
    "Who are the top 5 highest-risk customers and why?",
    "Explain why Tariq Mahmoud Haddad is critical risk, with evidence and policy references.",
    "Which customers structured cash deposits under AED 55,000 in the last 30 days?",
    "Did our LCR breach the 110% early-warning trigger? What drove it?",
    "What is our exposure to high-risk and prohibited jurisdictions?",
    "What does our policy say we must do on a sanctions true match?",
    "Open a case for Tariq Mahmoud Haddad and draft the STR.",
]

st.session_state.setdefault("chat", [])

with st.expander("Try a question", expanded=not st.session_state["chat"]):
    cols = st.columns(2)
    for i, s in enumerate(SAMPLES):
        if cols[i % 2].button(s, key=f"sample{i}", use_container_width=True):
            st.session_state["pending"] = s


def render_result(r: dict):
    if r.get("error"):
        st.error(f"The copilot could not complete this request safely: {r['error']}")
        return
    st.markdown(r.get("text") or "_No answer returned._")
    for df in r.get("tables", [])[:3]:
        st.dataframe(df, hide_index=True, use_container_width=True)
    tools = r.get("tools", [])
    if tools or r.get("sql") or r.get("citations"):
        with st.expander(f"How I answered · {len(tools)} tool call(s) · {len(r.get('citations', []))} citation(s)"):
            if tools:
                st.markdown(" → ".join(f"`{t.get('name')}`" for t in tools))
            for s in r.get("sql", []):
                st.code(s, language="sql")
            for c in r.get("citations", [])[:6]:
                citation(c)


for m in st.session_state["chat"]:
    with st.chat_message(m["role"], avatar="🧑‍💼" if m["role"] == "user" else "🛡️"):
        if m["role"] == "user":
            st.markdown(m["text"])
        else:
            render_result(m["result"])

prompt = st.chat_input("Ask about customers, alerts, typologies, LCR, credit risk or policy…")
prompt = prompt or st.session_state.pop("pending", None)

if prompt:
    st.session_state["chat"].append({"role": "user", "text": prompt})
    with st.chat_message("user", avatar="🧑‍💼"):
        st.markdown(prompt)
    # Conversation history for the agent (text turns only)
    messages = []
    for m in st.session_state["chat"][-8:]:
        text = m["text"] if m["role"] == "user" else (m["result"].get("text") or "")
        messages.append({"role": m["role"] if m["role"] == "user" else "assistant",
                         "content": [{"type": "text", "text": text}]})
    with st.chat_message("assistant", avatar="🛡️"):
        with st.spinner("Raqib is reasoning across data, tools and policies…"):
            try:
                result, ms = timed(be.agent, messages)
            except Exception as e:  # graceful failure: never a stack trace in front of a user
                result, ms = {"error": f"{type(e).__name__}: {str(e)[:200]}"}, 0
        render_result(result)
        if not result.get("error"):
            st.caption(f"Answered in {ms / 1000:.1f}s · persona: {st.session_state['persona']} · logged to OPS.COPILOT_AUDIT")
    st.session_state["chat"].append({"role": "assistant", "result": result})
    try:
        be.audit_copilot(st.session_state["persona"], prompt, result, ms)
    except Exception:  # audit must never block the user; failures surface in Governance page counts
        pass
    if any(t.get("type") == "generic" for t in result.get("tools", [])):
        invalidate()

if st.session_state["chat"] and st.button("Clear conversation"):
    st.session_state["chat"] = []
    st.rerun()
