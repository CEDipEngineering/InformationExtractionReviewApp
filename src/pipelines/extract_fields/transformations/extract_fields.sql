-- =============================================================================
-- Extract Financial Fields Pipeline
-- =============================================================================
-- Reads the raw parsed document text produced by the parse pipeline and
-- calls the Agent Bricks Information Extraction endpoint (via ai_query) to
-- produce structured JSON for each document.
--
-- Configuration keys (injected from resources/extract_pipeline.yml):
--   endpoint_name  — Model serving endpoint name passed to ai_query
--   source_table   — Fully-qualified parse pipeline output table
--                    (resolved at deploy time to catalog.schema.raw_parsed_content)
--
-- Output schema matches the JSON returned by the KIE endpoint:
--   {
--     "metadados_empresa": { "razao_social": "...", "cnpj": "..." },
--     "relatorios": [ { "identificacao": {...}, "balanco": {...}, "dre": {...} } ]
--   }
-- =============================================================================


CREATE OR REFRESH MATERIALIZED VIEW extracted_content
  COMMENT "Structured financial data extracted by Agent Bricks, one row per document"
AS
WITH query_results AS (
  SELECT
    path,
    raw_parsed,
    ai_query(
      '${endpoint_name}',
      raw_parsed,
      failOnError => false
    ) AS response
  FROM ${source_table}
  WHERE raw_parsed IS NOT NULL
)
SELECT
  path,
  raw_parsed,
  response.result        AS extracted,
  response.errorMessage  AS error,
  current_timestamp()    AS extracted_at
FROM query_results;

