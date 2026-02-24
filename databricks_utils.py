import os
import io
import pandas as pd
import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

TABLE_NAME = "pedro_zanela.ia.input_ocr_gabarito"


@st.cache_resource
def get_workspace_client() -> WorkspaceClient:
    profile = os.environ.get("DATABRICKS_CONFIG_PROFILE", "e2")
    return WorkspaceClient(profile=profile)


@st.cache_data(ttl=300)
def load_table(_client: WorkspaceClient, warehouse_id: str) -> pd.DataFrame:
    query = f"SELECT path, labels, raw_parsed FROM {TABLE_NAME}"
    response = _client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=query,
        wait_timeout="30s",
    )

    if response.status.state != StatementState.SUCCEEDED:
        error = response.status.error
        raise RuntimeError(f"Query failed ({response.status.state}): {error.message if error else 'unknown error'}")

    columns = [col.name for col in response.manifest.schema.columns]
    rows = [list(row) for row in response.result.data_array] if response.result.data_array else []
    return pd.DataFrame(rows, columns=columns)


@st.cache_data
def fetch_pdf_bytes(_client: WorkspaceClient, volume_path: str) -> bytes:
    response = _client.files.download(volume_path)
    return response.contents.read()
