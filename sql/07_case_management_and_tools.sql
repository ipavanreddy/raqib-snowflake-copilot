-- =====================================================================================
-- Raqib | 07 CASE MANAGEMENT, AUDIT and AGENT TOOLS
-- Tables the copilot acts on, plus Python stored procedures (tools/raqib_tools.py) that the
-- Cortex Agent calls as custom tools. Upload tools/raqib_tools.py to @RAQIB.OPS.CODE_STAGE
-- first (scripts/deploy.sh does this).
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE STAGE IF NOT EXISTS RAQIB.OPS.CODE_STAGE COMMENT = 'Python code for Raqib stored procedures';

CREATE OR REPLACE TABLE RAQIB.OPS.SETTINGS (
    KEY    VARCHAR,
    VALUE  VARCHAR
) COMMENT = 'Runtime settings (LLM models etc.)';
INSERT INTO RAQIB.OPS.SETTINGS VALUES
    ('LLM_MODEL', 'claude-sonnet-4-5'),
    ('FALLBACK_MODEL', 'llama3.3-70b');

CREATE TABLE IF NOT EXISTS RAQIB.OPS.ALERT_WORKFLOW (
    ALERT_ID    VARCHAR,
    STATUS      VARCHAR,
    ASSIGNEE    VARCHAR,
    RATIONALE   VARCHAR,
    CASE_ID     VARCHAR,
    UPDATED_BY  VARCHAR,
    UPDATED_AT  TIMESTAMP_NTZ
) COMMENT = 'Analyst workflow state per alert (alerts themselves are immutable dynamic-table rows)';

CREATE TABLE IF NOT EXISTS RAQIB.OPS.CASES (
    CASE_ID      VARCHAR,
    CUSTOMER_ID  VARCHAR,
    STATUS       VARCHAR,
    PRIORITY     VARCHAR,
    SUMMARY      VARCHAR,
    OPENED_BY    VARCHAR,
    OPENED_AT    TIMESTAMP_NTZ,
    UPDATED_AT   TIMESTAMP_NTZ
) COMMENT = 'Investigation cases (OPEN -> PENDING_MLRO -> STR_FILED | CLOSED)';

CREATE TABLE IF NOT EXISTS RAQIB.OPS.CASE_ALERTS (
    CASE_ID   VARCHAR,
    ALERT_ID  VARCHAR
) COMMENT = 'Alerts linked to each case';

CREATE TABLE IF NOT EXISTS RAQIB.OPS.REPORTS (
    REPORT_ID       VARCHAR,
    REPORT_TYPE     VARCHAR,
    CASE_ID         VARCHAR,
    SUBJECT         VARCHAR,
    STATUS          VARCHAR,
    CONTENT_MD      VARCHAR,
    EVIDENCE        VARIANT,
    CITATIONS       VARIANT,
    VALIDATION      VARIANT,
    CONFIDENCE      FLOAT,
    MODEL           VARCHAR,
    CREATED_BY      VARCHAR,
    CREATED_AT      TIMESTAMP_NTZ,
    APPROVED_BY     VARCHAR,
    APPROVED_AT     TIMESTAMP_NTZ,
    GOAML_REF       VARCHAR,
    REVIEW_COMMENT  VARCHAR
) COMMENT = 'Generated STRs and regulatory reports with evidence, citations and validation results';

CREATE TABLE IF NOT EXISTS RAQIB.OPS.AUDIT_LOG (
    EVENT_ID     VARCHAR,
    EVENT_TS     TIMESTAMP_NTZ,
    ACTOR        VARCHAR,
    ACTOR_ROLE   VARCHAR,
    ACTION       VARCHAR,
    OBJECT_TYPE  VARCHAR,
    OBJECT_ID    VARCHAR,
    DETAILS      VARIANT
) COMMENT = 'Immutable audit trail of every copilot tool action';

CREATE TABLE IF NOT EXISTS RAQIB.OPS.COPILOT_AUDIT (
    INTERACTION_ID  VARCHAR,
    EVENT_TS        TIMESTAMP_NTZ,
    ACTOR           VARCHAR,
    PERSONA         VARCHAR,
    SURFACE         VARCHAR,
    QUESTION        VARCHAR,
    ANSWER          VARCHAR,
    TOOLS_USED      VARIANT,
    SQL_EXECUTED    VARIANT,
    CITATIONS       VARIANT,
    LATENCY_MS      NUMBER,
    FEEDBACK        VARCHAR
) COMMENT = 'Every natural-language question and answer, for model risk and audit review';

CREATE TABLE IF NOT EXISTS RAQIB.OPS.NOTIFICATIONS (
    NOTIFICATION_ID  VARCHAR,
    CREATED_AT       TIMESTAMP_NTZ,
    CHANNEL          VARCHAR,
    SEVERITY         VARCHAR,
    TITLE            VARCHAR,
    BODY             VARCHAR,
    OBJECT_ID        VARCHAR,
    STATUS           VARCHAR,
    SENT_AT          TIMESTAMP_NTZ
) COMMENT = 'Outbox drained by the CoCo Slack/Jira MCP automation';

CREATE OR REPLACE VIEW RAQIB.OPS.ALERT_QUEUE
  COMMENT = 'Analyst work queue: alerts with workflow status and customer risk'
AS
SELECT
    a.ALERT_ID, a.ALERT_DATE, a.RULE_ID, a.RULE_NAME, a.TYPOLOGY, a.SEVERITY, a.CUSTOMER_ID,
    r.FULL_NAME, r.CUSTOMER_TYPE, r.SEGMENT, r.RISK_SCORE, r.RISK_BAND,
    a.AMOUNT_AED, a.TXN_COUNT, a.TRIGGER_SUMMARY, a.POLICY_REFERENCE,
    COALESCE(w.STATUS, 'NEW') AS STATUS, w.ASSIGNEE, w.CASE_ID, w.UPDATED_AT AS STATUS_UPDATED_AT
FROM RAQIB.DETECT.ALERTS a
JOIN RAQIB.DETECT.CUSTOMER_RISK r      ON r.CUSTOMER_ID = a.CUSTOMER_ID
LEFT JOIN RAQIB.OPS.ALERT_WORKFLOW w   ON w.ALERT_ID = a.ALERT_ID;

-- -------------------------------------------------------------------------------------
-- Agent tools (Python stored procedures). p_ prefixed parameters per Cortex Agent guidance.
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE RAQIB.OPS.GET_ALERT_EVIDENCE(P_ALERT_ID VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@RAQIB.OPS.CODE_STAGE/raqib_tools.py') HANDLER = 'raqib_tools.sp_get_alert_evidence'
  COMMENT = 'Alert details, customer KYC profile and evidence transactions'
  EXECUTE AS OWNER;

CREATE OR REPLACE PROCEDURE RAQIB.OPS.GET_CUSTOMER_360(P_CUSTOMER_ID VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@RAQIB.OPS.CODE_STAGE/raqib_tools.py') HANDLER = 'raqib_tools.sp_get_customer_360'
  COMMENT = 'Customer 360: profile, explainable risk score, alerts, accounts, loans, top counterparties'
  EXECUTE AS OWNER;

CREATE OR REPLACE PROCEDURE RAQIB.OPS.UPDATE_ALERT_STATUS(P_ALERT_ID VARCHAR, P_STATUS VARCHAR, P_RATIONALE VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@RAQIB.OPS.CODE_STAGE/raqib_tools.py') HANDLER = 'raqib_tools.sp_update_alert_status'
  COMMENT = 'Move an alert through the workflow; closure requires a rationale'
  EXECUTE AS OWNER;

CREATE OR REPLACE PROCEDURE RAQIB.OPS.CREATE_CASE(P_CUSTOMER_ID VARCHAR, P_SUMMARY VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@RAQIB.OPS.CODE_STAGE/raqib_tools.py') HANDLER = 'raqib_tools.sp_create_case'
  COMMENT = 'Open an investigation case linking all alerts for a customer, and notify'
  EXECUTE AS OWNER;

CREATE OR REPLACE PROCEDURE RAQIB.OPS.DRAFT_STR(P_CASE_ID VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@RAQIB.OPS.CODE_STAGE/raqib_tools.py') HANDLER = 'raqib_tools.sp_draft_str'
  COMMENT = 'Draft an evidence-backed, cited, validated STR for MLRO review'
  EXECUTE AS OWNER;

CREATE OR REPLACE PROCEDURE RAQIB.OPS.GENERATE_REGULATORY_REPORT(P_REPORT_TYPE VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@RAQIB.OPS.CODE_STAGE/raqib_tools.py') HANDLER = 'raqib_tools.sp_generate_regulatory_report'
  COMMENT = 'Generate an LCR, CREDIT or AML_MI regulatory report with citations'
  EXECUTE AS OWNER;

-- Caller's rights so IS_ROLE_IN_SESSION('RAQIB_MLRO') reflects the real user
CREATE OR REPLACE PROCEDURE RAQIB.OPS.APPROVE_REPORT(P_REPORT_ID VARCHAR, P_DECISION VARCHAR, P_GOAML_REF VARCHAR, P_COMMENT VARCHAR)
  RETURNS VARIANT
  LANGUAGE PYTHON RUNTIME_VERSION = '3.11' PACKAGES = ('snowflake-snowpark-python')
  IMPORTS = ('@RAQIB.OPS.CODE_STAGE/raqib_tools.py') HANDLER = 'raqib_tools.sp_approve_report'
  COMMENT = 'MLRO-only: approve and file, or reject, a report'
  EXECUTE AS CALLER;

-- Smoke tests
SET TOP_CUSTOMER = (SELECT CUSTOMER_ID FROM RAQIB.DETECT.CUSTOMER_RISK ORDER BY RISK_SCORE DESC LIMIT 1);
CALL RAQIB.OPS.GET_CUSTOMER_360($TOP_CUSTOMER);
