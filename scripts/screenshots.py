"""Capture app screenshots (offline mode) for the deck and README. Usage: python scripts/screenshots.py [base_url]"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
PAGES = {"01_command_center": "", "02_copilot": "copilot", "03_investigate": "investigate",
         "04_cases_reports": "cases", "05_regulatory_risk": "regulatory", "06_governance": "governance"}


def wait(page):
    page.wait_for_selector("[data-testid='stApp']", timeout=60000)
    page.wait_for_timeout(1500)
    page.wait_for_function("!document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=90000)
    page.wait_for_timeout(2500)


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 1000}, device_scale_factor=1)
    for name, path in PAGES.items():
        page.goto(f"{BASE}/{path}")
        wait(page)
        if name == "02_copilot":
            page.get_by_role("button", name="Explain why Tariq Mahmoud Haddad is critical risk, with evidence and policy references.").click()
            wait(page)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        print("saved", name)
    b.close()
