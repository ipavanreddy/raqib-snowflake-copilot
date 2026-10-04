-- =====================================================================================
-- Raqib | 02 RAW landing tables + bulk load
-- Column names match data_gen/generate.py CSV headers exactly.
-- Run 01_setup.sql first. Load step expects files PUT to @RAQIB.RAW.LANDING (see scripts/load_data.sh).
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;
USE SCHEMA RAQIB.RAW;

CREATE OR REPLACE TABLE CUSTOMERS (
    CUSTOMER_ID                    VARCHAR PRIMARY KEY,
    FULL_NAME                      VARCHAR,
    CUSTOMER_TYPE                  VARCHAR,   -- INDIVIDUAL | CORPORATE
    SEGMENT                        VARCHAR,   -- RETAIL | PRIORITY | SME | CORPORATE
    NATIONALITY                    VARCHAR,
    RESIDENCE_COUNTRY              VARCHAR,
    EMIRATE                        VARCHAR,
    OCCUPATION                     VARCHAR,
    INDUSTRY                       VARCHAR,
    GENDER                         VARCHAR,
    DATE_OF_BIRTH                  DATE,
    EMIRATES_ID                    VARCHAR,
    TRADE_LICENSE_NO               VARCHAR,
    ONBOARDING_DATE                DATE,
    KYC_RISK_RATING                VARCHAR,   -- LOW | MEDIUM | HIGH
    PEP_FLAG                       BOOLEAN,
    EXPECTED_MONTHLY_TURNOVER_AED  NUMBER(18,2),
    LAST_KYC_REVIEW_DATE           DATE,
    PHONE                          VARCHAR,
    EMAIL                          VARCHAR
) COMMENT = 'KYC master for individual and corporate customers (synthetic)';

CREATE OR REPLACE TABLE ACCOUNTS (
    ACCOUNT_ID                   VARCHAR PRIMARY KEY,
    CUSTOMER_ID                  VARCHAR,
    IBAN                         VARCHAR,
    ACCOUNT_TYPE                 VARCHAR,
    CURRENCY                     VARCHAR,
    OPEN_DATE                    DATE,
    STATUS                       VARCHAR,
    HOME_BRANCH                  VARCHAR,
    LAST_ACTIVITY_BEFORE_WINDOW  DATE
) COMMENT = 'Deposit accounts. LAST_ACTIVITY_BEFORE_WINDOW seeds dormancy detection.';

CREATE OR REPLACE TABLE COUNTERPARTIES (
    COUNTERPARTY_ID      VARCHAR PRIMARY KEY,
    COUNTERPARTY_NAME    VARCHAR,
    COUNTERPARTY_TYPE    VARCHAR,
    COUNTRY_CODE         VARCHAR,
    BANK_NAME            VARCHAR,
    INTERNAL_ACCOUNT_ID  VARCHAR
) COMMENT = 'Payment counterparties. INTERNAL_ACCOUNT_ID set when the counterparty banks with us.';

CREATE OR REPLACE TABLE TRANSACTIONS (
    TXN_ID                VARCHAR PRIMARY KEY,
    ACCOUNT_ID            VARCHAR,
    TXN_TS                TIMESTAMP_NTZ,
    DIRECTION             VARCHAR,   -- CREDIT | DEBIT
    CHANNEL               VARCHAR,
    AMOUNT                NUMBER(18,2),
    CURRENCY              VARCHAR,
    AMOUNT_AED            NUMBER(18,2),
    COUNTERPARTY_ID       VARCHAR,
    COUNTERPARTY_COUNTRY  VARCHAR,
    PURPOSE_CODE          VARCHAR,
    DESCRIPTION           VARCHAR,
    BRANCH_ID             VARCHAR
) CHANGE_TRACKING = TRUE
  COMMENT = 'Posted transactions. Live simulator appends here; dynamic tables pick up changes.';

CREATE OR REPLACE TABLE DIGITAL_EVENTS (
    EVENT_ID     VARCHAR PRIMARY KEY,
    CUSTOMER_ID  VARCHAR,
    EVENT_TS     TIMESTAMP_NTZ,
    EVENT_TYPE   VARCHAR,   -- LOGIN | NEW_DEVICE | PASSWORD_RESET | OTP_FAILED | BENEFICIARY_ADDED
    DEVICE_ID    VARCHAR,
    IP_COUNTRY   VARCHAR
) CHANGE_TRACKING = TRUE
  COMMENT = 'Online / mobile banking security events';

CREATE OR REPLACE TABLE LOANS (
    LOAN_ID               VARCHAR PRIMARY KEY,
    CUSTOMER_ID           VARCHAR,
    PRODUCT               VARCHAR,
    SECTOR                VARCHAR,
    ORIGINATION_DATE      DATE,
    MATURITY_DATE         DATE,
    PRINCIPAL_AED         NUMBER(18,2),
    OUTSTANDING_AED       NUMBER(18,2),
    INTEREST_RATE         NUMBER(8,4),
    DAYS_PAST_DUE         NUMBER,
    IFRS9_STAGE           NUMBER,
    PD_12M                NUMBER(8,4),
    LGD                   NUMBER(8,4),
    COLLATERAL_VALUE_AED  NUMBER(18,2),
    AS_OF_DATE            DATE
) COMMENT = 'Credit exposures with IFRS 9 staging inputs';

CREATE OR REPLACE TABLE LIQUIDITY_DAILY (
    AS_OF_DATE                          DATE PRIMARY KEY,
    HQLA_LEVEL1_AED_M                   NUMBER(18,1),
    HQLA_LEVEL2A_AED_M                  NUMBER(18,1),
    HQLA_LEVEL2B_AED_M                  NUMBER(18,1),
    RETAIL_STABLE_DEPOSITS_AED_M        NUMBER(18,1),
    RETAIL_LESS_STABLE_DEPOSITS_AED_M   NUMBER(18,1),
    WHOLESALE_OPERATIONAL_AED_M         NUMBER(18,1),
    WHOLESALE_NONOPERATIONAL_AED_M      NUMBER(18,1),
    FINANCIAL_INSTITUTION_FUNDING_AED_M NUMBER(18,1),
    COMMITTED_FACILITIES_AED_M          NUMBER(18,1),
    CONTRACTUAL_INFLOWS_30D_AED_M       NUMBER(18,1)
) COMMENT = 'Daily treasury balances feeding the Basel III LCR (AED millions)';

CREATE OR REPLACE TABLE COUNTRY_RISK (
    COUNTRY_CODE  VARCHAR PRIMARY KEY,
    COUNTRY_NAME  VARCHAR,
    FATF_STATUS   VARCHAR,   -- NONE | INCREASED_MONITORING | CALL_FOR_ACTION (illustrative)
    RISK_TIER     VARCHAR    -- LOW | MEDIUM | HIGH | PROHIBITED
) COMMENT = 'Illustrative jurisdiction risk table (not an official list)';

CREATE OR REPLACE TABLE WATCHLIST (
    ENTRY_ID      VARCHAR PRIMARY KEY,
    ENTRY_NAME    VARCHAR,
    LIST_SOURCE   VARCHAR,
    COUNTRY_CODE  VARCHAR,
    PROGRAM       VARCHAR
) COMMENT = 'Synthetic sanctions / PEP / internal blacklist entries (fictional names)';

CREATE OR REPLACE TABLE PLANTED_CASES (
    SCENARIO_ID    VARCHAR,
    TYPOLOGY       VARCHAR,
    CUSTOMER_ID    VARCHAR,
    ACCOUNT_ID     VARCHAR,
    EXPECTED_RULE  VARCHAR,
    NARRATIVE      VARCHAR,
    TXN_COUNT      NUMBER
) COMMENT = 'Ground truth for detection testing. Not exposed to business roles.';

-- ---------------------------------------------------------------------------------
-- Bulk load (files staged by scripts/load_data.sh)
-- ---------------------------------------------------------------------------------
COPY INTO CUSTOMERS       FROM @LANDING/customers.csv       FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO ACCOUNTS        FROM @LANDING/accounts.csv        FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO COUNTERPARTIES  FROM @LANDING/counterparties.csv  FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO TRANSACTIONS    FROM @LANDING/transactions.csv    FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO DIGITAL_EVENTS  FROM @LANDING/digital_events.csv  FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO LOANS           FROM @LANDING/loans.csv           FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO LIQUIDITY_DAILY FROM @LANDING/liquidity_daily.csv FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO COUNTRY_RISK    FROM @LANDING/country_risk.csv    FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO WATCHLIST       FROM @LANDING/watchlist.csv       FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;
COPY INTO PLANTED_CASES   FROM @LANDING/planted_cases.csv   FILE_FORMAT = (FORMAT_NAME = CSV_FF) ON_ERROR = ABORT_STATEMENT;

-- Row-count sanity check (compare with data/generated/manifest.json)
SELECT 'CUSTOMERS' t, COUNT(*) n FROM CUSTOMERS UNION ALL
SELECT 'ACCOUNTS', COUNT(*) FROM ACCOUNTS UNION ALL
SELECT 'COUNTERPARTIES', COUNT(*) FROM COUNTERPARTIES UNION ALL
SELECT 'TRANSACTIONS', COUNT(*) FROM TRANSACTIONS UNION ALL
SELECT 'DIGITAL_EVENTS', COUNT(*) FROM DIGITAL_EVENTS UNION ALL
SELECT 'LOANS', COUNT(*) FROM LOANS UNION ALL
SELECT 'LIQUIDITY_DAILY', COUNT(*) FROM LIQUIDITY_DAILY;
