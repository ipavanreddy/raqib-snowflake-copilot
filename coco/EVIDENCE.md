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

## Execute
| When | Action | Result | Screenshot |
|---|---|---|---|

## Test
| When | Check | Result | Screenshot |
|---|---|---|---|

## Skills, MCP, automations, multi-agent
| Capability | How it was used | Evidence |
|---|---|---|
| Custom skills (`.cortex/skills/*`) | | |
| MCP (Slack/Jira) | | |
| Scheduled runs | | |
| Multi-agent (`.cortex/agents/*`) | | |
| Cross-surface (CLI / Desktop / Snowsight agent / Streamlit) | | |
