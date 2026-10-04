#!/usr/bin/env bash
# Raqib end-to-end deploy. Intended to be executed BY CoCo (Cortex Code) in the Execution phase:
#   cortex exec "Run scripts/deploy.sh and fix any errors you hit, explaining each fix"
# Requires: Snowflake CLI (`snow`) with a connection named $RAQIB_CONN (default: raqib).
set -euo pipefail
CONN="${RAQIB_CONN:-raqib}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
run() { echo "▶ $1"; snow sql -c "$CONN" -f "$1"; }

echo "== 1. Synthetic data + policy PDFs"
.venv/bin/python data_gen/generate.py --out data/generated
.venv/bin/python data_gen/build_pdfs.py

echo "== 2. Platform setup (ACCOUNTADMIN)"
run sql/01_setup.sql

echo "== 3. Stage files"
snow sql -c "$CONN" -q "USE ROLE RAQIB_ADMIN; PUT file://$ROOT/data/generated/*.csv @RAQIB.RAW.LANDING AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
snow sql -c "$CONN" -q "USE ROLE RAQIB_ADMIN; PUT file://$ROOT/data/generated/docs/*.pdf @RAQIB.DOCS.POLICY_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE"

echo "== 4. Pipeline, detection, risk"
run sql/02_raw_tables.sql
run sql/03_core_pipeline.sql
run sql/04_detection.sql
run sql/05_risk_reporting.sql

echo "== 5. Documents -> Cortex Search"
run sql/06_documents.sql

echo "== 6. Tools, case management"
snow sql -c "$CONN" -q "USE ROLE RAQIB_ADMIN; CREATE STAGE IF NOT EXISTS RAQIB.OPS.CODE_STAGE; PUT file://$ROOT/tools/raqib_tools.py @RAQIB.OPS.CODE_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE"
run sql/07_case_management_and_tools.sql

echo "== 7. Governance, semantic views, agent, automation"
run sql/08_governance.sql
run sql/09_semantic_views.sql
run sql/10_agent.sql
run sql/11_automation.sql

echo "== 8. Streamlit in Snowflake"
(cd app && snow streamlit deploy --replace -c "$CONN")
snow sql -c "$CONN" -q "USE ROLE RAQIB_ADMIN; GRANT USAGE ON STREAMLIT RAQIB.APP.RAQIB_APP TO ROLE RAQIB_ANALYST"

echo "== 9. Validate"
.venv/bin/python eval/run_eval.py --connection "$CONN" || true
echo "✅ Raqib deployed. Open Snowsight → Projects → Streamlit → RAQIB_APP"
