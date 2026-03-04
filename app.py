import json

import streamlit as st
from streamlit_ace import st_ace
from streamlit_pdf_viewer import pdf_viewer

import config
from databricks_utils import (
    ensure_dest_table,
    fetch_pdf_bytes,
    get_workspace_client,
    load_table,
    save_record,
)


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


st.set_page_config(
    page_title="Information Extraction Review",
    layout="wide",
)

st.title("Information Extraction Review")

# --- Auto-load table on startup ---
client = get_workspace_client()

if "dest_table_ready" not in st.session_state:
    with st.spinner("Initializing..."):
        try:
            ensure_dest_table(client)
            st.session_state["dest_table_ready"] = True
        except Exception as e:
            st.error(f"Failed to initialize destination table: {e}")
            st.stop()

if "df" not in st.session_state:
    with st.spinner("Loading records..."):
        try:
            st.session_state["df"] = load_table(client, config.SQL_WAREHOUSE_ID)
            st.session_state["edits"] = {}
        except Exception as e:
            st.error(f"Failed to load table: {e}")
            st.stop()

df = st.session_state["df"]
edits: dict = st.session_state.setdefault("edits", {})

# --- Record selector ---
paths = df[config.COL_PDF_PATH].tolist()
selected_path = st.selectbox("Select a record", paths, format_func=lambda p: p.split("/")[-1])
row = df[df[config.COL_PDF_PATH] == selected_path].iloc[0]

# Persist edits for the previously selected record before switching
if "current_path" in st.session_state and st.session_state["current_path"] != selected_path:
    prev_path = st.session_state["current_path"]
    if "json_editor" in st.session_state:
        edits[prev_path] = st.session_state["json_editor"]

st.session_state["current_path"] = selected_path

# Determine the JSON to show: prefer saved edit, fall back to table value
raw_labels = row[config.COL_LABELS]
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
    tab_json, tab_raw = st.tabs(["JSON Editor", "Intermediate OCR"])

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

        btn_validate, btn_save = st.columns([1, 1])

        with btn_validate:
            if st.button("Validate JSON", use_container_width=True):
                try:
                    json.loads(edited)
                    edits[selected_path] = edited
                    st.success("Valid JSON.")
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")

        with btn_save:
            if st.button("Save", type="primary", use_container_width=True):
                try:
                    json.loads(edited)
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON — fix before saving: {e}")
                else:
                    change_author = (
                        st.context.headers.get("X-Forwarded-Email")
                        or "local_dev_testing"
                    )
                    with st.spinner("Saving..."):
                        try:
                            save_record(client, selected_path, edited, change_author)
                            edits[selected_path] = edited
                            st.success("Saved.")
                        except Exception as e:
                            st.error(f"Save failed: {e}")

    with tab_raw:
        st.text(row.get(config.COL_RAW_CONTENT) or "(empty)")
