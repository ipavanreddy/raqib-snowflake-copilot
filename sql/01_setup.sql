-- =====================================================================================
-- Raqib | 01 SETUP: roles, warehouse, database, schemas, stages, file formats
-- Run as ACCOUNTADMIN once. Everything after this runs as RAQIB_ADMIN.
-- =====================================================================================
USE ROLE ACCOUNTADMIN;

-- Cortex models may live in another region on trial accounts.
ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';

-- ---------------------------------------------------------------------------------
-- Roles (segregation of duties)
--   RAQIB_ADMIN   : platform owner (pipelines, agent, app)
--   RAQIB_MLRO    : Money Laundering Reporting Officer - sees unmasked PII, approves/files STRs
--   RAQIB_ANALYST : investigator - masked PII, can triage alerts and draft cases, cannot file
-- ---------------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS RAQIB_ADMIN   COMMENT = 'Raqib platform owner';
CREATE ROLE IF NOT EXISTS RAQIB_MLRO    COMMENT = 'Raqib MLRO - approves and files STRs';
CREATE ROLE IF NOT EXISTS RAQIB_ANALYST COMMENT = 'Raqib financial-crime analyst';
GRANT ROLE RAQIB_ANALYST TO ROLE RAQIB_MLRO;
GRANT ROLE RAQIB_MLRO    TO ROLE RAQIB_ADMIN;
GRANT ROLE RAQIB_ADMIN   TO ROLE SYSADMIN;

SET me = CURRENT_USER();
GRANT ROLE RAQIB_ADMIN   TO USER IDENTIFIER($me);
GRANT ROLE RAQIB_MLRO    TO USER IDENTIFIER($me);
GRANT ROLE RAQIB_ANALYST TO USER IDENTIFIER($me);

CREATE WAREHOUSE IF NOT EXISTS RAQIB_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Raqib compute (XS, 60s auto-suspend to protect trial credits)';
GRANT USAGE, OPERATE ON WAREHOUSE RAQIB_WH TO ROLE RAQIB_ADMIN;
GRANT USAGE ON WAREHOUSE RAQIB_WH TO ROLE RAQIB_ANALYST;

CREATE DATABASE IF NOT EXISTS RAQIB COMMENT = 'Raqib - Risk, Fraud & Regulatory Intelligence Copilot';
GRANT OWNERSHIP ON DATABASE RAQIB TO ROLE RAQIB_ADMIN COPY CURRENT GRANTS;

GRANT EXECUTE TASK, EXECUTE MANAGED TASK ON ACCOUNT TO ROLE RAQIB_ADMIN;
GRANT CREATE INTEGRATION ON ACCOUNT TO ROLE RAQIB_ADMIN;

-- Cortex access for all Raqib personas
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE RAQIB_ANALYST;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER TO ROLE RAQIB_ANALYST;

-- ---------------------------------------------------------------------------------
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE SCHEMA IF NOT EXISTS RAQIB.RAW    COMMENT = 'Landing tables (bulk + live feed)';
CREATE SCHEMA IF NOT EXISTS RAQIB.CORE   COMMENT = 'Conformed, enriched entities (dynamic tables)';
CREATE SCHEMA IF NOT EXISTS RAQIB.DETECT COMMENT = 'Detection rules, alerts and customer risk';
CREATE SCHEMA IF NOT EXISTS RAQIB.RISK   COMMENT = 'Liquidity (LCR) and credit (IFRS 9) reporting';
CREATE SCHEMA IF NOT EXISTS RAQIB.DOCS   COMMENT = 'Policy & regulatory documents, chunks, Cortex Search';
CREATE SCHEMA IF NOT EXISTS RAQIB.OPS    COMMENT = 'Case management, reports, audit, notifications, tools';
CREATE SCHEMA IF NOT EXISTS RAQIB.AI     COMMENT = 'Semantic views and Cortex Agent';
CREATE SCHEMA IF NOT EXISTS RAQIB.APP    COMMENT = 'Streamlit application';

CREATE OR REPLACE FILE FORMAT RAQIB.RAW.CSV_FF
  TYPE = CSV
  SKIP_HEADER = 1
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  NULL_IF = ('')
  EMPTY_FIELD_AS_NULL = TRUE
  TIMESTAMP_FORMAT = 'YYYY-MM-DD HH24:MI:SS';

CREATE STAGE IF NOT EXISTS RAQIB.RAW.LANDING
  FILE_FORMAT = RAQIB.RAW.CSV_FF
  COMMENT = 'Synthetic CSV drops from data_gen/generate.py';

-- Server-side encrypted + directory table: required for AI_PARSE_DOCUMENT
CREATE STAGE IF NOT EXISTS RAQIB.DOCS.POLICY_STAGE
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'Policy and regulatory PDFs';

CREATE STAGE IF NOT EXISTS RAQIB.APP.STREAMLIT_STAGE
  DIRECTORY = (ENABLE = TRUE)
  ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')
  COMMENT = 'Streamlit source';

-- Read access for personas (object-level grants are completed in 08_governance.sql)
GRANT USAGE ON DATABASE RAQIB TO ROLE RAQIB_ANALYST;
GRANT USAGE ON ALL SCHEMAS IN DATABASE RAQIB TO ROLE RAQIB_ANALYST;
