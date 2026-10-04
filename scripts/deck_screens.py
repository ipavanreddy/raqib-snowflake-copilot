"""Curated viewport screenshots for the submission deck (app must be running offline on :8501)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8501"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"


def settle(page, extra=2500):
    page.wait_for_selector("[data-testid='stApp']", timeout=60000)
    page.wait_for_timeout(1200)
    page.wait_for_function("!document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=120000)
    page.wait_for_timeout(extra)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 860})
    page.goto(f"{BASE}/copilot"); settle(page)
    page.get_by_role("button", name="Explain why Tariq Mahmoud Haddad is critical risk, with evidence and policy references.").click()
    settle(page)
    page.get_by_text("is CRITICAL risk", exact=False).first.scroll_into_view_if_needed()
    page.mouse.wheel(0, -120); page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "deck_copilot.png"))

    page.goto(f"{BASE}/investigate"); settle(page)
    page.get_by_role("tab", name="Money flow").click(); page.wait_for_timeout(2500)
    page.get_by_role("tab", name="Money flow").scroll_into_view_if_needed(); page.mouse.wheel(0, 250); page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "deck_moneyflow.png"))
    page.get_by_role("button", name="Open case & escalate").click(); settle(page)

    page.goto(f"{BASE}/cases"); settle(page)
    page.get_by_role("button", name="✍️ Draft STR with Raqib").click(); settle(page)
    page.get_by_role("tab", name="STR reports").click(); page.wait_for_timeout(2000)
    page.get_by_text("Amounts reconciled").first.scroll_into_view_if_needed(); page.mouse.wheel(0, -60); page.wait_for_timeout(800)
    page.screenshot(path=str(OUT / "deck_str.png"))

    page.goto(f"{BASE}/"); settle(page)
    page.screenshot(path=str(OUT / "deck_command_center.png"))
    b.close()
print("ok")
