"""
Centralized configuration. All tuneable values are read from environment
variables so the app can be reconfigured without code changes.

Local development  : set values in a .env file (or export them in your shell).
Databricks App     : DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET /
                     DATABRICKS_HOST are injected automatically by the platform;
                     the SDK detects them without any extra configuration here.
"""
import os

# ---------------------------------------------------------------------------
# Databricks auth (local development only)
# When running as a deployed Databricks App, DATABRICKS_CLIENT_ID is set by
# the platform and the SDK authenticates automatically — this value is ignored.
# ---------------------------------------------------------------------------
DATABRICKS_CONFIG_PROFILE: str = os.environ.get("DATABRICKS_CONFIG_PROFILE", "fevm")

# ---------------------------------------------------------------------------
# SQL warehouse
# ---------------------------------------------------------------------------
SQL_WAREHOUSE_ID: str = os.environ.get("SQL_WAREHOUSE_ID", "2c3975c5e258e46b")

# ---------------------------------------------------------------------------
# Source table
# ---------------------------------------------------------------------------
TABLE_NAME: str = os.environ.get("TABLE_NAME", "cedip_fevm_aws_classic_stable_catalog.ai.raw_parsed_content")

# ---------------------------------------------------------------------------
# Destination table (writeback)
# Reviewed/corrected JSON is upserted here, keyed on COL_PDF_PATH.
# ---------------------------------------------------------------------------
DEST_TABLE_NAME: str = os.environ.get("DEST_TABLE_NAME", "cedip_fevm_aws_classic_stable_catalog.ai.reviewed_records")

# Column that holds the path to the PDF file inside a UC Volume
COL_PDF_PATH: str = os.environ.get("COL_PDF_PATH", "path")

# Column that holds the JSON extraction output (may be wrapped in code fences)
COL_LABELS: str = os.environ.get("COL_LABELS", "labels")

# Column that holds the raw text parse of the PDF
COL_RAW_CONTENT: str = os.environ.get("COL_RAW_CONTENT", "raw_parsed")
