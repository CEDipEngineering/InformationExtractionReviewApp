import os
from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))

DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "")
WAREHOUSE_ID = os.environ["WAREHOUSE_ID"]
RESULTS_TABLE = os.environ["RESULTS_TABLE"]
CORRECTIONS_TABLE = os.environ["CORRECTIONS_TABLE"]
PDF_VOLUME_PATH = os.environ["PDF_VOLUME_PATH"]
OCR_ENDPOINT = os.environ["OCR_ENDPOINT"]


def get_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    return WorkspaceClient(profile=os.environ.get("DATABRICKS_PROFILE", "DEFAULT"))
