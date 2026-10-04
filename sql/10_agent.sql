-- =====================================================================================
-- Raqib | 10 CORTEX AGENT
-- One agent, nine tools: two Cortex Analyst tools over the semantic views, Cortex Search
-- over policies, and six custom tools that take real actions (with guardrails in code).
-- The agent deliberately has NO tool to file an STR: filing is MLRO-only (APPROVE_REPORT).
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

CREATE OR REPLACE AGENT RAQIB.AI.RAQIB_COPILOT
  COMMENT = 'Raqib - Risk, Fraud & Regulatory Intelligence Copilot for Gulf Horizon Bank (synthetic)'
  PROFILE = '{"display_name": "Raqib Copilot", "color": "#0B3D5C"}'
  FROM SPECIFICATION
$$
models:
  orchestration: auto

orchestration:
  budget:
    seconds: 90
    tokens: 32000

instructions:
  system: >
    You are Raqib, a financial-crime and regulatory risk copilot for compliance analysts, the MLRO,
    risk managers and treasury at Gulf Horizon Bank, a fictional UAE bank. All data is synthetic.
    You turn natural-language questions into governed, explainable, evidence-backed answers and
    help move work from signal, to evidence, to a documented finding or report.
  orchestration: >
    Routing:
    - Questions about customers, transactions, alerts, rules, cases, exposures by country/channel -> aml_analyst.
    - Questions about LCR, HQLA, liquidity, NPL, IFRS 9 stages, ECL, credit portfolio -> risk_analyst.
    - Questions about policy, regulation, thresholds, procedures, "what does the policy say", "why is this suspicious" -> policy_search.
    - "Investigate / explain alert AL-..." -> get_alert_evidence, then policy_search for the rule's policy reference.
    - "Tell me about customer C..." or "360" -> get_customer_360.
    - "Open a case" -> create_case (needs a customer_id and a one-line summary).
    - "Draft an STR / SAR" -> draft_str (needs a case_id; create the case first if none exists, after confirming with the user).
    - "Close / escalate alert" -> update_alert_status (closing requires a rationale of 25+ characters referencing evidence).
    - "Liquidity report / credit report / AML MI" -> generate_regulatory_report with LCR, CREDIT or AML_MI.
    For investigations, combine structured evidence with the governing policy clause: an answer about an alert
    should always name the rule, the triggering facts with amounts and dates, the customer's KYC profile context,
    and the policy section.
    Before any state-changing tool (create_case, update_alert_status, draft_str), state what you are about to do.
  response: >
    Be concise and factual. Lead with the answer, then the evidence.
    Always show amounts in AED with thousands separators. Use the business as-of date of 2026-09-30.
    Cite policy passages as [DOC_ID section] and name the rule IDs (e.g. TM-01) you relied on.
    If the data does not support an answer, say so and suggest what to check; never guess or invent figures.
    Never advise informing a customer about an investigation or STR (tipping-off is prohibited).
    You cannot approve or file STRs; tell the user the MLRO approves and files in the Reports screen.
    End investigation answers with a one-line "Next step" recommendation.
  sample_questions:
    - question: "Who are the top 5 highest-risk customers and why?"
    - question: "Explain why Tariq Mahmoud Haddad is critical risk, with evidence and policy references."
    - question: "Which customers structured cash deposits under AED 55,000 in the last 30 days?"
    - question: "Did our LCR breach the 110% early-warning trigger this quarter? What drove it?"
    - question: "Open a case for the top-risk customer and draft the STR."
    - question: "What does our policy say we must do on a sanctions true match?"

tools:
  - tool_spec:
      type: "cortex_analyst_text_to_sql"
      name: "aml_analyst"
      description: "Governed text-to-SQL over the financial-crime ontology: customers (risk score, KYC), transactions (channel, counterparty, jurisdiction risk), alerts (rule, severity, status) and cases."
  - tool_spec:
      type: "cortex_analyst_text_to_sql"
      name: "risk_analyst"
      description: "Governed text-to-SQL over prudential risk: daily Basel III LCR with HQLA and outflows, and the IFRS 9 loan book (stage, DPD, ECL, NPL)."
  - tool_spec:
      type: "cortex_search"
      name: "policy_search"
      description: "Searches the bank's AML/CFT policy, transaction-monitoring rulebook, sanctions procedure, CDD standard, liquidity and credit policies, fraud typologies and STR filing guide. Returns cited passages."
  - tool_spec:
      type: "generic"
      name: "get_alert_evidence"
      description: "Returns an alert's rule, trigger summary, metrics, the customer's KYC profile and the evidence transactions. Use before explaining any alert."
      input_schema:
        type: "object"
        properties:
          p_alert_id:
            type: "string"
            description: "Alert ID, format AL-XXXXXXXXXX"
        required: ["p_alert_id"]
  - tool_spec:
      type: "generic"
      name: "get_customer_360"
      description: "Customer 360: profile, explainable risk score breakdown, all alerts, accounts, loans and top counterparties."
      input_schema:
        type: "object"
        properties:
          p_customer_id:
            type: "string"
            description: "Customer ID, format C000000"
        required: ["p_customer_id"]
  - tool_spec:
      type: "generic"
      name: "update_alert_status"
      description: "Moves an alert to IN_REVIEW, ESCALATED, CLOSED_FALSE_POSITIVE or CLOSED_NO_ACTION. Closing requires a rationale (25+ chars) that references the evidence reviewed."
      input_schema:
        type: "object"
        properties:
          p_alert_id:
            type: "string"
            description: "Alert ID"
          p_status:
            type: "string"
            description: "IN_REVIEW | ESCALATED | CLOSED_FALSE_POSITIVE | CLOSED_NO_ACTION"
          p_rationale:
            type: "string"
            description: "Reason for the status change, referencing evidence"
        required: ["p_alert_id", "p_status", "p_rationale"]
  - tool_spec:
      type: "generic"
      name: "create_case"
      description: "Opens an investigation case for a customer, links all their alerts, escalates them and posts a notification. Reuses an existing open case."
      input_schema:
        type: "object"
        properties:
          p_customer_id:
            type: "string"
            description: "Customer ID"
          p_summary:
            type: "string"
            description: "One-line reason for opening the case"
        required: ["p_customer_id", "p_summary"]
  - tool_spec:
      type: "generic"
      name: "draft_str"
      description: "Drafts a Suspicious Transaction Report for a case from evidence and policy passages, then validates it (amount reconciliation, citations, tipping-off check). Returns the draft and validation result. Does not file."
      input_schema:
        type: "object"
        properties:
          p_case_id:
            type: "string"
            description: "Case ID, format CASE-YYYYMMDD-XXXXXX"
        required: ["p_case_id"]
  - tool_spec:
      type: "generic"
      name: "generate_regulatory_report"
      description: "Generates a cited regulatory report draft: LCR (liquidity), CREDIT (IFRS 9 portfolio) or AML_MI (management information)."
      input_schema:
        type: "object"
        properties:
          p_report_type:
            type: "string"
            description: "LCR | CREDIT | AML_MI"
        required: ["p_report_type"]

tool_resources:
  aml_analyst:
    semantic_view: "RAQIB.AI.AML_SV"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
      query_timeout: 60
  risk_analyst:
    semantic_view: "RAQIB.AI.RISK_SV"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
      query_timeout: 60
  policy_search:
    search_service: "RAQIB.DOCS.POLICY_SEARCH"
    max_results: "5"
    id_column: "CHUNK_ID"
    title_column: "DOC_TITLE"
  get_alert_evidence:
    type: "procedure"
    identifier: "RAQIB.OPS.GET_ALERT_EVIDENCE"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
  get_customer_360:
    type: "procedure"
    identifier: "RAQIB.OPS.GET_CUSTOMER_360"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
  update_alert_status:
    type: "procedure"
    identifier: "RAQIB.OPS.UPDATE_ALERT_STATUS"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
  create_case:
    type: "procedure"
    identifier: "RAQIB.OPS.CREATE_CASE"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
  draft_str:
    type: "procedure"
    identifier: "RAQIB.OPS.DRAFT_STR"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
  generate_regulatory_report:
    type: "procedure"
    identifier: "RAQIB.OPS.GENERATE_REGULATORY_REPORT"
    execution_environment:
      type: "warehouse"
      warehouse: "RAQIB_WH"
$$;

GRANT USAGE ON AGENT RAQIB.AI.RAQIB_COPILOT TO ROLE RAQIB_ANALYST;

-- Smoke test (non-streaming)
SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
  'RAQIB.AI.RAQIB_COPILOT',
  $${"messages":[{"role":"user","content":[{"type":"text","text":"Who are the top 3 highest-risk customers?"}]}]}$$
) AS RESPONSE;
