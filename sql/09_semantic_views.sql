-- =====================================================================================
-- Raqib | 09 SEMANTIC VIEWS (the ontology the copilot reasons over)
--   AML_SV  : Customer -> Account/Transaction -> Alert -> Case   (financial crime)
--   RISK_SV : Liquidity (Basel III LCR) and Credit (IFRS 9)       (prudential risk)
-- Business names, synonyms, governed metric definitions and verified queries live here so
-- every surface (agent, Snowsight, CoCo, Streamlit) gets the same answer to the same question.
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE OR REPLACE SEMANTIC VIEW RAQIB.AI.AML_SV
  TABLES (
    customers AS RAQIB.DETECT.CUSTOMER_RISK PRIMARY KEY (CUSTOMER_ID)
      WITH SYNONYMS ('clients', 'subjects', 'account holders')
      COMMENT = 'One row per customer with KYC attributes and the explainable Raqib risk score',
    alerts AS RAQIB.OPS.ALERT_QUEUE PRIMARY KEY (ALERT_ID)
      WITH SYNONYMS ('hits', 'red flags', 'monitoring alerts')
      COMMENT = 'Transaction-monitoring and fraud alerts with workflow status',
    transactions AS RAQIB.CORE.TXN_ENRICHED PRIMARY KEY (TXN_ID)
      WITH SYNONYMS ('payments', 'transfers', 'txns')
      COMMENT = 'Posted transactions enriched with counterparty and jurisdiction risk',
    cases AS RAQIB.OPS.CASES PRIMARY KEY (CASE_ID)
      WITH SYNONYMS ('investigations')
      COMMENT = 'Investigation cases opened from alerts'
  )
  RELATIONSHIPS (
    alerts_to_customers AS alerts (CUSTOMER_ID) REFERENCES customers,
    transactions_to_customers AS transactions (CUSTOMER_ID) REFERENCES customers,
    cases_to_customers AS cases (CUSTOMER_ID) REFERENCES customers
  )
  FACTS (
    transactions.amount_aed_fact AS AMOUNT_AED COMMENT = 'Transaction amount in AED',
    alerts.alerted_amount_fact AS AMOUNT_AED COMMENT = 'Amount covered by the alert in AED'
  )
  DIMENSIONS (
    customers.customer_id AS CUSTOMER_ID,
    customers.customer_name AS FULL_NAME WITH SYNONYMS ('name', 'client name'),
    customers.customer_type AS CUSTOMER_TYPE COMMENT = 'INDIVIDUAL or CORPORATE',
    customers.segment AS SEGMENT COMMENT = 'RETAIL, PRIORITY, SME, CORPORATE',
    customers.nationality AS NATIONALITY COMMENT = 'ISO 3166 alpha-2',
    customers.occupation AS OCCUPATION,
    customers.industry AS INDUSTRY,
    customers.kyc_risk_rating AS KYC_RISK_RATING WITH SYNONYMS ('KYC rating', 'CDD risk'),
    customers.is_pep AS PEP_FLAG WITH SYNONYMS ('politically exposed person'),
    customers.kyc_review_overdue AS KYC_REVIEW_OVERDUE,
    customers.risk_score AS RISK_SCORE WITH SYNONYMS ('Raqib score', 'AML risk score') COMMENT = '0-100 explainable score',
    customers.risk_band AS RISK_BAND COMMENT = 'CRITICAL >= 70, HIGH >= 45, MEDIUM >= 20, LOW',
    customers.rules_hit AS RULE_IDS COMMENT = 'Comma-separated rule IDs hit by the customer',
    alerts.alert_id AS ALERT_ID,
    alerts.rule_id AS RULE_ID WITH SYNONYMS ('scenario', 'rule') COMMENT = 'TM-01..TM-07 AML rules, FR-01 fraud',
    alerts.rule_name AS RULE_NAME,
    alerts.typology AS TYPOLOGY WITH SYNONYMS ('pattern'),
    alerts.severity AS SEVERITY,
    alerts.alert_status AS STATUS WITH SYNONYMS ('workflow status') COMMENT = 'NEW, IN_REVIEW, ESCALATED, CLOSED_*, STR_FILED',
    alerts.alert_date AS ALERT_DATE,
    alerts.trigger_summary AS TRIGGER_SUMMARY COMMENT = 'Plain-English explanation of why the alert fired',
    transactions.txn_date AS TXN_DATE WITH SYNONYMS ('transaction date', 'value date'),
    transactions.txn_month AS DATE_TRUNC('month', TXN_DATE),
    transactions.channel AS CHANNEL COMMENT = 'CASH_DEPOSIT, CASH_WITHDRAWAL, ATM, WIRE_IN, WIRE_OUT, INTERNAL_TRANSFER, CARD_POS, SALARY, PAYROLL, CHEQUE',
    transactions.direction AS DIRECTION COMMENT = 'CREDIT or DEBIT',
    transactions.counterparty_name AS COUNTERPARTY_NAME WITH SYNONYMS ('beneficiary', 'remitter'),
    transactions.counterparty_country AS COUNTERPARTY_COUNTRY,
    transactions.counterparty_country_risk AS COUNTERPARTY_COUNTRY_RISK WITH SYNONYMS ('jurisdiction risk') COMMENT = 'LOW, MEDIUM, HIGH, PROHIBITED',
    transactions.branch AS BRANCH_ID,
    cases.case_status AS STATUS COMMENT = 'OPEN, PENDING_MLRO, STR_FILED, CLOSED',
    cases.case_priority AS PRIORITY
  )
  METRICS (
    transactions.total_value_aed AS SUM(transactions.AMOUNT_AED) WITH SYNONYMS ('volume', 'turnover', 'total amount'),
    transactions.transaction_count AS COUNT(transactions.TXN_ID),
    transactions.cash_deposit_value_aed AS SUM(IFF(transactions.CHANNEL = 'CASH_DEPOSIT', transactions.AMOUNT_AED, 0)) WITH SYNONYMS ('cash in'),
    transactions.cross_border_value_aed AS SUM(IFF(transactions.COUNTERPARTY_COUNTRY <> 'AE', transactions.AMOUNT_AED, 0)),
    transactions.high_risk_jurisdiction_value_aed AS SUM(IFF(transactions.COUNTERPARTY_COUNTRY_RISK IN ('HIGH', 'PROHIBITED'), transactions.AMOUNT_AED, 0)),
    alerts.alert_count AS COUNT(alerts.ALERT_ID),
    alerts.open_alert_count AS COUNT_IF(alerts.STATUS IN ('NEW', 'IN_REVIEW', 'ESCALATED')) WITH SYNONYMS ('backlog', 'pending alerts'),
    alerts.alerted_value_aed AS SUM(alerts.AMOUNT_AED),
    customers.customer_count AS COUNT(customers.CUSTOMER_ID),
    customers.high_risk_customer_count AS COUNT_IF(customers.RISK_BAND IN ('HIGH', 'CRITICAL')),
    customers.average_risk_score AS AVG(customers.RISK_SCORE),
    cases.case_count AS COUNT(cases.CASE_ID)
  )
  COMMENT = 'Raqib financial-crime ontology: customers, transactions, alerts and cases (synthetic Gulf Horizon Bank data)'
  AI_SQL_GENERATION 'All amounts are in AED. The business as-of date is the latest TXN_DATE in the data (2026-09-30); interpret "today", "this month", "last 30 days" relative to that date, never CURRENT_DATE. Round money to 2 decimals. When listing customers, include customer_id, customer_name, risk_score and risk_band. Order risk lists by risk_score descending.'
  AI_VERIFIED_QUERIES (
    top_risk_customers AS (
      QUESTION 'Who are the top 10 highest risk customers right now?'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT CUSTOMER_ID, FULL_NAME, RISK_SCORE, RISK_BAND, RULE_IDS, ALERTED_AMOUNT_AED FROM customers ORDER BY RISK_SCORE DESC, ALERTED_AMOUNT_AED DESC LIMIT 10'
    ),
    open_alerts_by_rule AS (
      QUESTION 'How many open alerts do we have by rule and severity?'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT RULE_ID, RULE_NAME, SEVERITY, COUNT(ALERT_ID) AS OPEN_ALERTS, SUM(AMOUNT_AED) AS ALERTED_AED FROM alerts WHERE STATUS IN (''NEW'', ''IN_REVIEW'', ''ESCALATED'') GROUP BY RULE_ID, RULE_NAME, SEVERITY ORDER BY RULE_ID'
    ),
    structuring_last_30d AS (
      QUESTION 'Which customers made multiple cash deposits just under AED 55,000 in the last 30 days?'
      SQL 'SELECT CUSTOMER_ID, COUNT(TXN_ID) AS DEPOSITS, SUM(AMOUNT_AED) AS TOTAL_AED, COUNT(DISTINCT BRANCH_ID) AS BRANCHES FROM transactions WHERE CHANNEL = ''CASH_DEPOSIT'' AND AMOUNT_AED >= 45000 AND AMOUNT_AED < 55000 AND TXN_DATE > DATEADD(''day'', -30, (SELECT MAX(TXN_DATE) FROM transactions)) GROUP BY CUSTOMER_ID HAVING COUNT(TXN_ID) >= 3 ORDER BY TOTAL_AED DESC'
    ),
    high_risk_corridors AS (
      QUESTION 'What is our payment exposure to high-risk and prohibited jurisdictions by country?'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT COUNTERPARTY_COUNTRY, COUNTERPARTY_COUNTRY_RISK, COUNT(TXN_ID) AS PAYMENTS, SUM(AMOUNT_AED) AS TOTAL_AED, COUNT(DISTINCT CUSTOMER_ID) AS CUSTOMERS FROM transactions WHERE COUNTERPARTY_COUNTRY_RISK IN (''HIGH'', ''PROHIBITED'') GROUP BY COUNTERPARTY_COUNTRY, COUNTERPARTY_COUNTRY_RISK ORDER BY TOTAL_AED DESC'
    ),
    pep_alerts AS (
      QUESTION 'Do any politically exposed persons have open alerts?'
      SQL 'SELECT c.CUSTOMER_ID, c.FULL_NAME, a.RULE_ID, a.SEVERITY, a.AMOUNT_AED FROM customers AS c JOIN alerts AS a ON a.CUSTOMER_ID = c.CUSTOMER_ID WHERE c.PEP_FLAG = TRUE AND a.STATUS IN (''NEW'', ''IN_REVIEW'', ''ESCALATED'')'
    )
  );

CREATE OR REPLACE SEMANTIC VIEW RAQIB.AI.RISK_SV
  TABLES (
    lcr AS RAQIB.RISK.LCR_DAILY PRIMARY KEY (AS_OF_DATE)
      WITH SYNONYMS ('liquidity', 'liquidity coverage ratio')
      COMMENT = 'Daily Basel III Liquidity Coverage Ratio and its components (AED millions)',
    loans AS RAQIB.RISK.LOAN_ECL PRIMARY KEY (LOAN_ID)
      WITH SYNONYMS ('credit book', 'facilities', 'exposures')
      COMMENT = 'Loan-level IFRS 9 staging, days past due and expected credit loss'
  )
  FACTS (
    lcr.lcr_pct_fact AS LCR_PCT,
    loans.ead_fact AS EAD_AED
  )
  DIMENSIONS (
    lcr.as_of_date AS AS_OF_DATE WITH SYNONYMS ('date', 'reporting date'),
    lcr.lcr_status AS LCR_STATUS COMMENT = 'COMPLIANT >= 110%, EARLY_WARNING 100-110%, BREACH < 100%',
    loans.loan_id AS LOAN_ID,
    loans.customer_id AS CUSTOMER_ID,
    loans.borrower_name AS FULL_NAME,
    loans.product AS PRODUCT,
    loans.sector AS SECTOR WITH SYNONYMS ('industry'),
    loans.ifrs9_stage AS IFRS9_STAGE WITH SYNONYMS ('stage') COMMENT = '1 performing, 2 SICR, 3 credit-impaired',
    loans.dpd_bucket AS DPD_BUCKET WITH SYNONYMS ('arrears bucket'),
    loans.is_npl AS IS_NPL WITH SYNONYMS ('non-performing')
  )
  METRICS (
    lcr.lcr_percent AS AVG(lcr.LCR_PCT) WITH SYNONYMS ('LCR') COMMENT = 'Use with as_of_date for a daily value',
    lcr.minimum_lcr_percent AS MIN(lcr.LCR_PCT),
    lcr.hqla_aed_m AS AVG(lcr.HQLA_TOTAL_AED_M) WITH SYNONYMS ('liquid assets'),
    lcr.net_outflows_aed_m AS AVG(lcr.NET_OUTFLOWS_AED_M),
    lcr.early_warning_days AS COUNT_IF(lcr.LCR_STATUS <> 'COMPLIANT'),
    loans.exposure_aed AS SUM(loans.EAD_AED) WITH SYNONYMS ('outstanding', 'EAD'),
    loans.npl_exposure_aed AS SUM(IFF(loans.IS_NPL, loans.EAD_AED, 0)),
    loans.npl_ratio_pct AS 100 * SUM(IFF(loans.IS_NPL, loans.EAD_AED, 0)) / NULLIF(SUM(loans.EAD_AED), 0) WITH SYNONYMS ('NPL ratio'),
    loans.ecl_aed AS SUM(loans.ECL_AED) WITH SYNONYMS ('provisions', 'expected credit loss'),
    loans.loan_count AS COUNT(loans.LOAN_ID)
  )
  COMMENT = 'Raqib prudential risk ontology: Basel III LCR and IFRS 9 credit risk'
  AI_SQL_GENERATION 'Liquidity amounts are AED millions; credit amounts are AED. Regulatory LCR minimum is 100% and the internal early-warning trigger is 110%. NPL appetite is below 6%. The latest reporting date is the max AS_OF_DATE. Coverage ratio = SUM(ECL_AED)/NULLIF(SUM(EAD_AED),0)*100.'
  AI_VERIFIED_QUERIES (
    lcr_latest AS (
      QUESTION 'What is our current LCR and are we compliant?'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT AS_OF_DATE, LCR_PCT, LCR_STATUS, HQLA_TOTAL_AED_M, NET_OUTFLOWS_AED_M FROM lcr ORDER BY AS_OF_DATE DESC LIMIT 1'
    ),
    lcr_early_warnings AS (
      QUESTION 'On which days did the LCR fall below the 110% early-warning trigger?'
      SQL 'SELECT AS_OF_DATE, LCR_PCT, LCR_STATUS FROM lcr WHERE LCR_STATUS <> ''COMPLIANT'' ORDER BY AS_OF_DATE'
    ),
    npl_by_sector AS (
      QUESTION 'What is the NPL ratio by sector?'
      ONBOARDING_QUESTION TRUE
      SQL 'SELECT SECTOR, SUM(EAD_AED) AS EXPOSURE_AED, 100 * SUM(IFF(IS_NPL, EAD_AED, 0)) / NULLIF(SUM(EAD_AED), 0) AS NPL_RATIO_PCT FROM loans GROUP BY SECTOR ORDER BY NPL_RATIO_PCT DESC'
    ),
    stage_mix AS (
      QUESTION 'Show exposure and ECL by IFRS 9 stage'
      SQL 'SELECT IFRS9_STAGE, COUNT(LOAN_ID) AS LOANS, SUM(EAD_AED) AS EXPOSURE_AED, SUM(ECL_AED) AS ECL_AED FROM loans GROUP BY IFRS9_STAGE ORDER BY IFRS9_STAGE'
    )
  );

GRANT SELECT ON SEMANTIC VIEW RAQIB.AI.AML_SV  TO ROLE RAQIB_ANALYST;
GRANT SELECT ON SEMANTIC VIEW RAQIB.AI.RISK_SV TO ROLE RAQIB_ANALYST;

-- Ontology check: the same governed metric answered through the semantic layer
SELECT * FROM SEMANTIC_VIEW(
    RAQIB.AI.AML_SV
    DIMENSIONS alerts.rule_id
    METRICS alerts.alert_count, alerts.alerted_value_aed
) ORDER BY rule_id;
