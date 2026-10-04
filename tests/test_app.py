"""End-to-end UI journey in offline mode (Streamlit AppTest): signal -> evidence -> case -> STR -> MLRO filing."""
import os
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app"
os.environ["RAQIB_OFFLINE"] = "1"
sys.path.insert(0, str(APP))  # streamlit puts the main script dir on sys.path; AppTest on a page does not
SAMPLES = [
    "Who are the top 5 highest-risk customers and why?",
    "Explain why Tariq Mahmoud Haddad is critical risk, with evidence and policy references.",
    "Which customers structured cash deposits under AED 55,000 in the last 30 days?",
    "Did our LCR breach the 110% early-warning trigger? What drove it?",
    "What is our exposure to high-risk and prohibited jurisdictions?",
    "What does our policy say we must do on a sanctions true match?",
    "What is the NPL ratio by sector?",
]


@pytest.fixture(autouse=True)
def _cwd(monkeypatch):
    monkeypatch.chdir(APP)


def run(page, **state):
    at = AppTest.from_file(str(APP / page), default_timeout=180)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, at.exception[0].value
    return at


@pytest.mark.parametrize("question", SAMPLES)
def test_copilot_answers(question):
    at = run("pages/1_Copilot.py")
    at.chat_input[0].set_value(question).run()
    assert not at.exception, at.exception[0].value
    answer = " ".join(m.value for m in at.markdown)
    assert "could not complete" not in answer
    assert len(at.session_state["chat"]) == 2


def test_full_journey_case_str_and_filing():
    at = run("pages/2_Investigate.py")
    open_btn = next(b for b in at.button if b.label == "Open case & escalate")
    open_btn.click().run()
    assert not at.exception
    assert any("Case CASE-" in s.value for s in at.success), [e.value for e in at.error]

    at = run("pages/3_Cases_and_Reports.py")
    next(b for b in at.button if "Draft STR" in b.label).click().run()
    assert not at.exception
    assert at.success or at.warning

    at = run("pages/3_Cases_and_Reports.py", persona="MLRO")
    assert not at.exception
    approve = [b for b in at.button if "Approve" in b.label]
    if approve:  # only when validation passed
        approve[0].click().run()
        assert not at.exception


def test_inject_live_structuring_raises_new_alert():
    at = run("pages/0_Command_Center.py")
    at.selectbox[1].set_value("STRUCTURING").run()
    next(b for b in at.button if "Inject" in b.label).click().run()
    assert not at.exception
    assert "cash deposits under AED 55,000" in at.session_state["last_sim"]["detail"]
