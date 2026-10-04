# Phase 3 — EXECUTE (run the end-to-end flow through CoCo)

Use connection `raqib`.
1. **Baseline.** Show the top 5 customers from RAQIB.DETECT.CUSTOMER_RISK and the LCR status for the latest day.
2. **Live signal.** `CALL RAQIB.OPS.SIMULATE_ACTIVITY('STRUCTURING');` then `EXECUTE TASK RAQIB.OPS.ALERT_ROUTER;`.
   Show the new alert, and the new PENDING row in RAQIB.OPS.NOTIFICATIONS.
3. **Investigate.** Use `$aml-investigation` on the customer that the simulator just created activity for.
4. **Document.** Open a case and draft the STR (CREATE_CASE → DRAFT_STR). Show the validation result.
5. **Notify.** Use `$alert-dispatch` to post the pending notifications to Slack (and Jira for CRITICAL items) via MCP.
6. **Regulatory.** `CALL RAQIB.OPS.GENERATE_REGULATORY_REPORT('LCR');` then summarise the report.
7. **Unattended.** Confirm the tasks are scheduled: `SHOW TASKS IN SCHEMA RAQIB.OPS;`. Install the CoCo dispatch schedule
   from coco/automations/README.md.
8. **Cross-surface.** Ask the agent the same question from CoCo (`cortex agents` / DATA_AGENT_RUN) and confirm the answer
   matches the Streamlit Copilot and Snowsight agent chat.
Log the outputs under "Execute" in coco/EVIDENCE.md.
