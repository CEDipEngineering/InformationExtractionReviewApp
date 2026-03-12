# Databricks notebook source
# =============================================================================
# Extraction Agent — Log, Register, Deploy
# =============================================================================
# Logs the TechFinExtractorAgent pyfunc model to MLflow, registers it to
# Unity Catalog, and deploys/updates a serverless Model Serving endpoint.
#
# Parameters (injected via DABs job):
#   catalog       — Unity Catalog catalog
#   schema        — Schema for model registration
#   endpoint_name — Serving endpoint name
#   tag_project   — Project tag
#   tag_env       — Environment tag
# =============================================================================

# COMMAND ----------

import pandas as pd
import mlflow
from mlflow.models import infer_signature
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import serving

# COMMAND ----------

dbutils.widgets.text("catalog", "cedip_fevm_aws_classic_stable_catalog")
dbutils.widgets.text("schema", "ai")
dbutils.widgets.text("endpoint_name", "extraction-agent-endpoint")
dbutils.widgets.text("tag_project", "techfin-ocr")
dbutils.widgets.text("tag_env", "dev")

CATALOG       = dbutils.widgets.get("catalog")
SCHEMA        = dbutils.widgets.get("schema")
ENDPOINT_NAME = dbutils.widgets.get("endpoint_name")
TAG_PROJECT   = dbutils.widgets.get("tag_project")
TAG_ENV       = dbutils.widgets.get("tag_env")

MODEL_NAME    = "techfin_ocr_v4"
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

# Paths relative to this notebook's directory
AGENT_FILE  = "agent.py"
SCHEMA_FILE = "output_schema.json"

mlflow.set_registry_uri("databricks-uc")

_user = (
    dbutils.notebook.entry_point
    .getDbutils().notebook().getContext()
    .userName().get()
)
mlflow.set_experiment(f"/Users/{_user}/techfin_ocr_agent")

print(f"Model      : {UC_MODEL_NAME}")
print(f"Endpoint   : {ENDPOINT_NAME}")

# COMMAND ----------
# MAGIC %md ## 1. Log the model

# COMMAND ----------

input_example = pd.DataFrame(
    {"text": ["BALANÇO PATRIMONIAL — EMPRESA EXEMPLO LTDA\nCNPJ: 00.000.000/0001-00\nPeríodo: 31/12/2024\nAtivo Total: 1.000\n"]}
)
output_example = pd.DataFrame(
    {"response": ["[{\"tipo_entidade\": \"CONSOLIDADO\"}]"]}
)

signature = infer_signature(input_example, output_example)

with mlflow.start_run(run_name=f"techfin-ocr-{TAG_ENV}"):
    logged = mlflow.pyfunc.log_model(
        artifact_path="agent",
        python_model=AGENT_FILE,
        artifacts={"output_schema": SCHEMA_FILE},
        input_example=input_example,
        signature=signature,
        pip_requirements=["openai>=1.0.0", "mlflow>=2.10.0", "databricks-sdk>=0.20.0"],
    )

print(f"Logged model URI : {logged.model_uri}")
print(f"MLflow run ID    : {logged.run_id}")

# COMMAND ----------
# MAGIC %md ## 2. Register to Unity Catalog

# COMMAND ----------

registered = mlflow.register_model(
    model_uri=logged.model_uri,
    name=UC_MODEL_NAME,
)
print(f"Registered version: {registered.version}")

# COMMAND ----------
# MAGIC %md ## 3. Deploy as a serverless Model Serving endpoint

# COMMAND ----------

w = WorkspaceClient()

served_entity = serving.ServedEntityInput(
    entity_name=UC_MODEL_NAME,
    entity_version=str(registered.version),
    workload_size="Small",
    scale_to_zero_enabled=True,
)
config = serving.EndpointCoreConfigInput(name=ENDPOINT_NAME, served_entities=[served_entity])
endpoint_tags = [
    serving.EndpointTag(key="project", value=TAG_PROJECT),
    serving.EndpointTag(key="env",     value=TAG_ENV),
]

from databricks.sdk.errors import NotFound

try:
    w.serving_endpoints.get(ENDPOINT_NAME)
    endpoint_exists = True
except NotFound:
    endpoint_exists = False

if endpoint_exists:
    w.serving_endpoints.update_config(
        name=ENDPOINT_NAME,
        served_entities=[served_entity],
    ).result()
    print(f"Updated endpoint: {ENDPOINT_NAME}")
else:
    w.serving_endpoints.create(
        name=ENDPOINT_NAME, config=config, tags=endpoint_tags
    ).result()
    print(f"Created endpoint: {ENDPOINT_NAME}")

print()
print("=" * 60)
print(f"  Endpoint name : {ENDPOINT_NAME}")
print("=" * 60)
