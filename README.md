# Information Extraction Review App

Automates structured data extraction from financial PDFs using docling + a DSPy/MLflow agent, then provides a Streamlit app for human review and correction.

## Pipeline

```mermaid
flowchart LR
    A[UC Volume] --> B[parse_pipeline]
    B --> C[raw_parsed_content]
    C --> D[extract_pipeline]
    D --> E[extracted_content]
    E --> F[Review App]
    F --> G[reviewed_records]
    G -->|feedback loop| D
```

| Step | Resource | Output table |
|---|---|---|
| 1. OCR & parse | `parse_pipeline` (docling) | `raw_parsed_content` |
| 2. Field extraction | `extract_pipeline` (ai_query) | `extracted_content` |
| 3. Human review | Streamlit app | `reviewed_records` |
| 4. Feedback loop | — | `reviewed_records` feeds back to improve the extraction agent |

## Deploy

```bash
# 1. Validate and deploy all resources
databricks bundle validate -t dev
databricks bundle deploy -t dev

# 2. Run the parse pipeline
databricks bundle run parse_pipeline -t dev
```

**3. Deploy the extraction agent** — run the `src/agents/extractor/driver.py` notebook on Databricks.
It logs, registers, and deploys the DSPy/MLflow agent as a model serving endpoint.
Copy the printed endpoint name into `databricks.yml` → `endpoint_name`.

```bash
# 4. Re-deploy so the extract_pipeline picks up the updated endpoint_name
databricks bundle deploy -t dev

# 5. Run the extraction pipeline
databricks bundle run extract_pipeline -t dev

# 6. Start the review app
databricks bundle run review_app -t dev
```

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Requires a Databricks CLI profile (`fevm` by default) in `~/.databrickscfg`.

## Configuration

Settings live in [`config.py`](config.py) and are overridable via environment variables.

| Variable | Default |
|---|---|
| `DATABRICKS_CONFIG_PROFILE` | `fevm` |
| `SQL_WAREHOUSE_ID` | `2c3975c5e258e46b` |
| `TABLE_NAME` | `cedip_fevm_aws_classic_stable_catalog.ai.extracted_content` |
| `DEST_TABLE_NAME` | `cedip_fevm_aws_classic_stable_catalog.ai.reviewed_records` |

Bundle variables (`databricks.yml`) control catalog, schema, PDF volume path, warehouse, and agent endpoint name.

## Repository layout

```
├── databricks.yml                          # Bundle: variables, targets (dev/prod)
├── resources/
│   ├── pipeline.yml                        # parse_pipeline definition
│   ├── extract_pipeline.yml                # extract_pipeline definition
│   └── app.yml                             # Databricks App resource
├── src/
│   ├── agents/
│   │   └── extractor/
│   │       ├── agent.py                    # DSPy + MLflow pyfunc extraction agent
│   │       └── driver.py                   # Notebook: log → register → deploy agent
│   ├── pipelines/
│   │   ├── parse_pdfs/transformations/
│   │   │   └── parse_pdfs_docling.py       # docling (RapidOCR) → raw_parsed_content
│   │   └── extract_fields/transformations/
│   │       └── extract_fields.py           # ai_query → extracted_content
│   ├── tests/
│   │   └── test_docling.py                 # Smoke test for docling on Databricks
│   └── validation/
│       ├── evaluate_extraction.py          # Accuracy evaluation vs Excel ground truth
│       └── validate_against_reference.py   # Field-level comparison notebook
├── app.py                                  # Streamlit review app
├── config.py                               # Runtime config (env-var driven)
└── databricks_utils.py                     # SDK helpers (query, save, fetch PDF bytes)
```
