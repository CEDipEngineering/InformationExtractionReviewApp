-- =============================================================================
-- Parse PDF Documents Pipeline
-- =============================================================================
-- Two-layer DLT pipeline:
--   1. raw_parse_output    (STREAMING TABLE)  — calls ai_parse_document once
--      per file and stores the raw VARIANT result.
--   2. raw_parsed_content  (MATERIALIZED VIEW) — extracts and concatenates
--      the text elements in page order; this is the table read by the app.
--
-- pdf_folder_path is injected from the `configuration` block in
-- resources/pipeline.yml via the `pdf_folder_path` bundle variable.
-- Access it in SQL as ${pdf_folder_path} (no `pipeline.` prefix — that is
-- reserved for built-in DLT system properties only).
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Step 1: Parse each file once, store the raw VARIANT for downstream reuse.
-- ---------------------------------------------------------------------------
CREATE OR REFRESH STREAMING TABLE raw_parse_output
  COMMENT "Raw VARIANT output from ai_parse_document, one row per file"
AS
SELECT
  path,
  ai_parse_document(content) AS parsed,
  current_timestamp()        AS ingested_at
FROM STREAM read_files(
  '${pdf_folder_path}',
  format => 'binaryFile'
)
WHERE lower(regexp_extract(path, r'(\.[^.]+)$', 1)) IN (
  '.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx', '.ppt', '.pptx'
);


-- ---------------------------------------------------------------------------
-- Step 2: Unpack the VARIANT — explode pages/elements, concatenate in order.
--         The `labels` column is a placeholder for the Agent Bricks extraction
--         output that will be added in a later pipeline step.
-- ---------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW raw_parsed_content
  COMMENT "Full text extracted from parsed documents, consumed by the review app"
AS
WITH elements AS (
  SELECT
    path,
    ingested_at,
    pos,
    element:content::STRING AS chunk
  FROM (
    SELECT
      path,
      ingested_at,
      posexplode(
        CASE
          WHEN try_cast(parsed:metadata:version AS STRING) = '1.0'
          THEN try_cast(parsed:document:pages   AS ARRAY<VARIANT>)
          ELSE try_cast(parsed:document:elements AS ARRAY<VARIANT>)
        END
      ) AS (pos, element)
    FROM raw_parse_output
    WHERE try_cast(parsed:error_status AS STRING) IS NULL
  )
  WHERE element:content IS NOT NULL
)
SELECT
  path,
  CAST(NULL AS STRING) AS labels,        -- populated by Agent Bricks in a future step
  concat_ws(
    '\n\n',
    transform(
      sort_array(collect_list(struct(pos, chunk))),
      s -> s.chunk
    )
  )                      AS raw_parsed,
  any_value(ingested_at) AS ingested_at
FROM elements
GROUP BY path;
