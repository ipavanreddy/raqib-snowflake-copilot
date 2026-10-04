-- =====================================================================================
-- Raqib | 04 DETECTION layer
-- Each rule is a view whose ID matches a section of the Transaction Monitoring Rulebook
-- (policy_docs/02_transaction_monitoring_rulebook.md). The copilot cites both.
--
-- Every rule view returns the same shape:
--   RULE_ID, CUSTOMER_ID, ACCOUNT_ID, WINDOW_START, WINDOW_END, AMOUNT_AED, TXN_COUNT,
--   FOCUS_COUNTERPARTY_ID, METRICS (OBJECT), TRIGGER_SUMMARY
-- Alerts are consolidated to one per customer x rule (x counterparty for TM-06) per review
-- period, which keeps the alert ID stable as new data arrives.
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE OR REPLACE TABLE RAQIB.DETECT.RULE_CATALOG (
    RULE_ID           VARCHAR PRIMARY KEY,
    RULE_NAME         VARCHAR,
    TYPOLOGY          VARCHAR,
    SEVERITY          VARCHAR,
    BASE_SCORE        NUMBER,
    LOGIC_SUMMARY     VARCHAR,
    POLICY_REFERENCE  VARCHAR
) COMMENT = 'Detection rule metadata; mirrors the Transaction Monitoring Rulebook';

INSERT INTO RAQIB.DETECT.RULE_CATALOG VALUES
 ('TM-01', 'Cash structuring below reporting threshold', 'Structuring / smurfing', 'HIGH', 30,
  '>=3 cash deposits each AED 45,000-54,999 by the same customer within 7 days', 'TM Rulebook s.4.1; AML/CFT Policy s.7.2'),
 ('TM-02', 'Rapid pass-through of funds', 'Layering', 'HIGH', 30,
  '>= 2 episodes where a credit >= AED 200,000 (and >= 50% of declared monthly turnover) is followed within 48h by debits of 90-110% of it to >= 2 counterparties incl. one cross-border', 'TM Rulebook s.4.2; AML/CFT Policy s.7.3'),
 ('TM-03', 'Fan-in from many unrelated senders', 'Money mule', 'HIGH', 25,
  'Individual account receives from >= 10 distinct senders within 7 days', 'TM Rulebook s.4.3; Fraud Typologies s.3'),
 ('TM-04', 'High-risk jurisdiction exposure', 'Geographic risk', 'HIGH', 25,
  'Any wire to a PROHIBITED jurisdiction, or >= AED 100,000 in a calendar month to HIGH-risk jurisdictions', 'TM Rulebook s.4.4; Sanctions Procedure s.5'),
 ('TM-05', 'Dormant account reactivation', 'Account misuse', 'MEDIUM', 20,
  'First activity after >= 180 days of dormancy with >= AED 100,000 credits within 30 days', 'TM Rulebook s.4.5'),
 ('TM-06', 'Watchlist name match on counterparty', 'Sanctions', 'CRITICAL', 40,
  'Counterparty name Jaro-Winkler similarity >= 90, or identical first and last name tokens, to a sanctions / PEP / blacklist entry', 'TM Rulebook s.4.6; Sanctions Procedure s.4'),
 ('TM-07', 'Activity inconsistent with customer profile', 'Profile deviation', 'MEDIUM', 15,
  'Third-party and cash credits over any 30 days >= 5x declared expected monthly turnover and >= AED 50,000', 'TM Rulebook s.4.7; CDD Standard s.6'),
 ('FR-01', 'Account takeover pattern', 'Fraud - ATO', 'CRITICAL', 35,
  'Beneficiary added from a device first seen <24h earlier with foreign IP or password reset in prior hour, then >= AED 20,000 debited within 2h', 'TM Rulebook s.5.1; Fraud Typologies s.2');

-- -------------------------------------------------------------------------------------
-- TM-01 Structuring
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.TM01_STRUCTURING
  COMMENT = 'TM-01: repeated cash deposits just below the AED 55,000 threshold'
AS
WITH cash AS (
    SELECT TXN_ID, CUSTOMER_ID, ACCOUNT_ID, TXN_TS, AMOUNT_AED, BRANCH_ID
    FROM RAQIB.CORE.TXN_ENRICHED
    WHERE CHANNEL = 'CASH_DEPOSIT' AND AMOUNT_AED >= 45000 AND AMOUNT_AED < 55000
),
win AS (
    SELECT
        a.CUSTOMER_ID,
        a.TXN_TS                     AS WINDOW_START,
        MAX(b.TXN_TS)                AS WINDOW_END,
        MIN(b.ACCOUNT_ID)            AS ACCOUNT_ID,
        COUNT(*)                     AS DEPOSIT_COUNT,
        COUNT(DISTINCT b.BRANCH_ID)  AS BRANCH_COUNT,
        SUM(b.AMOUNT_AED)            AS TOTAL_AED
    FROM cash a
    JOIN cash b
      ON b.CUSTOMER_ID = a.CUSTOMER_ID
     AND b.TXN_TS >= a.TXN_TS
     AND b.TXN_TS < DATEADD('day', 7, a.TXN_TS)
    GROUP BY a.CUSTOMER_ID, a.TXN_TS
)
SELECT
    'TM-01'               AS RULE_ID,
    CUSTOMER_ID,
    ACCOUNT_ID,
    WINDOW_START,
    WINDOW_END,
    TOTAL_AED             AS AMOUNT_AED,
    DEPOSIT_COUNT         AS TXN_COUNT,
    NULL::VARCHAR         AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('deposit_count', DEPOSIT_COUNT, 'branch_count', BRANCH_COUNT,
                     'total_aed', ROUND(TOTAL_AED, 2), 'threshold_aed', 55000) AS METRICS,
    DEPOSIT_COUNT || ' cash deposits of AED 45,000-54,999 (total AED ' || TO_VARCHAR(CAST(ROUND(TOTAL_AED, 0) AS NUMBER(38, 0)))
        || ') across ' || BRANCH_COUNT || ' branches within 7 days' AS TRIGGER_SUMMARY
FROM win
WHERE DEPOSIT_COUNT >= 3
QUALIFY ROW_NUMBER() OVER (PARTITION BY CUSTOMER_ID ORDER BY DEPOSIT_COUNT DESC, TOTAL_AED DESC) = 1;

-- -------------------------------------------------------------------------------------
-- TM-02 Rapid pass-through
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.TM02_PASS_THROUGH
  COMMENT = 'TM-02: repeated amount-matched forwarding (90-110%) of large credits within 48h'
AS
WITH inflow AS (
    -- material credits: >= AED 200k and >= 50% of the customer's declared monthly turnover
    SELECT t.TXN_ID, t.CUSTOMER_ID, t.ACCOUNT_ID, t.TXN_TS, t.AMOUNT_AED
    FROM RAQIB.CORE.TXN_ENRICHED t
    JOIN RAQIB.RAW.CUSTOMERS c ON c.CUSTOMER_ID = t.CUSTOMER_ID
    WHERE t.DIRECTION = 'CREDIT'
      AND t.AMOUNT_AED >= 200000
      AND t.AMOUNT_AED >= 0.5 * c.EXPECTED_MONTHLY_TURNOVER_AED
),
episode AS (
    SELECT
        i.TXN_ID,
        i.CUSTOMER_ID,
        i.ACCOUNT_ID,
        i.TXN_TS                              AS IN_TS,
        i.AMOUNT_AED                          AS IN_AED,
        SUM(o.AMOUNT_AED)                     AS OUT_AED,
        COUNT(DISTINCT o.COUNTERPARTY_ID)     AS OUT_COUNTERPARTIES,
        COUNT(DISTINCT o.COUNTERPARTY_COUNTRY) AS OUT_COUNTRIES,
        MAX(o.TXN_TS)                         AS LAST_OUT_TS
    FROM inflow i
    JOIN RAQIB.CORE.TXN_ENRICHED o
      ON o.ACCOUNT_ID = i.ACCOUNT_ID
     AND o.DIRECTION = 'DEBIT'
     AND o.TXN_TS >= i.TXN_TS
     AND o.TXN_TS <= DATEADD('hour', 48, i.TXN_TS)
    GROUP BY i.TXN_ID, i.CUSTOMER_ID, i.ACCOUNT_ID, i.TXN_TS, i.AMOUNT_AED
    HAVING SUM(o.AMOUNT_AED) BETWEEN 0.9 * i.AMOUNT_AED AND 1.1 * i.AMOUNT_AED
       AND COUNT(DISTINCT o.COUNTERPARTY_ID) >= 2
       AND COUNT_IF(o.COUNTERPARTY_COUNTRY <> 'AE') >= 1
)
SELECT
    'TM-02'                     AS RULE_ID,
    CUSTOMER_ID,
    MIN(ACCOUNT_ID)             AS ACCOUNT_ID,
    MIN(IN_TS)                  AS WINDOW_START,
    MAX(LAST_OUT_TS)            AS WINDOW_END,
    SUM(IN_AED)                 AS AMOUNT_AED,
    COUNT(*)                    AS TXN_COUNT,
    NULL::VARCHAR               AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('episodes', COUNT(*), 'total_in_aed', ROUND(SUM(IN_AED), 2),
                     'total_out_aed', ROUND(SUM(OUT_AED), 2),
                     'pass_through_ratio', ROUND(SUM(OUT_AED) / SUM(IN_AED), 3),
                     'max_destination_countries', MAX(OUT_COUNTRIES)) AS METRICS,
    COUNT(*) || ' episode(s): AED ' || TO_VARCHAR(CAST(ROUND(SUM(IN_AED), 0) AS NUMBER(38, 0))) || ' received and '
        || TO_VARCHAR(CAST(ROUND(100 * SUM(OUT_AED) / SUM(IN_AED), 0) AS NUMBER(38, 0))) || '% forwarded within 48h' AS TRIGGER_SUMMARY
FROM episode
GROUP BY CUSTOMER_ID
HAVING COUNT(*) >= 2;

-- -------------------------------------------------------------------------------------
-- TM-03 Fan-in (money mule)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.TM03_FAN_IN
  COMMENT = 'TM-03: individual receives from >=10 distinct senders within 7 days'
AS
WITH cr AS (
    SELECT TXN_ID, CUSTOMER_ID, ACCOUNT_ID, TXN_TS, AMOUNT_AED, COUNTERPARTY_ID
    FROM RAQIB.CORE.TXN_ENRICHED
    WHERE DIRECTION = 'CREDIT'
      AND CUSTOMER_TYPE = 'INDIVIDUAL'
      AND COUNTERPARTY_ID IS NOT NULL
      AND CHANNEL IN ('INTERNAL_TRANSFER', 'WIRE_IN')
),
win AS (
    SELECT
        a.CUSTOMER_ID,
        a.ACCOUNT_ID,
        a.TXN_TS                            AS WINDOW_START,
        MAX(b.TXN_TS)                       AS WINDOW_END,
        COUNT(DISTINCT b.COUNTERPARTY_ID)   AS SENDERS,
        COUNT(*)                            AS CREDIT_COUNT,
        SUM(b.AMOUNT_AED)                   AS TOTAL_AED
    FROM cr a
    JOIN cr b
      ON b.ACCOUNT_ID = a.ACCOUNT_ID
     AND b.TXN_TS >= a.TXN_TS
     AND b.TXN_TS < DATEADD('day', 7, a.TXN_TS)
    GROUP BY a.CUSTOMER_ID, a.ACCOUNT_ID, a.TXN_TS
),
best AS (
    SELECT *
    FROM win
    WHERE SENDERS >= 10
    QUALIFY ROW_NUMBER() OVER (PARTITION BY CUSTOMER_ID ORDER BY SENDERS DESC, TOTAL_AED DESC) = 1
),
onward AS (
    SELECT b.CUSTOMER_ID, SUM(t.AMOUNT_AED) AS ONWARD_AED
    FROM best b
    JOIN RAQIB.CORE.TXN_ENRICHED t
      ON t.ACCOUNT_ID = b.ACCOUNT_ID
     AND t.DIRECTION = 'DEBIT'
     AND t.TXN_TS >= b.WINDOW_START
     AND t.TXN_TS <= DATEADD('day', 3, b.WINDOW_END)
    GROUP BY b.CUSTOMER_ID
)
SELECT
    'TM-03'               AS RULE_ID,
    b.CUSTOMER_ID,
    b.ACCOUNT_ID,
    b.WINDOW_START,
    b.WINDOW_END,
    b.TOTAL_AED           AS AMOUNT_AED,
    b.CREDIT_COUNT        AS TXN_COUNT,
    NULL::VARCHAR         AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('distinct_senders', b.SENDERS, 'credit_count', b.CREDIT_COUNT,
                     'total_in_aed', ROUND(b.TOTAL_AED, 2),
                     'onward_out_aed', ROUND(COALESCE(o.ONWARD_AED, 0), 2),
                     'tenure_days', p.TENURE_DAYS, 'age_years', p.AGE_YEARS) AS METRICS,
    b.SENDERS || ' distinct senders paid AED ' || TO_VARCHAR(CAST(ROUND(b.TOTAL_AED, 0) AS NUMBER(38, 0))) || ' within 7 days; AED '
        || TO_VARCHAR(CAST(ROUND(COALESCE(o.ONWARD_AED, 0), 0) AS NUMBER(38, 0))) || ' moved out within 3 days (account tenure '
        || p.TENURE_DAYS || ' days)' AS TRIGGER_SUMMARY
FROM best b
LEFT JOIN onward o                     ON o.CUSTOMER_ID = b.CUSTOMER_ID
LEFT JOIN RAQIB.CORE.CUSTOMER_PROFILE p ON p.CUSTOMER_ID = b.CUSTOMER_ID;

-- -------------------------------------------------------------------------------------
-- TM-04 High-risk jurisdiction exposure
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.TM04_HIGH_RISK_GEO
  COMMENT = 'TM-04: wires to PROHIBITED jurisdictions or >= AED 100k/month to HIGH-risk ones'
AS
WITH w AS (
    SELECT *
    FROM RAQIB.CORE.TXN_ENRICHED
    WHERE CHANNEL IN ('WIRE_OUT', 'WIRE_IN')
      AND COUNTERPARTY_COUNTRY_RISK IN ('HIGH', 'PROHIBITED')
),
monthly AS (
    SELECT CUSTOMER_ID, DATE_TRUNC('month', TXN_TS) AS MTH, SUM(AMOUNT_AED) AS MTH_AED
    FROM w
    GROUP BY CUSTOMER_ID, DATE_TRUNC('month', TXN_TS)
),
qualifying AS (
    SELECT CUSTOMER_ID
    FROM w
    GROUP BY CUSTOMER_ID
    HAVING COUNT_IF(COUNTERPARTY_COUNTRY_RISK = 'PROHIBITED') > 0
    UNION
    SELECT CUSTOMER_ID FROM monthly WHERE MTH_AED >= 100000
)
SELECT
    'TM-04'                     AS RULE_ID,
    w.CUSTOMER_ID,
    MIN(w.ACCOUNT_ID)           AS ACCOUNT_ID,
    MIN(w.TXN_TS)               AS WINDOW_START,
    MAX(w.TXN_TS)               AS WINDOW_END,
    SUM(w.AMOUNT_AED)           AS AMOUNT_AED,
    COUNT(*)                    AS TXN_COUNT,
    NULL::VARCHAR               AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('countries', ARRAY_AGG(DISTINCT w.COUNTERPARTY_COUNTRY),
                     'prohibited_txn_count', COUNT_IF(w.COUNTERPARTY_COUNTRY_RISK = 'PROHIBITED'),
                     'high_risk_txn_count', COUNT_IF(w.COUNTERPARTY_COUNTRY_RISK = 'HIGH'),
                     'total_aed', ROUND(SUM(w.AMOUNT_AED), 2)) AS METRICS,
    COUNT(*) || ' wire(s) totalling AED ' || TO_VARCHAR(CAST(ROUND(SUM(w.AMOUNT_AED), 0) AS NUMBER(38, 0))) || ' with high-risk jurisdictions ('
        || COUNT_IF(w.COUNTERPARTY_COUNTRY_RISK = 'PROHIBITED') || ' to prohibited)' AS TRIGGER_SUMMARY
FROM w
JOIN qualifying q ON q.CUSTOMER_ID = w.CUSTOMER_ID
GROUP BY w.CUSTOMER_ID;

-- -------------------------------------------------------------------------------------
-- TM-05 Dormant account reactivation
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.TM05_DORMANT_REACTIVATION
  COMMENT = 'TM-05: activity after >=180 days dormancy with >= AED 100k credits in 30 days'
AS
WITH seq AS (
    SELECT
        t.TXN_ID, t.CUSTOMER_ID, t.ACCOUNT_ID, t.TXN_TS,
        COALESCE(LAG(t.TXN_TS) OVER (PARTITION BY t.ACCOUNT_ID ORDER BY t.TXN_TS),
                 a.LAST_ACTIVITY_BEFORE_WINDOW::TIMESTAMP_NTZ) AS PREV_TS
    FROM RAQIB.CORE.TXN_ENRICHED t
    JOIN RAQIB.RAW.ACCOUNTS a ON a.ACCOUNT_ID = t.ACCOUNT_ID
),
react AS (
    SELECT CUSTOMER_ID, ACCOUNT_ID, TXN_TS AS REACTIVATED_TS, PREV_TS,
           DATEDIFF('day', PREV_TS, TXN_TS) AS DORMANT_DAYS
    FROM seq
    WHERE DATEDIFF('day', PREV_TS, TXN_TS) >= 180
),
after AS (
    SELECT r.CUSTOMER_ID, r.ACCOUNT_ID, r.REACTIVATED_TS, r.DORMANT_DAYS,
           MAX(t.TXN_TS)       AS WINDOW_END,
           SUM(t.CREDIT_AED)   AS CREDITS_AED,
           SUM(t.DEBIT_AED)    AS DEBITS_AED,
           SUM(IFF(t.CHANNEL IN ('CASH_WITHDRAWAL', 'ATM'), t.AMOUNT_AED, 0)) AS CASH_OUT_AED,
           COUNT(*)            AS TXN_COUNT
    FROM react r
    JOIN RAQIB.CORE.TXN_ENRICHED t
      ON t.ACCOUNT_ID = r.ACCOUNT_ID
     AND t.TXN_TS >= r.REACTIVATED_TS
     AND t.TXN_TS < DATEADD('day', 30, r.REACTIVATED_TS)
    GROUP BY r.CUSTOMER_ID, r.ACCOUNT_ID, r.REACTIVATED_TS, r.DORMANT_DAYS
)
SELECT
    'TM-05'               AS RULE_ID,
    CUSTOMER_ID,
    ACCOUNT_ID,
    REACTIVATED_TS        AS WINDOW_START,
    WINDOW_END,
    CREDITS_AED           AS AMOUNT_AED,
    TXN_COUNT,
    NULL::VARCHAR         AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('dormant_days', DORMANT_DAYS, 'credits_30d_aed', ROUND(CREDITS_AED, 2),
                     'debits_30d_aed', ROUND(DEBITS_AED, 2), 'cash_out_aed', ROUND(CASH_OUT_AED, 2)) AS METRICS,
    'Dormant ' || DORMANT_DAYS || ' days, then AED ' || TO_VARCHAR(CAST(ROUND(CREDITS_AED, 0) AS NUMBER(38, 0))) || ' credited and AED '
        || TO_VARCHAR(CAST(ROUND(CASH_OUT_AED, 0) AS NUMBER(38, 0))) || ' withdrawn in cash within 30 days' AS TRIGGER_SUMMARY
FROM after
WHERE CREDITS_AED >= 100000
QUALIFY ROW_NUMBER() OVER (PARTITION BY CUSTOMER_ID ORDER BY CREDITS_AED DESC) = 1;

-- -------------------------------------------------------------------------------------
-- TM-06 Watchlist fuzzy match
-- Names are normalised (upper-case, punctuation -> space, collapsed whitespace) and compared
-- with Jaro-Winkler (0-100) >= 90, or matched on identical first + last tokens (catches
-- abbreviated middle names such as "Viktor A. Morozkin"). Calibrated in tests/test_detection.py.
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.WATCHLIST_MATCHES
  COMMENT = 'Counterparty-to-watchlist fuzzy matches with similarity score'
AS
WITH cp AS (
    SELECT COUNTERPARTY_ID, COUNTERPARTY_NAME,
           TRIM(REGEXP_REPLACE(REGEXP_REPLACE(UPPER(COUNTERPARTY_NAME), '[^A-Z0-9]', ' '), ' +', ' ')) AS NORM_NAME
    FROM RAQIB.RAW.COUNTERPARTIES
),
wl AS (
    SELECT ENTRY_ID, ENTRY_NAME, LIST_SOURCE, PROGRAM,
           TRIM(REGEXP_REPLACE(REGEXP_REPLACE(UPPER(ENTRY_NAME), '[^A-Z0-9]', ' '), ' +', ' ')) AS NORM_NAME
    FROM RAQIB.RAW.WATCHLIST
)
SELECT
    cp.COUNTERPARTY_ID, cp.COUNTERPARTY_NAME, wl.ENTRY_ID, wl.ENTRY_NAME, wl.LIST_SOURCE, wl.PROGRAM,
    JAROWINKLER_SIMILARITY(cp.NORM_NAME, wl.NORM_NAME) AS SIMILARITY,
    IFF(JAROWINKLER_SIMILARITY(cp.NORM_NAME, wl.NORM_NAME) >= 90, 'FUZZY_NAME', 'FIRST_LAST_TOKEN') AS MATCH_METHOD
FROM cp
CROSS JOIN wl
WHERE JAROWINKLER_SIMILARITY(cp.NORM_NAME, wl.NORM_NAME) >= 90
   OR (    REGEXP_SUBSTR(cp.NORM_NAME, '^[^ ]+') = REGEXP_SUBSTR(wl.NORM_NAME, '^[^ ]+')
       AND REGEXP_SUBSTR(cp.NORM_NAME, '[^ ]+$') = REGEXP_SUBSTR(wl.NORM_NAME, '[^ ]+$')
       AND LENGTH(REGEXP_SUBSTR(cp.NORM_NAME, '[^ ]+$')) >= 4
       AND JAROWINKLER_SIMILARITY(cp.NORM_NAME, wl.NORM_NAME) >= 75);

CREATE OR REPLACE VIEW RAQIB.DETECT.TM06_WATCHLIST
  COMMENT = 'TM-06: payments with counterparties matching a watchlist entry'
AS
SELECT
    'TM-06'                   AS RULE_ID,
    t.CUSTOMER_ID,
    MIN(t.ACCOUNT_ID)         AS ACCOUNT_ID,
    MIN(t.TXN_TS)             AS WINDOW_START,
    MAX(t.TXN_TS)             AS WINDOW_END,
    SUM(t.AMOUNT_AED)         AS AMOUNT_AED,
    COUNT(*)                  AS TXN_COUNT,
    m.COUNTERPARTY_ID         AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('counterparty_name', m.COUNTERPARTY_NAME, 'watchlist_entry_id', m.ENTRY_ID,
                     'watchlist_name', m.ENTRY_NAME, 'list_source', m.LIST_SOURCE,
                     'similarity', m.SIMILARITY, 'match_method', m.MATCH_METHOD, 'total_aed', ROUND(SUM(t.AMOUNT_AED), 2)) AS METRICS,
    COUNT(*) || ' payment(s), AED ' || TO_VARCHAR(CAST(ROUND(SUM(t.AMOUNT_AED), 0) AS NUMBER(38, 0))) || ', with "' || m.COUNTERPARTY_NAME
        || '" (' || m.SIMILARITY || '% match to ' || m.LIST_SOURCE || ' entry ' || m.ENTRY_ID || ' "' || m.ENTRY_NAME || '")' AS TRIGGER_SUMMARY
FROM RAQIB.CORE.TXN_ENRICHED t
JOIN RAQIB.DETECT.WATCHLIST_MATCHES m ON m.COUNTERPARTY_ID = t.COUNTERPARTY_ID
GROUP BY t.CUSTOMER_ID, m.COUNTERPARTY_ID, m.COUNTERPARTY_NAME, m.ENTRY_ID, m.ENTRY_NAME, m.LIST_SOURCE, m.SIMILARITY, m.MATCH_METHOD;

-- -------------------------------------------------------------------------------------
-- TM-07 Profile deviation
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.TM07_PROFILE_DEVIATION
  COMMENT = 'TM-07: 30-day third-party credits >= 5x declared monthly turnover'
AS
WITH cr AS (
    SELECT t.CUSTOMER_ID, t.ACCOUNT_ID, t.TXN_TS, t.AMOUNT_AED
    FROM RAQIB.CORE.TXN_ENRICHED t
    WHERE t.DIRECTION = 'CREDIT' AND (t.COUNTERPARTY_ID IS NOT NULL OR t.CHANNEL = 'CASH_DEPOSIT')
),
win AS (
    SELECT a.CUSTOMER_ID, a.TXN_TS AS WINDOW_START, MAX(b.TXN_TS) AS WINDOW_END,
           MIN(b.ACCOUNT_ID) AS ACCOUNT_ID, SUM(b.AMOUNT_AED) AS CREDITS_AED, COUNT(*) AS CREDIT_COUNT
    FROM cr a
    JOIN cr b
      ON b.CUSTOMER_ID = a.CUSTOMER_ID
     AND b.TXN_TS >= a.TXN_TS
     AND b.TXN_TS < DATEADD('day', 30, a.TXN_TS)
    GROUP BY a.CUSTOMER_ID, a.TXN_TS
)
SELECT
    'TM-07'               AS RULE_ID,
    w.CUSTOMER_ID,
    w.ACCOUNT_ID,
    w.WINDOW_START,
    w.WINDOW_END,
    w.CREDITS_AED         AS AMOUNT_AED,
    w.CREDIT_COUNT        AS TXN_COUNT,
    NULL::VARCHAR         AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('credits_30d_aed', ROUND(w.CREDITS_AED, 2),
                     'expected_monthly_turnover_aed', c.EXPECTED_MONTHLY_TURNOVER_AED,
                     'multiple', ROUND(w.CREDITS_AED / c.EXPECTED_MONTHLY_TURNOVER_AED, 1),
                     'occupation_or_industry', COALESCE(c.OCCUPATION, c.INDUSTRY)) AS METRICS,
    'AED ' || TO_VARCHAR(CAST(ROUND(w.CREDITS_AED, 0) AS NUMBER(38, 0))) || ' third-party and cash credits in 30 days = '
        || TO_VARCHAR(ROUND(w.CREDITS_AED / c.EXPECTED_MONTHLY_TURNOVER_AED, 1)) || 'x declared monthly turnover of AED '
        || TO_VARCHAR(CAST(ROUND(c.EXPECTED_MONTHLY_TURNOVER_AED, 0) AS NUMBER(38, 0))) AS TRIGGER_SUMMARY
FROM win w
JOIN RAQIB.RAW.CUSTOMERS c ON c.CUSTOMER_ID = w.CUSTOMER_ID
WHERE w.CREDITS_AED >= 5 * c.EXPECTED_MONTHLY_TURNOVER_AED
  AND w.CREDITS_AED >= 50000
QUALIFY ROW_NUMBER() OVER (PARTITION BY w.CUSTOMER_ID ORDER BY w.CREDITS_AED DESC) = 1;

-- -------------------------------------------------------------------------------------
-- FR-01 Account takeover
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.DETECT.FR01_ACCOUNT_TAKEOVER
  COMMENT = 'FR-01: new-device beneficiary add with foreign IP / password reset, then rapid debits'
AS
WITH first_seen AS (
    SELECT CUSTOMER_ID, DEVICE_ID, MIN(EVENT_TS) AS FIRST_SEEN_TS
    FROM RAQIB.RAW.DIGITAL_EVENTS
    GROUP BY CUSTOMER_ID, DEVICE_ID
),
benef AS (
    SELECT e.EVENT_ID, e.CUSTOMER_ID, e.EVENT_TS, e.DEVICE_ID, e.IP_COUNTRY
    FROM RAQIB.RAW.DIGITAL_EVENTS e
    JOIN first_seen f ON f.CUSTOMER_ID = e.CUSTOMER_ID AND f.DEVICE_ID = e.DEVICE_ID
    WHERE e.EVENT_TYPE = 'BENEFICIARY_ADDED'
      AND DATEDIFF('minute', f.FIRST_SEEN_TS, e.EVENT_TS) <= 1440
),
resets AS (
    SELECT b.EVENT_ID, COUNT(*) AS RESET_COUNT
    FROM benef b
    JOIN RAQIB.RAW.DIGITAL_EVENTS r
      ON r.CUSTOMER_ID = b.CUSTOMER_ID
     AND r.EVENT_TYPE IN ('PASSWORD_RESET', 'OTP_FAILED')
     AND r.EVENT_TS >= DATEADD('hour', -1, b.EVENT_TS)
     AND r.EVENT_TS <= b.EVENT_TS
    GROUP BY b.EVENT_ID
),
drains AS (
    SELECT b.EVENT_ID, MIN(t.ACCOUNT_ID) AS ACCOUNT_ID, SUM(t.AMOUNT_AED) AS DEBIT_AED,
           COUNT(*) AS DEBIT_COUNT, MAX(t.TXN_TS) AS LAST_DEBIT_TS
    FROM benef b
    JOIN RAQIB.CORE.TXN_ENRICHED t
      ON t.CUSTOMER_ID = b.CUSTOMER_ID
     AND t.DIRECTION = 'DEBIT'
     AND t.CHANNEL IN ('INTERNAL_TRANSFER', 'WIRE_OUT')
     AND t.TXN_TS >= b.EVENT_TS
     AND t.TXN_TS <= DATEADD('hour', 2, b.EVENT_TS)
    GROUP BY b.EVENT_ID
)
SELECT
    'FR-01'                 AS RULE_ID,
    b.CUSTOMER_ID,
    d.ACCOUNT_ID,
    b.EVENT_TS              AS WINDOW_START,
    d.LAST_DEBIT_TS         AS WINDOW_END,
    d.DEBIT_AED             AS AMOUNT_AED,
    d.DEBIT_COUNT           AS TXN_COUNT,
    NULL::VARCHAR           AS FOCUS_COUNTERPARTY_ID,
    OBJECT_CONSTRUCT('device_id', b.DEVICE_ID, 'ip_country', b.IP_COUNTRY,
                     'security_resets_prior_hour', COALESCE(r.RESET_COUNT, 0),
                     'debits_within_2h_aed', ROUND(d.DEBIT_AED, 2)) AS METRICS,
    'Beneficiary added from new device ' || b.DEVICE_ID || ' (IP ' || b.IP_COUNTRY || ', '
        || COALESCE(r.RESET_COUNT, 0) || ' security reset/OTP failures in prior hour), then AED '
        || TO_VARCHAR(CAST(ROUND(d.DEBIT_AED, 0) AS NUMBER(38, 0))) || ' sent within 2 hours' AS TRIGGER_SUMMARY
FROM benef b
JOIN drains d       ON d.EVENT_ID = b.EVENT_ID
LEFT JOIN resets r  ON r.EVENT_ID = b.EVENT_ID
WHERE (b.IP_COUNTRY <> 'AE' OR COALESCE(r.RESET_COUNT, 0) > 0)
  AND d.DEBIT_AED >= 20000
QUALIFY ROW_NUMBER() OVER (PARTITION BY b.CUSTOMER_ID ORDER BY d.DEBIT_AED DESC) = 1;

-- -------------------------------------------------------------------------------------
-- Consolidated alerts (consumer-facing freshness SLA)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE DYNAMIC TABLE RAQIB.DETECT.ALERTS
  TARGET_LAG = '5 minutes'
  WAREHOUSE = RAQIB_WH
  COMMENT = 'All rule hits, one row per customer x rule (x counterparty for TM-06)'
AS
WITH hits AS (
    SELECT * FROM RAQIB.DETECT.TM01_STRUCTURING
    UNION ALL SELECT * FROM RAQIB.DETECT.TM02_PASS_THROUGH
    UNION ALL SELECT * FROM RAQIB.DETECT.TM03_FAN_IN
    UNION ALL SELECT * FROM RAQIB.DETECT.TM04_HIGH_RISK_GEO
    UNION ALL SELECT * FROM RAQIB.DETECT.TM05_DORMANT_REACTIVATION
    UNION ALL SELECT * FROM RAQIB.DETECT.TM06_WATCHLIST
    UNION ALL SELECT * FROM RAQIB.DETECT.TM07_PROFILE_DEVIATION
    UNION ALL SELECT * FROM RAQIB.DETECT.FR01_ACCOUNT_TAKEOVER
)
SELECT
    'AL-' || UPPER(LEFT(MD5(h.RULE_ID || '|' || h.CUSTOMER_ID || '|' || COALESCE(h.FOCUS_COUNTERPARTY_ID, '')), 10)) AS ALERT_ID,
    h.RULE_ID,
    rc.RULE_NAME,
    rc.TYPOLOGY,
    rc.SEVERITY,
    rc.BASE_SCORE,
    h.CUSTOMER_ID,
    h.ACCOUNT_ID,
    h.WINDOW_START,
    h.WINDOW_END,
    TO_DATE(h.WINDOW_END)   AS ALERT_DATE,
    h.AMOUNT_AED,
    h.TXN_COUNT,
    h.FOCUS_COUNTERPARTY_ID,
    h.METRICS,
    h.TRIGGER_SUMMARY,
    rc.POLICY_REFERENCE
FROM hits h
JOIN RAQIB.DETECT.RULE_CATALOG rc ON rc.RULE_ID = h.RULE_ID;

-- Transactions that evidence each alert (rule-specific filter over the alert window)
CREATE OR REPLACE VIEW RAQIB.DETECT.ALERT_EVIDENCE
  COMMENT = 'Evidence transactions per alert, used by the copilot and case files'
AS
SELECT
    a.ALERT_ID, a.RULE_ID, t.TXN_ID, t.CUSTOMER_ID, t.ACCOUNT_ID, t.TXN_TS, t.DIRECTION, t.CHANNEL,
    t.AMOUNT, t.CURRENCY, t.AMOUNT_AED, t.COUNTERPARTY_ID, t.COUNTERPARTY_NAME, t.COUNTERPARTY_COUNTRY,
    t.COUNTERPARTY_COUNTRY_RISK, t.BRANCH_ID, t.DESCRIPTION
FROM RAQIB.DETECT.ALERTS a
JOIN RAQIB.CORE.TXN_ENRICHED t
  ON t.CUSTOMER_ID = a.CUSTOMER_ID
 AND t.TXN_TS >= a.WINDOW_START
 AND t.TXN_TS <= DATEADD('day', IFF(a.RULE_ID IN ('TM-01', 'TM-03'), 3, 0), a.WINDOW_END)
 AND (
       (a.RULE_ID = 'TM-01' AND (t.CHANNEL = 'CASH_DEPOSIT' AND t.AMOUNT_AED >= 45000 OR t.CHANNEL = 'WIRE_OUT'))
    OR (a.RULE_ID = 'TM-02' AND t.AMOUNT_AED >= 10000 AND t.CHANNEL IN ('WIRE_IN', 'WIRE_OUT', 'INTERNAL_TRANSFER', 'CASH_DEPOSIT'))
    OR (a.RULE_ID = 'TM-03' AND t.CHANNEL IN ('INTERNAL_TRANSFER', 'WIRE_IN', 'WIRE_OUT'))
    OR (a.RULE_ID = 'TM-04' AND t.COUNTERPARTY_COUNTRY_RISK IN ('HIGH', 'PROHIBITED') AND t.CHANNEL IN ('WIRE_OUT', 'WIRE_IN'))
    OR (a.RULE_ID = 'TM-05' AND t.ACCOUNT_ID = a.ACCOUNT_ID)
    OR (a.RULE_ID = 'TM-06' AND t.COUNTERPARTY_ID = a.FOCUS_COUNTERPARTY_ID)
    OR (a.RULE_ID = 'TM-07' AND t.DIRECTION = 'CREDIT' AND (t.COUNTERPARTY_ID IS NOT NULL OR t.CHANNEL = 'CASH_DEPOSIT'))
    OR (a.RULE_ID = 'FR-01' AND t.DIRECTION = 'DEBIT' AND t.CHANNEL IN ('INTERNAL_TRANSFER', 'WIRE_OUT'))
 );

-- -------------------------------------------------------------------------------------
-- Explainable customer risk score (0-100). Every point is attributable to a column.
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE DYNAMIC TABLE RAQIB.DETECT.CUSTOMER_RISK
  TARGET_LAG = '5 minutes'
  WAREHOUSE = RAQIB_WH
  COMMENT = 'Explainable customer risk score with per-component breakdown'
AS
WITH rule_hits AS (
    SELECT CUSTOMER_ID,
           COUNT(DISTINCT RULE_ID)                      AS RULES_HIT,
           LISTAGG(DISTINCT RULE_ID, ', ')              AS RULE_IDS,
           SUM(BASE_SCORE)                              AS RULE_POINTS_RAW,
           COUNT(*)                                     AS ALERT_COUNT,
           SUM(AMOUNT_AED)                              AS ALERTED_AMOUNT_AED,
           MAX(WINDOW_END)                              AS LAST_ALERT_TS
    FROM RAQIB.DETECT.ALERTS
    GROUP BY CUSTOMER_ID
),
scored AS (
    SELECT
        p.CUSTOMER_ID,
        p.FULL_NAME,
        p.CUSTOMER_TYPE,
        p.SEGMENT,
        p.NATIONALITY,
        p.OCCUPATION,
        p.INDUSTRY,
        p.KYC_RISK_RATING,
        p.PEP_FLAG,
        p.KYC_REVIEW_OVERDUE,
        COALESCE(r.RULES_HIT, 0)                                            AS RULES_HIT,
        r.RULE_IDS,
        COALESCE(r.ALERT_COUNT, 0)                                          AS ALERT_COUNT,
        COALESCE(r.ALERTED_AMOUNT_AED, 0)                                   AS ALERTED_AMOUNT_AED,
        r.LAST_ALERT_TS,
        LEAST(COALESCE(r.RULE_POINTS_RAW, 0), 70)                           AS PTS_RULES,
        IFF(COALESCE(r.RULES_HIT, 0) >= 3, 5, 0)                            AS PTS_MULTI_TYPOLOGY,
        IFF(p.KYC_RISK_RATING = 'HIGH', 12, IFF(p.KYC_RISK_RATING = 'MEDIUM', 4, 0)) AS PTS_KYC,
        IFF(p.PEP_FLAG, 10, 0)                                              AS PTS_PEP,
        IFF(p.NATIONALITY_RISK_TIER IN ('HIGH', 'PROHIBITED'), 5, 0)        AS PTS_GEOGRAPHY,
        IFF(p.KYC_REVIEW_OVERDUE, 5, 0)                                     AS PTS_KYC_OVERDUE,
        IFF(COALESCE(r.ALERTED_AMOUNT_AED, 0) >= 1000000, 8,
            IFF(COALESCE(r.ALERTED_AMOUNT_AED, 0) >= 250000, 4, 0))         AS PTS_VALUE
    FROM RAQIB.CORE.CUSTOMER_PROFILE p
    LEFT JOIN rule_hits r ON r.CUSTOMER_ID = p.CUSTOMER_ID
)
SELECT
    s.*,
    LEAST(PTS_RULES + PTS_MULTI_TYPOLOGY + PTS_KYC + PTS_PEP + PTS_GEOGRAPHY + PTS_KYC_OVERDUE + PTS_VALUE, 100) AS RISK_SCORE,
    CASE
        WHEN LEAST(PTS_RULES + PTS_MULTI_TYPOLOGY + PTS_KYC + PTS_PEP + PTS_GEOGRAPHY + PTS_KYC_OVERDUE + PTS_VALUE, 100) >= 70 THEN 'CRITICAL'
        WHEN LEAST(PTS_RULES + PTS_MULTI_TYPOLOGY + PTS_KYC + PTS_PEP + PTS_GEOGRAPHY + PTS_KYC_OVERDUE + PTS_VALUE, 100) >= 45 THEN 'HIGH'
        WHEN LEAST(PTS_RULES + PTS_MULTI_TYPOLOGY + PTS_KYC + PTS_PEP + PTS_GEOGRAPHY + PTS_KYC_OVERDUE + PTS_VALUE, 100) >= 20 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS RISK_BAND
FROM scored s;
