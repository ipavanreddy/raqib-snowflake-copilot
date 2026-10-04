-- =====================================================================================
-- Raqib | 06 DOCUMENT INTELLIGENCE
-- PDFs on @POLICY_STAGE -> AI_PARSE_DOCUMENT (layout) -> metadata (regex + AI_EXTRACT)
-- -> section-aware chunks -> Cortex Search service used by the agent for citations.
-- Upload PDFs first: scripts/load_data.sh (PUT data/generated/docs/*.pdf).
-- =====================================================================================
USE ROLE RAQIB_ADMIN;
USE WAREHOUSE RAQIB_WH;

ALTER STAGE RAQIB.DOCS.POLICY_STAGE REFRESH;

-- 1. Parse every PDF once (layout mode keeps headings and tables as markdown)
CREATE OR REPLACE TABLE RAQIB.DOCS.DOCUMENTS
  COMMENT = 'Parsed policy / regulatory documents'
AS
WITH files AS (
    SELECT RELATIVE_PATH AS FILE_NAME, LAST_MODIFIED
    FROM DIRECTORY(@RAQIB.DOCS.POLICY_STAGE)
    WHERE RELATIVE_PATH ILIKE '%.pdf'
),
parsed AS (
    SELECT
        FILE_NAME,
        LAST_MODIFIED,
        AI_PARSE_DOCUMENT(TO_FILE('@RAQIB.DOCS.POLICY_STAGE', FILE_NAME), {'mode': 'LAYOUT'}) AS PARSED
    FROM files
)
SELECT
    FILE_NAME,
    REGEXP_SUBSTR(PARSED:content::VARCHAR, 'POL-[A-Z]+-[0-9]{3}')        AS DOC_ID,
    PARSED:content::VARCHAR                                              AS CONTENT,
    LENGTH(PARSED:content::VARCHAR)                                      AS CONTENT_CHARS,
    LAST_MODIFIED,
    CURRENT_TIMESTAMP()                                                  AS PARSED_AT
FROM parsed;

-- 2. Enrich with structured metadata extracted by Cortex AI (title, owner, effective date)
ALTER TABLE RAQIB.DOCS.DOCUMENTS ADD COLUMN IF NOT EXISTS METADATA VARIANT;
UPDATE RAQIB.DOCS.DOCUMENTS
SET METADATA = AI_EXTRACT(
    text => LEFT(CONTENT, 4000),
    responseFormat => {
        'title': 'What is the document title?',
        'owner': 'Who owns the document (role)?',
        'effective_date': 'What is the effective date (YYYY-MM-DD)?',
        'version': 'What is the document version?'
    });

CREATE OR REPLACE VIEW RAQIB.DOCS.DOCUMENT_CATALOG
  COMMENT = 'One row per policy document with AI-extracted metadata'
AS
SELECT
    DOC_ID,
    COALESCE(METADATA:response:title::VARCHAR, FILE_NAME) AS DOC_TITLE,
    METADATA:response:owner::VARCHAR                      AS OWNER,
    METADATA:response:effective_date::VARCHAR             AS EFFECTIVE_DATE,
    METADATA:response:version::VARCHAR                    AS VERSION,
    FILE_NAME,
    CONTENT_CHARS,
    PARSED_AT
FROM RAQIB.DOCS.DOCUMENTS;

-- 3. Section-aware chunks. Each chunk is prefixed with its document title so retrieval
--    results are self-describing when shown as citations.
CREATE OR REPLACE TABLE RAQIB.DOCS.POLICY_CHUNKS
  COMMENT = 'Retrieval chunks for Cortex Search'
AS
SELECT
    d.DOC_ID || '#' || LPAD(c.INDEX::VARCHAR, 3, '0')                            AS CHUNK_ID,
    d.DOC_ID,
    cat.DOC_TITLE,
    d.FILE_NAME,
    c.INDEX                                                                      AS CHUNK_INDEX,
    COALESCE(REGEXP_SUBSTR(c.VALUE::VARCHAR, '#{1,4} *([^\n]+)', 1, 1, 'e', 1), 'General') AS SECTION,
    '[' || d.DOC_ID || ' | ' || cat.DOC_TITLE || ']\n' || c.VALUE::VARCHAR        AS CHUNK
FROM RAQIB.DOCS.DOCUMENTS d
JOIN RAQIB.DOCS.DOCUMENT_CATALOG cat ON cat.DOC_ID = d.DOC_ID,
LATERAL FLATTEN(INPUT => SNOWFLAKE.CORTEX.SPLIT_TEXT_RECURSIVE_CHARACTER(d.CONTENT, 'markdown', 1400, 200)) c;

-- 4. Cortex Search service (hybrid vector + keyword) over the chunks
CREATE OR REPLACE CORTEX SEARCH SERVICE RAQIB.DOCS.POLICY_SEARCH
  ON CHUNK
  ATTRIBUTES DOC_ID, DOC_TITLE, SECTION
  WAREHOUSE = RAQIB_WH
  TARGET_LAG = '1 day'
  COMMENT = 'Policy & regulatory knowledge base for the Raqib copilot'
AS
SELECT CHUNK, CHUNK_ID, DOC_ID, DOC_TITLE, SECTION, FILE_NAME
FROM RAQIB.DOCS.POLICY_CHUNKS;

-- 5. Smoke test: should return the structuring threshold clause (AED 55,000)
SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(
    'RAQIB.DOCS.POLICY_SEARCH',
    '{"query": "cash deposits just below reporting threshold structuring", "columns": ["CHUNK_ID", "DOC_TITLE", "SECTION"], "limit": 3}'
)):results AS TOP_HITS;
