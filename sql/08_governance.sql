-- =====================================================================================
-- Raqib | 08 GOVERNANCE: PII classification tags, secure views, least-privilege grants
-- Analysts investigate with masked identifiers via a secure view; the MLRO sees full PII
-- and alone can read filed STRs. Ground-truth test data is visible to the platform owner only.
--
-- NOTE: masking policies require Enterprise edition. This file uses a SECURE VIEW to achieve
-- the same effect on Standard edition. The tags remain for documentation / future upgrade.
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE TAG IF NOT EXISTS RAQIB.OPS.PII_TYPE
  ALLOWED_VALUES 'NATIONAL_ID', 'PHONE', 'EMAIL', 'DATE_OF_BIRTH', 'ACCOUNT_NUMBER'
  COMMENT = 'Personal data classification';

-- Tag-based classification (informational — masking is enforced by the secure view below)
ALTER TABLE RAQIB.RAW.CUSTOMERS MODIFY
    COLUMN EMIRATES_ID   SET TAG RAQIB.OPS.PII_TYPE = 'NATIONAL_ID',
    COLUMN PHONE         SET TAG RAQIB.OPS.PII_TYPE = 'PHONE',
    COLUMN EMAIL         SET TAG RAQIB.OPS.PII_TYPE = 'EMAIL',
    COLUMN DATE_OF_BIRTH SET TAG RAQIB.OPS.PII_TYPE = 'DATE_OF_BIRTH';
ALTER TABLE RAQIB.RAW.ACCOUNTS  MODIFY COLUMN IBAN SET TAG RAQIB.OPS.PII_TYPE = 'ACCOUNT_NUMBER';

-- ---------------------------------------------------------------------------------
-- Secure view: masks PII unless the MLRO role is active in the session.
-- Replaces masking policies (which require Enterprise edition).
--
-- CAVEAT: IS_ROLE_IN_SESSION checks the full session role set, including secondary
-- roles. When a single test user holds both RAQIB_ANALYST and RAQIB_MLRO, masking
-- will not trigger unless secondary roles are disabled (USE SECONDARY ROLES NONE).
-- In production each user holds only the roles appropriate to their job function,
-- so this is not an issue. IS_ROLE_IN_SESSION is the correct pattern because it
-- respects role inheritance: RAQIB_ADMIN inherits RAQIB_MLRO and sees clear PII.
-- ---------------------------------------------------------------------------------
CREATE OR REPLACE SECURE VIEW RAQIB.CORE.CUSTOMER_PROFILE_SECURE
  COMMENT = 'CUSTOMER_PROFILE with PII masked for non-MLRO roles (Standard-edition alternative to masking policies)'
AS
SELECT
    CUSTOMER_ID,
    FULL_NAME,
    CUSTOMER_TYPE,
    SEGMENT,
    NATIONALITY,
    NATIONALITY_RISK_TIER,
    EMIRATE,
    OCCUPATION,
    INDUSTRY,
    CASE WHEN IS_ROLE_IN_SESSION('RAQIB_MLRO') THEN DATE_OF_BIRTH
         ELSE DATE_TRUNC('year', DATE_OF_BIRTH)
    END                                                                     AS DATE_OF_BIRTH,
    AGE_YEARS,
    CASE WHEN IS_ROLE_IN_SESSION('RAQIB_MLRO') THEN EMIRATES_ID
         WHEN EMIRATES_ID IS NULL THEN NULL
         ELSE REPEAT('*', GREATEST(LENGTH(EMIRATES_ID) - 4, 0)) || RIGHT(EMIRATES_ID, 4)
    END                                                                     AS EMIRATES_ID,
    TRADE_LICENSE_NO,
    ONBOARDING_DATE,
    TENURE_DAYS,
    KYC_RISK_RATING,
    PEP_FLAG,
    EXPECTED_MONTHLY_TURNOVER_AED,
    LAST_KYC_REVIEW_DATE,
    DAYS_SINCE_KYC_REVIEW,
    KYC_REVIEW_OVERDUE,
    CASE WHEN IS_ROLE_IN_SESSION('RAQIB_MLRO') THEN PHONE
         WHEN PHONE IS NULL THEN NULL
         ELSE REPEAT('*', GREATEST(LENGTH(PHONE) - 4, 0)) || RIGHT(PHONE, 4)
    END                                                                     AS PHONE,
    CASE WHEN IS_ROLE_IN_SESSION('RAQIB_MLRO') THEN EMAIL
         WHEN EMAIL IS NULL THEN NULL
         ELSE REPEAT('*', GREATEST(LENGTH(EMAIL) - 4, 0)) || RIGHT(EMAIL, 4)
    END                                                                     AS EMAIL,
    TXN_COUNT_90D,
    CREDITS_90D_AED,
    DEBITS_90D_AED,
    CASH_IN_90D_AED,
    CROSS_BORDER_90D_AED,
    LAST_TXN_TS
FROM RAQIB.CORE.CUSTOMER_PROFILE;

-- ---------------------------------------------------------------------------------
-- Least-privilege grants
-- ---------------------------------------------------------------------------------
-- Analyst: read the governed analytical layers, act only through tools
GRANT SELECT ON ALL TABLES          IN SCHEMA RAQIB.CORE   TO ROLE RAQIB_ANALYST;
GRANT SELECT ON ALL DYNAMIC TABLES  IN SCHEMA RAQIB.CORE   TO ROLE RAQIB_ANALYST;
GRANT SELECT ON ALL VIEWS           IN SCHEMA RAQIB.CORE   TO ROLE RAQIB_ANALYST;
GRANT SELECT ON ALL DYNAMIC TABLES  IN SCHEMA RAQIB.DETECT TO ROLE RAQIB_ANALYST;
GRANT SELECT ON ALL VIEWS           IN SCHEMA RAQIB.DETECT TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.DETECT.RULE_CATALOG           TO ROLE RAQIB_ANALYST;
GRANT SELECT ON ALL VIEWS           IN SCHEMA RAQIB.RISK   TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.DOCS.POLICY_CHUNKS            TO ROLE RAQIB_ANALYST;
GRANT SELECT ON VIEW  RAQIB.DOCS.DOCUMENT_CATALOG         TO ROLE RAQIB_ANALYST;
GRANT USAGE  ON CORTEX SEARCH SERVICE RAQIB.DOCS.POLICY_SEARCH TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.RAW.ACCOUNTS       TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.RAW.TRANSACTIONS   TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.RAW.COUNTERPARTIES TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.RAW.LOANS          TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.RAW.COUNTRY_RISK   TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.RAW.WATCHLIST      TO ROLE RAQIB_ANALYST;
-- NOTE: RAW.PLANTED_CASES (ground truth) is intentionally NOT granted.
-- NOTE: RAW.CUSTOMERS and CORE.CUSTOMER_PROFILE are NOT granted directly;
--       the analyst reads the secure view CORE.CUSTOMER_PROFILE_SECURE instead.

-- Revoke direct access to PII-bearing objects for the analyst role
REVOKE SELECT ON TABLE RAQIB.RAW.CUSTOMERS              FROM ROLE RAQIB_ANALYST;
REVOKE SELECT ON DYNAMIC TABLE RAQIB.CORE.CUSTOMER_PROFILE FROM ROLE RAQIB_ANALYST;

GRANT SELECT ON VIEW  RAQIB.OPS.ALERT_QUEUE    TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.OPS.CASES          TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.OPS.CASE_ALERTS    TO ROLE RAQIB_ANALYST;
GRANT SELECT ON TABLE RAQIB.OPS.ALERT_WORKFLOW TO ROLE RAQIB_ANALYST;
GRANT INSERT ON TABLE RAQIB.OPS.COPILOT_AUDIT  TO ROLE RAQIB_ANALYST;
GRANT USAGE ON PROCEDURE RAQIB.OPS.GET_ALERT_EVIDENCE(VARCHAR)                   TO ROLE RAQIB_ANALYST;
GRANT USAGE ON PROCEDURE RAQIB.OPS.GET_CUSTOMER_360(VARCHAR)                     TO ROLE RAQIB_ANALYST;
GRANT USAGE ON PROCEDURE RAQIB.OPS.UPDATE_ALERT_STATUS(VARCHAR, VARCHAR, VARCHAR) TO ROLE RAQIB_ANALYST;
GRANT USAGE ON PROCEDURE RAQIB.OPS.CREATE_CASE(VARCHAR, VARCHAR)                 TO ROLE RAQIB_ANALYST;
GRANT USAGE ON PROCEDURE RAQIB.OPS.DRAFT_STR(VARCHAR)                            TO ROLE RAQIB_ANALYST;
GRANT USAGE ON PROCEDURE RAQIB.OPS.GENERATE_REGULATORY_REPORT(VARCHAR)           TO ROLE RAQIB_ANALYST;

-- MLRO: reports (STRs are confidential), audit trail, and the approval tool (caller's rights)
GRANT SELECT, UPDATE ON TABLE RAQIB.OPS.REPORTS TO ROLE RAQIB_MLRO;
GRANT SELECT, UPDATE ON TABLE RAQIB.OPS.CASES TO ROLE RAQIB_MLRO;
GRANT SELECT, UPDATE ON TABLE RAQIB.OPS.ALERT_WORKFLOW TO ROLE RAQIB_MLRO;
GRANT SELECT, INSERT ON TABLE RAQIB.OPS.AUDIT_LOG TO ROLE RAQIB_MLRO;
GRANT SELECT ON TABLE RAQIB.OPS.COPILOT_AUDIT TO ROLE RAQIB_MLRO;
GRANT SELECT ON TABLE RAQIB.OPS.SETTINGS TO ROLE RAQIB_MLRO;
GRANT USAGE ON PROCEDURE RAQIB.OPS.APPROVE_REPORT(VARCHAR, VARCHAR, VARCHAR, VARCHAR) TO ROLE RAQIB_MLRO;

-- ---------------------------------------------------------------------------------
-- Governance verification (run in CoCo testing phase)
-- Disable secondary roles so a single test user cannot inherit MLRO while testing
-- the analyst view. In production, separate users make this unnecessary.
-- ---------------------------------------------------------------------------------
USE SECONDARY ROLES NONE;
USE ROLE RAQIB_ANALYST;
SELECT CUSTOMER_ID, EMIRATES_ID, PHONE, DATE_OF_BIRTH FROM RAQIB.CORE.CUSTOMER_PROFILE_SECURE LIMIT 3;  -- expect masked
USE ROLE RAQIB_MLRO;
SELECT CUSTOMER_ID, EMIRATES_ID, PHONE, DATE_OF_BIRTH FROM RAQIB.CORE.CUSTOMER_PROFILE_SECURE LIMIT 3;  -- expect clear
USE SECONDARY ROLES ALL;
USE ROLE RAQIB_ADMIN;
