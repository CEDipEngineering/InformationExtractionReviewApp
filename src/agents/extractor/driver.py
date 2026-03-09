# Databricks notebook source
# =============================================================================
# Extraction Agent — Log, Register, Deploy
# =============================================================================
# Run this notebook once to:
#   1. Log the ExtractionAgent pyfunc model to an MLflow experiment
#   2. Register it to Unity Catalog
#   3. Deploy it as a serverless Model Serving endpoint
#
# After running, copy the printed endpoint name into databricks.yml → endpoint_name,
# then re-deploy the bundle and run the extract_pipeline.
# =============================================================================

# COMMAND ----------

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import serving

CATALOG        = "cedip_fevm_aws_classic_stable_catalog"
SCHEMA         = "ai"
MODEL_NAME     = "extraction_agent"
UC_MODEL_NAME  = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"
ENDPOINT_NAME  = "extraction-agent-endpoint"

# Path to agent.py relative to this notebook's directory
AGENT_FILE = "agent.py"

mlflow.set_registry_uri("databricks-uc")

# Use the current user's home folder for the experiment
_user = (
    dbutils.notebook.entry_point
    .getDbutils().notebook().getContext()
    .userName().get()
)
mlflow.set_experiment(f"/Users/{_user}/extraction_agent")

# COMMAND ----------
# ---------------------------------------------------------------------------
# Step 1 — Log the model
# ---------------------------------------------------------------------------
input_example = {
    "messages": [
        {
            "role": "user",
            "content": (
                "BALANÇO PATRIMONIAL — EMPRESA EXEMPLO LTDA\n"
                "CNPJ: 00.000.000/0001-00\n"
                "Período: 31/12/2024\n"
                "Ativo Total: 1.000\n"
            ),
        }
    ]
}

with mlflow.start_run(run_name="extraction_agent_v1"):
    logged = mlflow.pyfunc.log_model(
        artifact_path="extraction_agent",
        python_model=AGENT_FILE,
        input_example=input_example,
        pip_requirements=["dspy-ai", "langchain-databricks"],
    )

print(f"Logged model URI : {logged.model_uri}")
print(f"MLflow run ID    : {logged.run_id}")

# COMMAND ----------
# ---------------------------------------------------------------------------
# Step 2 — Register to Unity Catalog
# ---------------------------------------------------------------------------
registered = mlflow.register_model(
    model_uri=logged.model_uri,
    name=UC_MODEL_NAME,
)
print(f"Registered version: {registered.version}")

# COMMAND ----------
# ---------------------------------------------------------------------------
# Step 3 — Deploy as a serverless Model Serving endpoint
# ---------------------------------------------------------------------------
w = WorkspaceClient()

served_entity = serving.ServedEntityInput(
    entity_name=UC_MODEL_NAME,
    entity_version=str(registered.version),
    workload_size="Small",
    scale_to_zero_enabled=True,
)
config = serving.EndpointCoreConfigInput(served_entities=[served_entity])

try:
    w.serving_endpoints.get(ENDPOINT_NAME)
    # Endpoint exists — update to new model version
    w.serving_endpoints.update_config(
        name=ENDPOINT_NAME,
        served_entities=[served_entity],
    ).result()
    print(f"Updated endpoint: {ENDPOINT_NAME}")
except Exception:
    # Endpoint does not exist — create it
    w.serving_endpoints.create(name=ENDPOINT_NAME, config=config).result()
    print(f"Created endpoint: {ENDPOINT_NAME}")

print()
print("=" * 60)
print(f"  Endpoint name : {ENDPOINT_NAME}")
print("=" * 60)
