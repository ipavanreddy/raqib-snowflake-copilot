-- =====================================================================================
-- Raqib | 05 RISK & REGULATORY REPORTING layer
-- Basel III Liquidity Coverage Ratio and IFRS 9 expected credit loss, computed from the
-- daily treasury and loan-book inputs. Parameters mirror policy_docs/05 and /06.
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

-- -------------------------------------------------------------------------------------
-- LCR = Stock of HQLA / Total net cash outflows over the next 30 calendar days
--   HQLA haircuts: L1 0%, L2A 15%, L2B 50%
--   Caps: L2B <= 15% of total HQLA; L2 (A+B) <= 40% of total HQLA
--   Run-off rates: retail stable 5%, retail less-stable 10%, operational wholesale 25%,
--                  non-operational wholesale (non-financial corporates) 40%,
--                  financial-institution funding 100%, committed facilities 10%
--   Inflows capped at 75% of gross outflows
-- Regulatory minimum 100%; internal early-warning trigger 110% (Liquidity Policy s.4)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.RISK.LCR_DAILY
  COMMENT = 'Daily Basel III LCR with HQLA caps and run-off rates (AED millions)'
AS
WITH base AS (
    SELECT
        AS_OF_DATE,
        HQLA_LEVEL1_AED_M                         AS L1,
        HQLA_LEVEL2A_AED_M * 0.85                 AS L2A_ADJ,
        HQLA_LEVEL2B_AED_M * 0.50                 AS L2B_ADJ,
        RETAIL_STABLE_DEPOSITS_AED_M * 0.05
          + RETAIL_LESS_STABLE_DEPOSITS_AED_M * 0.10                       AS OUT_RETAIL,
        WHOLESALE_OPERATIONAL_AED_M * 0.25
          + WHOLESALE_NONOPERATIONAL_AED_M * 0.40                          AS OUT_WHOLESALE,
        FINANCIAL_INSTITUTION_FUNDING_AED_M * 1.00                          AS OUT_FI,
        COMMITTED_FACILITIES_AED_M * 0.10                                   AS OUT_FACILITIES,
        CONTRACTUAL_INFLOWS_30D_AED_M                                       AS INFLOWS
    FROM RAQIB.RAW.LIQUIDITY_DAILY
),
capped AS (
    SELECT
        b.*,
        -- L2B cap: <= 15/85 of (L1 + L2A) and <= 15/60 of L1 ; total L2 cap: <= 2/3 of L1
        LEAST(L2B_ADJ, 15 / 85 * (L1 + L2A_ADJ), 15 / 60 * L1)              AS L2B_CAPPED,
        OUT_RETAIL + OUT_WHOLESALE + OUT_FI + OUT_FACILITIES                AS GROSS_OUTFLOWS
    FROM base b
),
lcr AS (
    SELECT
        c.*,
        L1 + LEAST(L2A_ADJ + L2B_CAPPED, 2 / 3 * L1)                        AS HQLA_TOTAL,
        LEAST(INFLOWS, 0.75 * GROSS_OUTFLOWS)                               AS INFLOWS_CAPPED
    FROM capped c
)
SELECT
    AS_OF_DATE,
    ROUND(L1, 1)                                         AS HQLA_LEVEL1_AED_M,
    ROUND(L2A_ADJ, 1)                                    AS HQLA_LEVEL2A_ADJ_AED_M,
    ROUND(L2B_CAPPED, 1)                                 AS HQLA_LEVEL2B_ADJ_AED_M,
    ROUND(HQLA_TOTAL, 1)                                 AS HQLA_TOTAL_AED_M,
    ROUND(OUT_RETAIL, 1)                                 AS OUTFLOW_RETAIL_AED_M,
    ROUND(OUT_WHOLESALE, 1)                              AS OUTFLOW_WHOLESALE_AED_M,
    ROUND(OUT_FI, 1)                                     AS OUTFLOW_FI_AED_M,
    ROUND(OUT_FACILITIES, 1)                             AS OUTFLOW_FACILITIES_AED_M,
    ROUND(GROSS_OUTFLOWS, 1)                             AS GROSS_OUTFLOWS_AED_M,
    ROUND(INFLOWS_CAPPED, 1)                             AS INFLOWS_CAPPED_AED_M,
    ROUND(GROSS_OUTFLOWS - INFLOWS_CAPPED, 1)            AS NET_OUTFLOWS_AED_M,
    ROUND(100 * HQLA_TOTAL / (GROSS_OUTFLOWS - INFLOWS_CAPPED), 1) AS LCR_PCT,
    CASE
        WHEN 100 * HQLA_TOTAL / (GROSS_OUTFLOWS - INFLOWS_CAPPED) < 100 THEN 'BREACH'
        WHEN 100 * HQLA_TOTAL / (GROSS_OUTFLOWS - INFLOWS_CAPPED) < 110 THEN 'EARLY_WARNING'
        ELSE 'COMPLIANT'
    END                                                  AS LCR_STATUS
FROM lcr;

-- -------------------------------------------------------------------------------------
-- IFRS 9 expected credit loss
--   Stage 1: 12-month ECL = PD_12M x LGD x EAD
--   Stage 2: lifetime ECL ~ (1 - (1 - PD_12M)^remaining_years) x LGD x EAD
--   Stage 3: credit-impaired, PD = 1 -> ECL = LGD x EAD
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW RAQIB.RISK.LOAN_ECL
  COMMENT = 'Loan-level IFRS 9 staging and expected credit loss'
AS
SELECT
    l.LOAN_ID,
    l.CUSTOMER_ID,
    c.FULL_NAME,
    c.CUSTOMER_TYPE,
    l.PRODUCT,
    l.SECTOR,
    l.OUTSTANDING_AED                                                     AS EAD_AED,
    l.DAYS_PAST_DUE,
    CASE
        WHEN l.DAYS_PAST_DUE = 0 THEN 'CURRENT'
        WHEN l.DAYS_PAST_DUE <= 30 THEN '1-30'
        WHEN l.DAYS_PAST_DUE <= 60 THEN '31-60'
        WHEN l.DAYS_PAST_DUE <= 90 THEN '61-90'
        ELSE '90+'
    END                                                                   AS DPD_BUCKET,
    l.IFRS9_STAGE,
    l.PD_12M,
    l.LGD,
    l.COLLATERAL_VALUE_AED,
    GREATEST(DATEDIFF('day', l.AS_OF_DATE, l.MATURITY_DATE) / 365.0, 0.25) AS REMAINING_YEARS,
    ROUND(CASE l.IFRS9_STAGE
        WHEN 1 THEN l.PD_12M * l.LGD * l.OUTSTANDING_AED
        WHEN 2 THEN (1 - POWER(1 - l.PD_12M, GREATEST(DATEDIFF('day', l.AS_OF_DATE, l.MATURITY_DATE) / 365.0, 1)))
                    * l.LGD * l.OUTSTANDING_AED
        ELSE l.LGD * l.OUTSTANDING_AED
    END, 2)                                                               AS ECL_AED,
    l.IFRS9_STAGE = 3                                                     AS IS_NPL,
    l.AS_OF_DATE
FROM RAQIB.RAW.LOANS l
JOIN RAQIB.RAW.CUSTOMERS c ON c.CUSTOMER_ID = l.CUSTOMER_ID;

CREATE OR REPLACE VIEW RAQIB.RISK.CREDIT_PORTFOLIO_SUMMARY
  COMMENT = 'Portfolio KPIs by sector and product: exposure, NPL ratio, coverage'
AS
SELECT
    SECTOR,
    PRODUCT,
    COUNT(*)                                                     AS LOAN_COUNT,
    ROUND(SUM(EAD_AED), 0)                                       AS EXPOSURE_AED,
    ROUND(SUM(IFF(IS_NPL, EAD_AED, 0)), 0)                       AS NPL_EXPOSURE_AED,
    ROUND(100 * SUM(IFF(IS_NPL, EAD_AED, 0)) / NULLIF(SUM(EAD_AED), 0), 2) AS NPL_RATIO_PCT,
    ROUND(SUM(IFF(IFRS9_STAGE = 2, EAD_AED, 0)), 0)              AS STAGE2_EXPOSURE_AED,
    ROUND(SUM(ECL_AED), 0)                                       AS ECL_AED,
    ROUND(100 * SUM(ECL_AED) / NULLIF(SUM(EAD_AED), 0), 2)       AS COVERAGE_PCT
FROM RAQIB.RISK.LOAN_ECL
GROUP BY SECTOR, PRODUCT;

-- Credit exposure of customers who are also under AML investigation (cross-risk view)
CREATE OR REPLACE VIEW RAQIB.RISK.AML_CREDIT_OVERLAP
  COMMENT = 'Customers with both AML risk and outstanding credit exposure'
AS
SELECT
    r.CUSTOMER_ID, r.FULL_NAME, r.RISK_SCORE, r.RISK_BAND, r.RULE_IDS,
    COUNT(e.LOAN_ID)               AS LOANS,
    ROUND(SUM(e.EAD_AED), 0)       AS EXPOSURE_AED,
    MAX(e.IFRS9_STAGE)             AS WORST_STAGE,
    ROUND(SUM(e.ECL_AED), 0)       AS ECL_AED
FROM RAQIB.DETECT.CUSTOMER_RISK r
JOIN RAQIB.RISK.LOAN_ECL e ON e.CUSTOMER_ID = r.CUSTOMER_ID
WHERE r.RISK_BAND IN ('HIGH', 'CRITICAL')
GROUP BY r.CUSTOMER_ID, r.FULL_NAME, r.RISK_SCORE, r.RISK_BAND, r.RULE_IDS;
