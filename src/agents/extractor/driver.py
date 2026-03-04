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

%pip install dspy-ai langchain-databricks databricks-agents "mlflow>=3.0"
dbutils.library.restartPython()

# COMMAND ----------

import mlflow
from databricks import agents

CATALOG       = "cedip_fevm_aws_classic_stable_catalog"
SCHEMA        = "ai"
MODEL_NAME    = "extraction_agent"
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.{MODEL_NAME}"

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
deployment = agents.deploy(
    model_name=UC_MODEL_NAME,
    model_version=registered.version,
    scale_to_zero_enabled=True,
)

print()
print("=" * 60)
print(f"  Endpoint name : {deployment.endpoint_name}")
print("=" * 60)
print()
print("Next steps:")
print(f"  1. Copy the endpoint name above into databricks.yml → endpoint_name")
print(f"  2. Run: databricks bundle deploy -t dev")
print(f"  3. Run: databricks bundle run extract_pipeline -t dev")
