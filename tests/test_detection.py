"""Detection quality gates: every planted typology must be caught; false positives bounded."""
import pytest

from sql_harness import build_all

MAX_FP_PER_RULE = 12   # alerts on non-planted customers (realistic noise, still triage-able)


@pytest.fixture(scope="module")
def con():
    return build_all()


def test_every_planted_case_detected(con):
    missed = con.sql("""
        WITH exp AS (
            SELECT SCENARIO_ID, TYPOLOGY, CUSTOMER_ID, UNNEST(STRING_SPLIT(EXPECTED_RULE, '|')) AS RULE_ID
            FROM RAQIB.RAW.PLANTED_CASES)
        SELECT * FROM exp e
        WHERE NOT EXISTS (SELECT 1 FROM RAQIB.DETECT.ALERTS a
                          WHERE a.CUSTOMER_ID = e.CUSTOMER_ID AND a.RULE_ID = e.RULE_ID)""").fetchall()
    assert missed == [], f"missed planted cases: {missed}"


def test_false_positive_volume(con):
    rows = con.sql("""
        SELECT RULE_ID, COUNT(*) FROM RAQIB.DETECT.ALERTS
        WHERE CUSTOMER_ID NOT IN (SELECT CUSTOMER_ID FROM RAQIB.RAW.PLANTED_CASES)
        GROUP BY 1""").fetchall()
    noisy = {r: n for r, n in rows if n > MAX_FP_PER_RULE}
    assert not noisy, f"rules too noisy: {noisy}"


def test_hero_case_is_critical_and_top5(con):
    top = con.sql("""SELECT FULL_NAME, RISK_BAND FROM RAQIB.DETECT.CUSTOMER_RISK
                     ORDER BY RISK_SCORE DESC, ALERTED_AMOUNT_AED DESC LIMIT 5""").fetchall()
    assert ("Tariq Mahmoud Haddad", "CRITICAL") in top, top


def test_planted_customers_dominate_top_of_queue(con):
    share = con.sql("""SELECT AVG(CASE WHEN CUSTOMER_ID IN (SELECT CUSTOMER_ID FROM RAQIB.RAW.PLANTED_CASES) THEN 1 ELSE 0 END)
                       FROM (SELECT * FROM RAQIB.DETECT.CUSTOMER_RISK ORDER BY RISK_SCORE DESC LIMIT 30)""").fetchone()[0]
    assert share >= 0.8, share


def test_alert_ids_unique_and_evidenced(con):
    dup = con.sql("SELECT ALERT_ID FROM RAQIB.DETECT.ALERTS GROUP BY 1 HAVING COUNT(*) > 1").fetchall()
    assert dup == []
    no_ev = con.sql("""SELECT ALERT_ID, RULE_ID FROM RAQIB.DETECT.ALERTS a
                       WHERE NOT EXISTS (SELECT 1 FROM RAQIB.DETECT.ALERT_EVIDENCE e WHERE e.ALERT_ID = a.ALERT_ID)""").fetchall()
    assert no_ev == [], f"alerts without evidence: {no_ev}"


def test_watchlist_no_partial_company_matches(con):
    bad = con.sql("""SELECT COUNTERPARTY_NAME, ENTRY_NAME, SIMILARITY FROM RAQIB.DETECT.WATCHLIST_MATCHES
                     WHERE COUNTERPARTY_NAME LIKE 'Golden Crescent %' AND COUNTERPARTY_NAME NOT LIKE 'Golden Crescent Exchange%'""").fetchall()
    assert bad == []


def test_lcr_stress_episode_visible_but_no_breach(con):
    lo, ew, br = con.sql("""SELECT MIN(LCR_PCT), SUM(CASE WHEN LCR_STATUS = 'EARLY_WARNING' THEN 1 ELSE 0 END),
                                   SUM(CASE WHEN LCR_STATUS = 'BREACH' THEN 1 ELSE 0 END) FROM RAQIB.RISK.LCR_DAILY""").fetchone()
    assert 100 <= lo < 110 and ew >= 3 and br == 0, (lo, ew, br)


def test_credit_kpis_plausible(con):
    npl, cov = con.sql("""SELECT 100 * SUM(CASE WHEN IS_NPL THEN EAD_AED ELSE 0 END) / SUM(EAD_AED),
                                 100 * SUM(ECL_AED) / SUM(EAD_AED) FROM RAQIB.RISK.LOAN_ECL""").fetchone()
    assert 2 <= npl <= 8 and 1 <= cov <= 8, (npl, cov)
