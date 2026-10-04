# Phase 2 — BUILD (CoCo builds everything in Snowflake)

Use connection `raqib`. Follow AGENTS.md. Work through the steps in order. After each step, verify it succeeded with a query
and log what you did (and any error you fixed) under "Build" in coco/EVIDENCE.md.

1. **Data.** Use skill `$synthetic-banking-data` to generate the data and build the policy PDFs
   (`python data_gen/build_pdfs.py`).
2. **Platform.** Run `sql/01_setup.sql`. If cross-region inference cannot be set, note it and continue.
3. **Load.** PUT the CSVs to `@RAQIB.RAW.LANDING` and the PDFs to `@RAQIB.DOCS.POLICY_STAGE`, then run `sql/02_raw_tables.sql`
   and compare the row counts with data/generated/manifest.json.
4. **Pipeline.** Run `sql/03_core_pipeline.sql`, `sql/04_detection.sql` and `sql/05_risk_reporting.sql`. Show
   `SHOW DYNAMIC TABLES IN DATABASE RAQIB` and the alert count by rule.
5. **Documents.** Run `sql/06_documents.sql`. Confirm 8 documents were parsed, show the chunk count, and run the search smoke test.
6. **Tools.** PUT tools/raqib_tools.py to `@RAQIB.OPS.CODE_STAGE`, run `sql/07_case_management_and_tools.sql`, and call
   GET_CUSTOMER_360 for the top-risk customer.
7. **Governance.** Run `sql/08_governance.sql` and show masked vs unmasked output.
8. **Semantic layer.** Run `sql/09_semantic_views.sql`. If any verified query or metric fails validation, fix the YAML/DDL
   in the file and re-run. Then answer "How many open alerts by rule?" through the semantic view.
9. **Agent.** Run `sql/10_agent.sql` and the DATA_AGENT_RUN smoke test.
10. **Automation.** Run `sql/11_automation.sql`.
11. **App.** Deploy with `cd app && snow streamlit deploy --replace -c raqib`, or run `sql/12_streamlit.sql`.
If a step fails, fix the root cause in the repo file (not only in the session) and continue.
