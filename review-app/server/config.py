import os
from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))

DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "")
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "2c3975c5e258e46b")
RESULTS_TABLE = os.environ.get("RESULTS_TABLE", "cedip_fevm_aws_classic_stable_catalog.ai.ocr_results")
CORRECTIONS_TABLE = os.environ.get("CORRECTIONS_TABLE", "cedip_fevm_aws_classic_stable_catalog.ai.ocr_corrections")
PDF_VOLUME_PATH = os.environ.get("PDF_VOLUME_PATH", "/Volumes/cedip_fevm_aws_classic_stable_catalog/ai/techfin_raw_files/input_files/")
OCR_ENDPOINT = os.environ.get("OCR_ENDPOINT", "extraction-agent-endpoint")


def get_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    return WorkspaceClient(profile=os.environ.get("DATABRICKS_PROFILE", "DEFAULT"))
