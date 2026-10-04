-- =====================================================================================
-- Raqib | 03 CORE pipeline (dynamic tables)
-- RAW -> CORE.TXN_ENRICHED -> DETECT rules -> DETECT.ALERTS -> DETECT.CUSTOMER_RISK
-- Intermediate tables use TARGET_LAG = DOWNSTREAM so only the consumer-facing tables
-- set the freshness SLA (see 04_detection.sql).
--
-- Convention used by tests/test_sql_logic.py: every object body starts on a line that is
-- exactly "AS" and ends with ";" so the SELECT can be extracted and run locally in DuckDB.
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE OR REPLACE DYNAMIC TABLE RAQIB.CORE.TXN_ENRICHED
  TARGET_LAG = DOWNSTREAM
  WAREHOUSE = RAQIB_WH
  COMMENT = 'One row per transaction enriched with account, customer, counterparty and jurisdiction risk'
AS
SELECT
    t.TXN_ID,
    t.ACCOUNT_ID,
    a.CUSTOMER_ID,
    t.TXN_TS,
    TO_DATE(t.TXN_TS)                                        AS TXN_DATE,
    t.DIRECTION,
    t.CHANNEL,
    t.AMOUNT,
    t.CURRENCY,
    t.AMOUNT_AED,
    IFF(t.DIRECTION = 'CREDIT', t.AMOUNT_AED, 0)             AS CREDIT_AED,
    IFF(t.DIRECTION = 'DEBIT', t.AMOUNT_AED, 0)              AS DEBIT_AED,
    t.COUNTERPARTY_ID,
    cp.COUNTERPARTY_NAME,
    cp.COUNTERPARTY_TYPE,
    COALESCE(t.COUNTERPARTY_COUNTRY, cp.COUNTRY_CODE)        AS COUNTERPARTY_COUNTRY,
    COALESCE(cr.RISK_TIER, 'UNKNOWN')                        AS COUNTERPARTY_COUNTRY_RISK,
    cr.FATF_STATUS                                           AS COUNTERPARTY_FATF_STATUS,
    cp.INTERNAL_ACCOUNT_ID IS NOT NULL                       AS IS_INTERNAL_COUNTERPARTY,
    t.PURPOSE_CODE,
    t.DESCRIPTION,
    t.BRANCH_ID,
    c.CUSTOMER_TYPE,
    c.SEGMENT,
    c.KYC_RISK_RATING
FROM RAQIB.RAW.TRANSACTIONS t
JOIN RAQIB.RAW.ACCOUNTS a       ON a.ACCOUNT_ID = t.ACCOUNT_ID
JOIN RAQIB.RAW.CUSTOMERS c      ON c.CUSTOMER_ID = a.CUSTOMER_ID
LEFT JOIN RAQIB.RAW.COUNTERPARTIES cp ON cp.COUNTERPARTY_ID = t.COUNTERPARTY_ID
LEFT JOIN RAQIB.RAW.COUNTRY_RISK cr   ON cr.COUNTRY_CODE = COALESCE(t.COUNTERPARTY_COUNTRY, cp.COUNTRY_CODE);

-- Reference "as of" date = latest posted transaction. Used instead of CURRENT_DATE so the
-- synthetic history behaves like today and dynamic tables stay deterministic.
CREATE OR REPLACE VIEW RAQIB.CORE.AS_OF
  COMMENT = 'Business as-of date (latest posted transaction date)'
AS
SELECT MAX(TXN_DATE) AS AS_OF_DATE FROM RAQIB.CORE.TXN_ENRICHED;

CREATE OR REPLACE DYNAMIC TABLE RAQIB.CORE.CUSTOMER_PROFILE
  TARGET_LAG = DOWNSTREAM
  WAREHOUSE = RAQIB_WH
  COMMENT = 'Customer 360 profile: KYC attributes plus 90-day behavioural aggregates'
AS
WITH as_of AS (
    SELECT MAX(TXN_DATE) AS AS_OF_DATE FROM RAQIB.CORE.TXN_ENRICHED
),
beh AS (
    SELECT
        t.CUSTOMER_ID,
        COUNT(*)                                                           AS TXN_COUNT_90D,
        SUM(t.CREDIT_AED)                                                  AS CREDITS_90D_AED,
        SUM(t.DEBIT_AED)                                                   AS DEBITS_90D_AED,
        SUM(IFF(t.CHANNEL = 'CASH_DEPOSIT', t.AMOUNT_AED, 0))              AS CASH_IN_90D_AED,
        SUM(IFF(t.CHANNEL IN ('WIRE_OUT', 'WIRE_IN') AND t.COUNTERPARTY_COUNTRY <> 'AE', t.AMOUNT_AED, 0)) AS CROSS_BORDER_90D_AED,
        MAX(t.TXN_TS)                                                      AS LAST_TXN_TS
    FROM RAQIB.CORE.TXN_ENRICHED t
    CROSS JOIN as_of
    WHERE t.TXN_DATE > DATEADD('day', -90, as_of.AS_OF_DATE)
    GROUP BY t.CUSTOMER_ID
)
SELECT
    c.CUSTOMER_ID,
    c.FULL_NAME,
    c.CUSTOMER_TYPE,
    c.SEGMENT,
    c.NATIONALITY,
    nr.RISK_TIER                                                           AS NATIONALITY_RISK_TIER,
    c.EMIRATE,
    c.OCCUPATION,
    c.INDUSTRY,
    c.DATE_OF_BIRTH,
    DATEDIFF('year', c.DATE_OF_BIRTH, as_of.AS_OF_DATE)                    AS AGE_YEARS,
    c.EMIRATES_ID,
    c.TRADE_LICENSE_NO,
    c.ONBOARDING_DATE,
    DATEDIFF('day', c.ONBOARDING_DATE, as_of.AS_OF_DATE)                   AS TENURE_DAYS,
    c.KYC_RISK_RATING,
    c.PEP_FLAG,
    c.EXPECTED_MONTHLY_TURNOVER_AED,
    c.LAST_KYC_REVIEW_DATE,
    DATEDIFF('day', c.LAST_KYC_REVIEW_DATE, as_of.AS_OF_DATE)              AS DAYS_SINCE_KYC_REVIEW,
    DATEDIFF('day', c.LAST_KYC_REVIEW_DATE, as_of.AS_OF_DATE)
        > IFF(c.KYC_RISK_RATING = 'HIGH', 365, IFF(c.KYC_RISK_RATING = 'MEDIUM', 730, 1095)) AS KYC_REVIEW_OVERDUE,
    c.PHONE,
    c.EMAIL,
    COALESCE(b.TXN_COUNT_90D, 0)                                           AS TXN_COUNT_90D,
    COALESCE(b.CREDITS_90D_AED, 0)                                         AS CREDITS_90D_AED,
    COALESCE(b.DEBITS_90D_AED, 0)                                          AS DEBITS_90D_AED,
    COALESCE(b.CASH_IN_90D_AED, 0)                                         AS CASH_IN_90D_AED,
    COALESCE(b.CROSS_BORDER_90D_AED, 0)                                    AS CROSS_BORDER_90D_AED,
    b.LAST_TXN_TS
FROM RAQIB.RAW.CUSTOMERS c
CROSS JOIN as_of
LEFT JOIN beh b                       ON b.CUSTOMER_ID = c.CUSTOMER_ID
LEFT JOIN RAQIB.RAW.COUNTRY_RISK nr   ON nr.COUNTRY_CODE = c.NATIONALITY;
