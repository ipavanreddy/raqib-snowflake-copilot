-- =====================================================================================
-- Raqib | 12 STREAMLIT IN SNOWFLAKE
-- Preferred: `snow streamlit deploy --replace --project app` (uses app/snowflake.yml).
-- Manual alternative below: PUT the app files to the stage, then CREATE STREAMLIT.
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

-- PUT file://app/streamlit_app.py @RAQIB.APP.STREAMLIT_STAGE/raqib AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
-- PUT file://app/environment.yml  @RAQIB.APP.STREAMLIT_STAGE/raqib AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
-- PUT file://app/pages/*.py       @RAQIB.APP.STREAMLIT_STAGE/raqib/pages AUTO_COMPRESS=FALSE OVERWRITE=TRUE;
-- PUT file://app/lib/*.py         @RAQIB.APP.STREAMLIT_STAGE/raqib/lib AUTO_COMPRESS=FALSE OVERWRITE=TRUE;

CREATE OR REPLACE STREAMLIT RAQIB.APP.RAQIB_APP
  FROM '@RAQIB.APP.STREAMLIT_STAGE/raqib'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = RAQIB_WH
  TITLE = 'Raqib — Risk, Fraud & Regulatory Copilot'
  COMMENT = 'Raqib command center, copilot, investigations, reports, governance';

GRANT USAGE ON STREAMLIT RAQIB.APP.RAQIB_APP TO ROLE RAQIB_ANALYST;
