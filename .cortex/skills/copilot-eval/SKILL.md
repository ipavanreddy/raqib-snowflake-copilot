---
name: copilot-eval
description: Evaluate a Cortex Agent or semantic view against a golden question set — required facts, forbidden phrases (e.g. tipping-off), unknown-entity handling — and store a scorecard in Snowflake. Use when asked to test, validate, regression-check or benchmark the copilot, its semantic views or verified queries.
tools:
  - bash
  - read
  - write
  - sql_execute
  - snowflake_sql_execute
---

# Copilot Evaluation

## 1. Semantic-view checks (deterministic)
For each verified query in `sql/09_semantic_views.sql`:
- Run it against the semantic view and confirm it returns rows.
- Compare one governed metric with the physical-table equivalent. They must match exactly. This proves that the ontology resolves the same way everywhere:
```sql
SELECT * FROM SEMANTIC_VIEW(RAQIB.AI.AML_SV DIMENSIONS alerts.rule_id METRICS alerts.alert_count) ORDER BY rule_id;
SELECT RULE_ID, COUNT(*) FROM RAQIB.OPS.ALERT_QUEUE GROUP BY 1 ORDER BY 1;   -- must be identical
```

## 2. Agent golden set
```bash
.venv/bin/python eval/run_eval.py --connection raqib     # live agent; also writes RAQIB.OPS.EVAL_RESULTS
.venv/bin/python eval/run_eval.py --offline              # offline replica
```
Each case in `eval/golden_questions.yaml` has `must_contain` (alternatives separated by `|`) and `must_not_contain`.
The set covers:
- ranking
- explanation with citations
- typology search
- LCR trigger logic
- sanctions procedure
- threshold recall
- jurisdiction exposure
- NPL appetite
- the tipping-off refusal
- an unknown customer, which must answer "not found" and never invent figures

## 3. Report
Summarise the pass rate, the failures with the agent's answer excerpt, and a proposed fix for each. Fixes go to one of three places:
- semantic view synonyms or verified queries, if the SQL was wrong;
- agent instructions, if routing or tone was wrong;
- tools, if facts were wrong.

Re-run until the score is ≥ 90%, and record each run in `coco/EVIDENCE.md`.

## 4. Adding cases
Add a case for every bug you fix, so it stays fixed.
