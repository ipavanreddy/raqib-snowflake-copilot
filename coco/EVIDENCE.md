# CoCo usage evidence log

Fill this in while you run each phase. Judges look for CoCo at every stage.
Attach screenshots under `docs/coco_evidence/` and reference them here.
List sessions with `cortex conversations`. Export or screenshot the key ones.

## Plan
| When | Session / prompt | What CoCo produced | Screenshot |
|---|---|---|---|
| 2026-10-04 | `coco/01_plan.md` | Full plan review: data profiling of 10 CSVs (215k txn, 42 planted cases, 0 orphans), persona framing (4 personas × 5 questions), design critique (6 improvements), rule-to-policy mapping (all 8 rules match), risk ranking (8 risks) → `docs/coco_plan_review.md` | |

## Build
| When | Step | Error hit (if any) | Fix CoCo applied | Screenshot |
|---|---|---|---|---|
| 2026-10-04 | 01 Setup | None | Roles, warehouse, schemas, stages, file format created cleanly | |
| 2026-10-04 | 02 Raw load | None | 10 CSVs PUT + COPY INTO; all row counts match manifest exactly | |
| 2026-10-04 | 03 Core pipeline | None | TXN_ENRICHED (215,364 rows) and CUSTOMER_PROFILE (2,150) DTs created | |
| 2026-10-04 | 04 Detection | **ALERTS DT failed**: views over DTs not allowed without `DYNAMIC_TABLE_REFRESH_BOUNDARY()` | Wrapped all 8 rule-view references in `DYNAMIC_TABLE_REFRESH_BOUNDARY()` in both the session and `sql/04_detection.sql` (line 470-477) | |
| 2026-10-04 | 05 Risk reporting | None | LCR_DAILY, LOAN_ECL, CREDIT_PORTFOLIO_SUMMARY, AML_CREDIT_OVERLAP views created | |
| 2026-10-04 | 06 Documents | None | 8 PDFs parsed via AI_PARSE_DOCUMENT, 25 chunks created, Cortex Search service live (smoke test returns TM Rulebook) | |
| 2026-10-04 | 07 Tools | None | 7 stored procedures created; GET_CUSTOMER_360 returns C000660 (Tariq, score 100, 5 alerts) | |
| 2026-10-04 | 08 Governance | **Masking policies unsupported** (Standard edition) | Replaced masking policies with `SECURE VIEW RAQIB.CORE.CUSTOMER_PROFILE_SECURE` using `IS_ROLE_IN_SESSION('RAQIB_MLRO')`. Revoked analyst's direct SELECT on `RAW.CUSTOMERS` and `CORE.CUSTOMER_PROFILE`. Proof: `USE SECONDARY ROLES NONE; USE ROLE RAQIB_ANALYST` → EMIRATES_ID shows `**************54-9`, DOB truncated to year; `USE ROLE RAQIB_MLRO` → full PII `784-1964-9478454-9`, `1964-11-24`. Added caveat comment explaining secondary-roles behaviour for single-user testing. | |
| 2026-10-04 | 09 Semantic views | **RISK_SV failed**: `ECL_AED` cannot be a fact (computed column); `coverage_pct` metric can't cross-reference other metrics | Removed `loans.ecl_fact` from FACTS, removed `loans.coverage_pct` metric, moved coverage formula to AI_SQL_GENERATION instruction. Fixed `sql/09_semantic_views.sql`. | |
| 2026-10-04 | 10 Agent | None | RAQIB_COPILOT agent created with 9 tools. Smoke test returns top 3 customers correctly via verified query. | |
| 2026-10-04 | 11 Automation | **Stream on ALERTS DT failed**: streams not supported on FULL-refresh dynamic tables | Replaced stream-based ALERT_ROUTER with poll-based approach using `NOT EXISTS`. Fixed `sql/11_automation.sql`. | |
| 2026-10-04 | 11 Automation | New feature: PIPELINE_HEALTH view | Added `RAQIB.OPS.PIPELINE_HEALTH` view to `sql/11_automation.sql` — shows last refresh time, state and health status for all 4 DTs (from `INFORMATION_SCHEMA.DYNAMIC_TABLE_REFRESH_HISTORY`). All 4 DTs showing HEALTHY. | |
| 2026-10-04 | 12 Streamlit | None | `snow streamlit deploy --replace -c raqib` succeeded. App live at `RAQIB.APP.RAQIB_APP`. | |
| 2026-10-05 | 12 Streamlit fix | **`_snowflake` module missing** in SiS container runtime | `app/lib/backend.py`: wrapped `import _snowflake` in try/except; on `ModuleNotFoundError` falls back to `_agent_via_sql()` which calls `SNOWFLAKE.CORTEX.DATA_AGENT_RUN` through the active Snowpark session. Added `parse_agent_response()` to map non-streaming response to the streaming event shape. | |

## Execute
| When | Action | Result | Screenshot |
|---|---|---|---|
| 2026-10-05 | E1 Baseline | Top 5: C000660 Tariq (100 CRITICAL), C002074 Palm Crescent (95), C002099 Pearl Crescent (87), C002051 Blue Wave (87), C001952 Crescent Crescent (83). LCR 129.8% COMPLIANT as of 2026-09-30. | |
| 2026-10-05 | E2 Live signal | `SIMULATE_ACTIVITY('STRUCTURING')` → 4 cash deposits AED 47k-54k for James Santos (C000331) across 4 branches. `EXECUTE TASK ALERT_ROUTER` → new alert AL-B05405EC1B (TM-01 HIGH) + AL-CFA98DB07B (TM-07 MEDIUM). 1 PENDING notification created. | |
| 2026-10-05 | E3 Investigate (`$aml-investigation`) | Full investigation of C000331: GET_ALERT_EVIDENCE for both alerts, GET_CUSTOMER_360 (score 49 HIGH, IT Consultant, AED 12k turnover, 17.5x deviation), policy search (POL-TM-002#001 s.4.1 structuring threshold). Finding written per skill template. | |
| 2026-10-05 | E4 Document | `CREATE_CASE('C000331', ...)` → CASE-20261005-694748 (P2, 2 linked alerts). `DRAFT_STR('CASE-20261005-694748')` → STR-20261005-EB4FCA. Validation: 28/28 amounts reconciled, citations valid, 0 tipping-off flags, confidence 1.0, status DRAFT. | |
| 2026-10-05 | E5 Notify | **Skipped**: no Slack or Jira MCP server configured (only Figma and Meta Ads present). In production, `$alert-dispatch` drains `RAQIB.OPS.NOTIFICATIONS` to Slack/Jira via MCP. 1 PENDING notification remains in the outbox. | |
| 2026-10-05 | E6 Regulatory | `GENERATE_REGULATORY_REPORT('LCR')` → LCR-20261005-013A45. LCR 129.8% COMPLIANT at month-end but trough of 101.6% on 2026-09-16 (EARLY_WARNING). 3 consecutive days below 110% trigger. HQLA drawdown of AED 1,648M Level 1, wholesale outflow +314M. Validation passed, confidence 1.0. | |
| 2026-10-05 | E7 Unattended | 3 tasks active: ALERT_ROUTER (every 5 min), DAILY_BRIEFING (07:00 Dubai), DAILY_LCR_REPORT (after briefing). CoCo-level dispatch schedule documented in `coco/automations/README.md`; not installed (no Slack MCP). | |
| 2026-10-05 | E8 Cross-surface | `DATA_AGENT_RUN` "How many open alerts by rule?" → 77 open alerts across 8 rules (TM-07: 28, TM-04: 16, TM-01: 9, TM-06: 6, TM-03: 5, TM-02: 5, TM-05: 4, FR-01: 4). Includes chart. Matches semantic view query from build phase (+2 from simulator). | |

## Test
| When | Check | Result | Screenshot |
|---|---|---|---|
| 2026-10-05 | T1 Detection quality | **PASS** — 100% recall: all 42 planted cases detected across all 8 rules. False positives per rule: TM-01 1, TM-07 1, all others 0. Max 1 non-planted alert per rule (target ≤12). | |
| 2026-10-05 | T2 Ontology consistency | **PASS** — semantic-view metric `alerts.alert_count` by `alerts.rule_id` matches physical query on `RAQIB.OPS.ALERT_QUEUE` exactly for all 8 rules. | |
| 2026-10-05 | T3a Governance (analyst masked) | **PASS** — `USE SECONDARY ROLES NONE; USE ROLE RAQIB_ANALYST` → EMIRATES_ID `**************54-9`, PHONE `*********5942`. | |
| 2026-10-05 | T3b Governance (planted denied) | **PASS** — `SELECT * FROM RAQIB.RAW.PLANTED_CASES` → "does not exist or not authorized". | |
| 2026-10-05 | T3c Governance (approve refused) | **PASS** — `CALL APPROVE_REPORT(...)` as RAQIB_ANALYST → "Unknown user-defined function". | |
| 2026-10-05 | T3d Governance (MLRO clear) | **PASS** — `USE ROLE RAQIB_MLRO` → full PII `784-1964-9478454-9`, `+971584335942`. | |
| 2026-10-05 | T3e Governance (MLRO files) | **PASS** — `APPROVE_AND_FILE` → status FILED, goAML ref GOAML-2026-TEST-001. | |
| 2026-10-05 | T4a Short rationale | **PASS** — `UPDATE_ALERT_STATUS(..., 'ok')` → rejected: "rationale of at least 25 characters". | |
| 2026-10-05 | T4b Tipping-off | **PASS** — agent refuses: "you must not tell the customer... tipping-off is prohibited". | |
| 2026-10-05 | T4c Unknown customer | **PASS** — `GET_CUSTOMER_360('C999999')` → "Customer C999999 not found." | |
| 2026-10-05 | T4d Model fallback | **PASS** — set LLM_MODEL to invalid, DRAFT_STR used `llama3.3-70b` (fallback), validation passed 8/8, confidence 1.0. Restored to `claude-sonnet-4-5`. | |
| 2026-10-05 | T5 Golden eval (live) | **PASS** — `run_eval.py --connection raqib` → **100% (10/10)**, mode=live. | |
| 2026-10-05 | T6 Local suite | **PASS** — `pytest tests -q` → **27 passed** in 5.84s. | |
| 2026-10-05 | T7 Freshness | **PASS** — `SIMULATE_ACTIVITY('BACKGROUND')` inserted 40 txns, all 4 DTs refreshed SUCCEEDED, PIPELINE_HEALTH shows HEALTHY. | |

### Scorecard

| # | Test | Target | Result | Status |
|---|---|---|---|---|
| T1 | Detection recall | 100% planted detected | 42/42 (100%) | PASS |
| T1 | False-positive cap | ≤12 per rule | max 1 | PASS |
| T2 | Ontology consistency | SV metric = physical | 8/8 match | PASS |
| T3 | RBAC enforcement | 5 checks | 5/5 | PASS |
| T4 | Guardrails | 4 checks | 4/4 | PASS |
| T5 | Golden eval (live) | ≥90% | 100% (10/10) | PASS |
| T6 | Local pytest suite | all green | 27/27 | PASS |
| T7 | DT freshness | refreshes after insert | all HEALTHY | PASS |

## Skills, MCP, automations, multi-agent
| Capability | How it was used | Evidence |
|---|---|---|
| Custom skills (`.cortex/skills/*`) | `$aml-investigation` skill drove the E3 investigation workflow (scope→signal→evidence→context→policy→finding→decision) | Investigation of C000331 with finding template |
| MCP (Slack/Jira) | Not configured on this account (Figma + Meta Ads only). Design supports `$alert-dispatch` draining `RAQIB.OPS.NOTIFICATIONS` to Slack/Jira. | Noted in E5 |
| Scheduled runs | 3 Snowflake tasks active (ALERT_ROUTER 5min, DAILY_BRIEFING 07:00, DAILY_LCR_REPORT). CoCo-level dispatch schedule in `coco/automations/README.md`. | `SHOW TASKS IN SCHEMA RAQIB.OPS` |
| Multi-agent (`.cortex/agents/*`) | `fincrime-investigator` and `report-validator` subagents defined for investigation and STR validation workflows | `.cortex/agents/` directory |
| Cross-surface (CLI / Desktop / Snowsight agent / Streamlit) | Same "open alerts by rule" question answered via CoCo CLI (`DATA_AGENT_RUN`) and Streamlit app. Agent uses AML_SV verified query. | E8 output matches E1 baseline (+2 from simulator) |
