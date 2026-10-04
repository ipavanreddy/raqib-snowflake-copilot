-- =====================================================================================
-- Raqib | 11 AUTOMATION: live feed simulator, alert routing, scheduled reporting
--   SIMULATE_ACTIVITY  : injects realistic activity (incl. a fresh typology) into RAW so the
--                        dynamic-table pipeline raises a brand-new alert live in the demo
--   ALERT_ROUTER task  : stream on DETECT.ALERTS -> notification outbox (Slack via CoCo MCP)
--   DAILY_BRIEFING task: 07:00 Dubai, AML MI + LCR report drafts
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE OR REPLACE PROCEDURE RAQIB.OPS.SIMULATE_ACTIVITY(P_SCENARIO VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  HANDLER = 'run'
  COMMENT = 'Demo feed: STRUCTURING | ATO | BACKGROUND. Inserts new rows into RAW tables.'
  EXECUTE AS OWNER
AS
$$
import random, uuid
from datetime import timedelta

BRANCHES = ["DXB-DEIRA", "DXB-KARAMA", "SHJ-ROLLA", "AJM-CENTRAL", "DXB-BURDUBAI", "AUH-MUSSAFAH"]

def _ins_txn(session, rows):
    for r in rows:
        session.sql("""INSERT INTO RAQIB.RAW.TRANSACTIONS (TXN_ID, ACCOUNT_ID, TXN_TS, DIRECTION, CHANNEL, AMOUNT, CURRENCY,
                       AMOUNT_AED, COUNTERPARTY_ID, COUNTERPARTY_COUNTRY, PURPOSE_CODE, DESCRIPTION, BRANCH_ID)
                       SELECT ?, ?, ?::TIMESTAMP_NTZ, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?""", params=r).collect()

def _clean_customer(session, where):
    return session.sql(f"""
        SELECT p.CUSTOMER_ID, a.ACCOUNT_ID, p.FULL_NAME FROM RAQIB.CORE.CUSTOMER_PROFILE p
        JOIN RAQIB.RAW.ACCOUNTS a ON a.CUSTOMER_ID = p.CUSTOMER_ID AND a.CURRENCY = 'AED' AND a.ACCOUNT_TYPE IN ('CURRENT','BUSINESS')
        WHERE p.CUSTOMER_ID NOT IN (SELECT CUSTOMER_ID FROM RAQIB.DETECT.ALERTS) AND {where}
        ORDER BY RANDOM() LIMIT 1""").collect()[0]

def run(session, p_scenario):
    scenario = (p_scenario or "BACKGROUND").upper()
    now = session.sql("SELECT MAX(TXN_TS) AS T FROM RAQIB.RAW.TRANSACTIONS").collect()[0]["T"]
    rng = random.Random()
    rows = []
    if scenario == "STRUCTURING":
        c = _clean_customer(session, "p.CUSTOMER_TYPE = 'INDIVIDUAL' AND p.KYC_RISK_RATING = 'LOW'")
        for k in range(4):
            ts = now - timedelta(days=3 - k, hours=rng.randint(0, 5))
            amt = round(rng.uniform(47000, 54800), 2)
            rows.append([f"LIVE-{uuid.uuid4().hex[:10]}", c["ACCOUNT_ID"], str(ts), "CREDIT", "CASH_DEPOSIT", amt, "AED", amt,
                         None, None, None, "Cash deposit", BRANCHES[k]])
        _ins_txn(session, rows)
        detail = f"4 cash deposits under AED 55,000 for {c['FULL_NAME']} ({c['CUSTOMER_ID']}) across 4 branches"
    elif scenario == "ATO":
        c = _clean_customer(session, "p.SEGMENT = 'PRIORITY'")
        dev = f"DEV-UNSEEN-{rng.randint(1000, 9999)}"
        t0 = now - timedelta(hours=2)
        for i, et in enumerate(["OTP_FAILED", "PASSWORD_RESET", "NEW_DEVICE", "BENEFICIARY_ADDED"]):
            session.sql("""INSERT INTO RAQIB.RAW.DIGITAL_EVENTS (EVENT_ID, CUSTOMER_ID, EVENT_TS, EVENT_TYPE, DEVICE_ID, IP_COUNTRY)
                           SELECT ?, ?, ?::TIMESTAMP_NTZ, ?, ?, 'NG'""",
                        params=[f"LIVE-{uuid.uuid4().hex[:10]}", c["CUSTOMER_ID"], str(t0 + timedelta(minutes=3 * i)), et, dev]).collect()
        cp = session.sql("SELECT COUNTERPARTY_ID FROM RAQIB.RAW.COUNTERPARTIES WHERE COUNTRY_CODE = 'AE' AND COUNTERPARTY_TYPE = 'INDIVIDUAL' ORDER BY RANDOM() LIMIT 1").collect()[0][0]
        for k in range(3):
            amt = round(rng.uniform(25000, 60000), 2)
            rows.append([f"LIVE-{uuid.uuid4().hex[:10]}", c["ACCOUNT_ID"], str(t0 + timedelta(minutes=15 + 6 * k)), "DEBIT",
                         "INTERNAL_TRANSFER", amt, "AED", amt, cp, "AE", None, "Online transfer", None])
        _ins_txn(session, rows)
        detail = f"Account takeover pattern on {c['FULL_NAME']} ({c['CUSTOMER_ID']}): foreign new device, reset, beneficiary, 3 transfers"
    else:
        accts = session.sql("""SELECT ACCOUNT_ID FROM RAQIB.RAW.ACCOUNTS WHERE CURRENCY = 'AED' ORDER BY RANDOM() LIMIT 40""").collect()
        for a in accts:
            amt = round(rng.lognormvariate(5.2, 0.9), 2)
            rows.append([f"LIVE-{uuid.uuid4().hex[:10]}", a[0], str(now + timedelta(minutes=rng.randint(1, 30))), "DEBIT",
                         "CARD_POS", amt, "AED", amt, None, "AE", None, "Card purchase", None])
        _ins_txn(session, rows)
        detail = f"{len(rows)} routine card transactions"
    # refresh the pipeline immediately so the demo does not wait for TARGET_LAG
    for dt in ["RAQIB.CORE.TXN_ENRICHED", "RAQIB.CORE.CUSTOMER_PROFILE", "RAQIB.DETECT.ALERTS", "RAQIB.DETECT.CUSTOMER_RISK"]:
        session.sql(f"ALTER DYNAMIC TABLE {dt} REFRESH").collect()
    return {"ok": True, "scenario": scenario, "inserted_transactions": len(rows), "detail": detail}
$$;

-- -------------------------------------------------------------------------------------
-- Alert routing: new HIGH/CRITICAL alerts -> notification outbox (deduplicated)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE STREAM RAQIB.OPS.ALERTS_STREAM ON DYNAMIC TABLE RAQIB.DETECT.ALERTS
  COMMENT = 'Change feed of alerts for routing';

CREATE OR REPLACE TASK RAQIB.OPS.ALERT_ROUTER
  WAREHOUSE = RAQIB_WH
  SCHEDULE = '5 MINUTES'
  COMMENT = 'Routes newly raised HIGH/CRITICAL alerts to the notification outbox'
  WHEN SYSTEM$STREAM_HAS_DATA('RAQIB.OPS.ALERTS_STREAM')
AS
INSERT INTO RAQIB.OPS.NOTIFICATIONS (NOTIFICATION_ID, CREATED_AT, CHANNEL, SEVERITY, TITLE, BODY, OBJECT_ID, STATUS)
SELECT
    UUID_STRING(), CURRENT_TIMESTAMP(), 'slack', s.SEVERITY,
    'New ' || s.SEVERITY || ' alert ' || s.ALERT_ID || ' (' || s.RULE_ID || ')',
    r.FULL_NAME || ' (' || s.CUSTOMER_ID || ', risk ' || r.RISK_SCORE || ' ' || r.RISK_BAND || '): ' || s.TRIGGER_SUMMARY,
    s.ALERT_ID, 'PENDING'
FROM RAQIB.OPS.ALERTS_STREAM s
JOIN RAQIB.DETECT.CUSTOMER_RISK r ON r.CUSTOMER_ID = s.CUSTOMER_ID
WHERE s.METADATA$ACTION = 'INSERT'
  AND s.SEVERITY IN ('HIGH', 'CRITICAL')
  AND NOT EXISTS (SELECT 1 FROM RAQIB.OPS.NOTIFICATIONS n WHERE n.OBJECT_ID = s.ALERT_ID);

-- Baseline: mark alerts that exist at deploy time as already notified, so only NEW ones page
INSERT INTO RAQIB.OPS.NOTIFICATIONS (NOTIFICATION_ID, CREATED_AT, CHANNEL, SEVERITY, TITLE, BODY, OBJECT_ID, STATUS)
SELECT UUID_STRING(), CURRENT_TIMESTAMP(), 'slack', SEVERITY, 'Baseline', 'Existing at deploy', ALERT_ID, 'SKIPPED'
FROM RAQIB.DETECT.ALERTS a
WHERE NOT EXISTS (SELECT 1 FROM RAQIB.OPS.NOTIFICATIONS n WHERE n.OBJECT_ID = a.ALERT_ID);

-- -------------------------------------------------------------------------------------
-- Daily regulatory briefing (07:00 Gulf Standard Time)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TASK RAQIB.OPS.DAILY_BRIEFING
  WAREHOUSE = RAQIB_WH
  SCHEDULE = 'USING CRON 0 7 * * * Asia/Dubai'
  COMMENT = 'Drafts the AML MI report every morning'
AS
CALL RAQIB.OPS.GENERATE_REGULATORY_REPORT('AML_MI');

CREATE OR REPLACE TASK RAQIB.OPS.DAILY_LCR_REPORT
  WAREHOUSE = RAQIB_WH
  AFTER RAQIB.OPS.DAILY_BRIEFING
  COMMENT = 'Drafts the LCR report after the AML briefing'
AS
CALL RAQIB.OPS.GENERATE_REGULATORY_REPORT('LCR');

ALTER TASK RAQIB.OPS.DAILY_LCR_REPORT RESUME;
ALTER TASK RAQIB.OPS.DAILY_BRIEFING RESUME;
ALTER TASK RAQIB.OPS.ALERT_ROUTER RESUME;

-- Demo: inject a fresh structuring pattern and watch it surface
-- CALL RAQIB.OPS.SIMULATE_ACTIVITY('STRUCTURING');
-- EXECUTE TASK RAQIB.OPS.ALERT_ROUTER;
-- SELECT * FROM RAQIB.OPS.NOTIFICATIONS WHERE STATUS = 'PENDING' ORDER BY CREATED_AT DESC;

-- Credit protection after the hackathon:
-- ALTER TASK RAQIB.OPS.ALERT_ROUTER SUSPEND; ALTER TASK RAQIB.OPS.DAILY_BRIEFING SUSPEND;
-- ALTER DYNAMIC TABLE RAQIB.DETECT.ALERTS SUSPEND; ALTER DYNAMIC TABLE RAQIB.DETECT.CUSTOMER_RISK SUSPEND;
