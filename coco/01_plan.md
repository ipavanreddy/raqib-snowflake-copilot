# Phase 1 — PLAN (run in CoCo before building)

You are the lead data architect for "Raqib", a Risk, Fraud & Regulatory Intelligence Copilot for a fictional UAE bank.
Hackathon problem: banking/NBFC teams handle fraud, liquidity, credit risk and AML/Basel reporting manually. Build a
copilot that surfaces risk and fraud signals and produces audit-ready regulatory outputs from natural-language questions.

Do the following and write your results to `docs/coco_plan_review.md`:
1. **Explore the data.** Run `.venv/bin/python data_gen/generate.py --out data/generated` and profile every CSV: row counts, keys, null
   rates, value distributions, date ranges. Check referential integrity (txn→account→customer, txn→counterparty).
2. **Frame the problem.** Name the personas (analyst, MLRO, treasury/risk), their top 5 questions each, and today's manual pain.
3. **Review the design.** Read `docs/solution_design.md`, then critique the data model, ontology
   (Customer→Account→Transaction→Counterparty→Alert→Case→Report, plus LCR and Loan) and workflow (signal→evidence→finding).
   Propose concrete improvements.
4. **Map rules to policies.** Read `policy_docs/02_transaction_monitoring_rulebook.md` and check that every rule threshold matches
   `sql/04_detection.sql`. List any mismatches.
5. **Rank risks.** List the top risks to a successful demo (trial limits, model availability, data volume, latency) with mitigations.
Do not create Snowflake objects in this phase.
