# Agent Instructions

This file is a guide for AI agents (Claude Code or similar) working on this project. Read it before making any changes.

## Project in one sentence

Databricks Asset Bundle that extracts structured financial data from PDFs and serves a Streamlit review app. The full pipeline runs as a single Databricks Job.

## Credentials and environment

- **Databricks CLI profile**: `fevm`
- **Workspace**: FEVM workspace (`fevm-cedip-fevm-aws-classic-stable.cloud.databricks.com`)
- **Catalog**: `cedip_fevm_aws_classic_stable_catalog`
- **Dev schema (reads + writes)**: `ai`
- **Prod schema (writes)**: `ai_prod`

Always check `databricks auth profiles | grep fevm` before running CLI commands.

## Deploy workflow

```bash
# Deploy bundle resources
databricks bundle deploy -t dev --profile=fevm

# Run the pipeline job (parse PDFs + deploy agent + extract fields)
databricks bundle run extraction_job -t dev --profile=fevm

# Run the review app
databricks bundle run review_app -t dev --profile=fevm
```

For production, replace `-t dev` with `-t prod`.

## Job task graph

```
parse_pdfs ──┐
             ├──> extract_fields
deploy_agent─┘
```

- `parse_pdfs` runs `src/pipelines/parse_pdfs/parse_pdfs_notebook.py` with `docling_env`
- `deploy_agent` runs `src/agents/extractor/driver.py` with `agent_env`
- `extract_fields` runs the `extract_pipeline` DLT pipeline

Both `parse_pdfs` and `deploy_agent` run in parallel; `extract_fields` waits for both.

## Key files to know

| File | Purpose | Notes |
|---|---|---|
| `databricks.yml` | Bundle config, variables, dev/prod targets | Change defaults here |
| `resources/job.yml` | Job task graph and environments | Edit when adding/changing tasks |
| `resources/extract_pipeline.yml` | DLT extract pipeline | Uses `ai_query` against model serving endpoint |
| `resources/app.yml` | Databricks App definition | Points to repo root |
| `src/pipelines/parse_pdfs/parse_pdfs_notebook.py` | PDF OCR/parsing | Incremental; Docling primary, `ai_parse_document` fallback |
| `src/agents/extractor/agent.py` | DSPy extraction agent | MLflow pyfunc wrapper |
| `src/agents/extractor/driver.py` | Agent log/register/deploy | Runs as a job task |
| `src/pipelines/extract_fields/transformations/extract_fields.py` | DLT field extraction | Calls `ai_query(endpoint_name, ...)` |
| `app.py` | Streamlit review app | Reads `extracted_content`, writes `reviewed_records` |
| `config.py` | Runtime config for the app | Overridable via env vars |

## Critical gotchas

### Docling version pinning
**Always use `docling==2.37.0`** — both in `%pip install` in the notebook and in `resources/job.yml` `docling_env` dependencies. Version 2.38.0+ introduces an `asr_pipeline` import that pulls in `transformers`/`torch` at module load time, which crashes Spark UDF workers.

### torch._dynamo in Spark workers
Even with 2.37.0, `docling-ibm-models` → `transformers` → `torch` import can fail because `torch._dynamo.__init__` calls `default_cache_dir()` which tries to resolve a path unavailable in Spark workers. Fix: set `TORCHINDUCTOR_CACHE_DIR` **inside the UDF body, before any docling import**:
```python
os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", "/tmp/torch_inductor_cache")
```

### Spark lazy evaluation and table existence checks
Never use `try: spark.table(name)` to check if a table exists. `spark.table()` is lazy — it returns a DataFrame without executing, so the exception only surfaces later (outside the try block). Use:
```python
if spark.catalog.tableExists(dest_table):
```

### Job environments vs %pip install
When a notebook task has an `environment_key` in `job.yml`, Databricks Serverless enforces immutable package constraints. `%pip install` at the top of the notebook is **not needed** (and can fail). All dependencies go in the environment spec under `resources/job.yml`. See `docling_env` and `agent_env` for examples.

### agents.deploy() is deprecated
`databricks_agents.deploy()` from the `databricks-agents` SDK tries to enable legacy inference tables, which have been removed. Use `WorkspaceClient` + `serving.ServedEntityInput` directly (as in `driver.py`).

### parse_pdfs is incremental
The notebook skips files already present in `raw_parsed_content`. On first run (or full reload) the table does not exist — the `spark.catalog.tableExists()` branch handles this correctly.

## Debugging a failed job run

1. Get the run ID from the CLI output or Databricks UI.
2. Export notebook output:
   ```bash
   curl -H "Authorization: Bearer $TOKEN" \
     "https://<host>/api/2.0/jobs/runs/export?run_id=<id>&views_to_export=CODE" \
     | python3 -c "import sys,json,base64,urllib.parse; d=json.load(sys.stdin); [print(urllib.parse.unquote(base64.b64decode(v['content']).decode())) for v in d['views']]"
   ```
3. The output is JSON with `content` fields (base64 → URL-decoded cell outputs). Look for `PARSE_ERROR:` or Python tracebacks.

## Adding a new pipeline step

1. Create the transformation file under `src/pipelines/<step>/`.
2. If it's a DLT pipeline, add a new `resources/<step>_pipeline.yml`.
3. Add a task to `resources/job.yml` with appropriate `depends_on` and `environment_key`.
4. Add the environment spec to `resources/job.yml` if new packages are required.
5. Update `databricks.yml` variables if the step needs configurable params.
6. Update this file and `README.md`.

## Modifying the extraction agent

The agent is a DSPy `ChainOfThought` module wrapped as an MLflow pyfunc model:
- **Schema**: `src/agents/extractor/agent.py` — defines `FinancialExtraction` DSPy signature and `ExtractionAgent` pyfunc class.
- **Deployment**: `src/agents/extractor/driver.py` — logs, registers to UC, creates/updates the Model Serving endpoint.
- **Endpoint name**: controlled by `endpoint_name` variable in `databricks.yml`.
- **DLT pipeline call**: `src/pipelines/extract_fields/transformations/extract_fields.py` uses `ai_query(spark.conf.get("endpoint_name"), ...)`.

After changing `agent.py`, re-run the job (or just `deploy_agent` task) to push a new version.

## Evaluation

Run `src/validation/evaluate_extraction.py` as a notebook to compare `extracted_content` against the Excel ground truth at `/Volumes/.../techfin_raw_files/ground_truth.xlsx`. Tolerance is 1% relative difference. Statuses: `exact`, `close`, `zero_both`, `wrong`, `missing_ex`, `missing_gt`.
