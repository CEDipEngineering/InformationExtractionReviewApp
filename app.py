import json
import os

import streamlit as st
from streamlit_ace import st_ace
from streamlit_pdf_viewer import pdf_viewer

from databricks_utils import fetch_pdf_bytes, get_workspace_client, load_table


def _strip_code_fence(s: str) -> str:
    """Remove leading/trailing triple-backtick fences from an LLM JSON output."""
    s = s.strip()
    for prefix in ("```json", "```"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()

WAREHOUSE_ID = os.environ.get("SQL_WAREHOUSE_ID", "c741aaf0c2ad0829")

st.set_page_config(
    page_title="Information Extraction Review",
    layout="wide",
)

st.title("Information Extraction Review")

# --- Auto-load table on startup ---
client = get_workspace_client()

if "df" not in st.session_state:
    with st.spinner("Loading records..."):
        try:
            st.session_state["df"] = load_table(client, WAREHOUSE_ID)
            st.session_state["edits"] = {}
        except Exception as e:
            st.error(f"Failed to load table: {e}")
            st.stop()

df = st.session_state["df"]
edits: dict = st.session_state.setdefault("edits", {})

# --- Record selector ---
paths = df["path"].tolist()
selected_path = st.selectbox("Select a record", paths, format_func=lambda p: p.split("/")[-1])
row = df[df["path"] == selected_path].iloc[0]

# Persist edits for the previously selected record before switching
if "current_path" in st.session_state and st.session_state["current_path"] != selected_path:
    prev_path = st.session_state["current_path"]
    if "json_editor" in st.session_state:
        edits[prev_path] = st.session_state["json_editor"]

st.session_state["current_path"] = selected_path

# Determine the JSON to show: prefer saved edit, fall back to table value
raw_labels = row["labels"]
if selected_path in edits:
    editor_value = edits[selected_path]
else:
    try:
        cleaned = _strip_code_fence(raw_labels)
        editor_value = json.dumps(json.loads(cleaned), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        editor_value = raw_labels or ""

# --- Two-column layout ---
col_pdf, col_json = st.columns(2)

with col_pdf:
    st.subheader("Source PDF")
    with st.spinner("Loading PDF..."):
        try:
            pdf_bytes = fetch_pdf_bytes(client, selected_path)
        except Exception as e:
            st.error(f"Could not load PDF: {e}")
            pdf_bytes = None

    if pdf_bytes is not None:
        pdf_viewer(pdf_bytes, height=700)

with col_json:
    st.subheader("Extraction Output")
    tab_json, tab_raw = st.tabs(["JSON Editor", "Raw Parse"])

    with tab_json:
        edited = st_ace(
            value=editor_value,
            language="json",
            theme="github",
            height=620,
            key="json_editor",
            show_gutter=True,
            show_print_margin=False,
            wrap=False,
            auto_update=True,
        )

        if st.button("Validate JSON"):
            try:
                json.loads(edited)
                edits[selected_path] = edited
                st.success("Valid JSON.")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")

    with tab_raw:
        st.text(row.get("raw_parsed") or "(empty)")
