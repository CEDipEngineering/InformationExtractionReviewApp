import io
import os

import pandas as pd
import streamlit as st
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

import config


@st.cache_resource
def get_workspace_client() -> WorkspaceClient:
    # Databricks Apps sets DATABRICKS_CLIENT_ID automatically; when present the
    # SDK picks up all credentials from the environment without extra config.
    if os.environ.get("DATABRICKS_CLIENT_ID"):
        return WorkspaceClient()
    return WorkspaceClient(profile=config.DATABRICKS_CONFIG_PROFILE)


def _execute(client: WorkspaceClient, statement: str, parameters: list | None = None) -> None:
    """Run a SQL statement and raise on failure."""
    kwargs = dict(warehouse_id=config.SQL_WAREHOUSE_ID, statement=statement, wait_timeout="30s")
    if parameters:
        kwargs["parameters"] = parameters
    response = client.statement_execution.execute_statement(**kwargs)
    if response.status.state != StatementState.SUCCEEDED:
        error = response.status.error
        raise RuntimeError(
            f"SQL failed ({response.status.state}): {error.message if error else 'unknown error'}"
        )


@st.cache_data(ttl=300)
def load_table(_client: WorkspaceClient, warehouse_id: str) -> pd.DataFrame:
    query = (
        f"SELECT {config.COL_PDF_PATH}, {config.COL_LABELS}, {config.COL_RAW_CONTENT} "
        f"FROM {config.TABLE_NAME}"
    )
    response = _client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=query,
        wait_timeout="30s",
    )

    if response.status.state != StatementState.SUCCEEDED:
        error = response.status.error
        raise RuntimeError(
            f"Query failed ({response.status.state}): {error.message if error else 'unknown error'}"
        )

    columns = [col.name for col in response.manifest.schema.columns]
    rows = [list(row) for row in response.result.data_array] if response.result.data_array else []
    return pd.DataFrame(rows, columns=columns)


@st.cache_data
def fetch_pdf_bytes(_client: WorkspaceClient, volume_path: str) -> bytes:
    response = _client.files.download(volume_path)
    return response.contents.read()


def ensure_dest_table(client: WorkspaceClient) -> None:
    """Create the destination feedback table if it does not already exist."""
    _execute(
        client,
        f"""
        CREATE TABLE IF NOT EXISTS {config.DEST_TABLE_NAME} (
            {config.COL_PDF_PATH} STRING,
            {config.COL_LABELS}   STRING,
            change_author         STRING,
            saved_at              TIMESTAMP
        )
        """,
    )


def save_record(
    client: WorkspaceClient,
    path_value: str,
    labels_value: str,
    change_author: str,
) -> None:
    """Append a reviewed record to the destination table with metadata."""
    _execute(
        client,
        f"""
        INSERT INTO {config.DEST_TABLE_NAME}
            ({config.COL_PDF_PATH}, {config.COL_LABELS}, change_author, saved_at)
        VALUES
            (:path_val, :labels_val, :author_val, current_timestamp())
        """,
        parameters=[
            StatementParameterListItem(name="path_val",   value=path_value),
            StatementParameterListItem(name="labels_val", value=labels_value),
            StatementParameterListItem(name="author_val", value=change_author),
        ],
    )
