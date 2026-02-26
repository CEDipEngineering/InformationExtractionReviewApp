# Databricks notebook source
# =============================================================================
# Validate Pipeline Output Against Excel Reference
# =============================================================================
# This notebook compares the raw parsed content produced by the parse pipeline
# against the ground-truth data stored in the Excel reference file.
#
# Usage:
#   1. Import this file as a Databricks notebook (File → Import → Python).
#   2. Attach to any cluster that can reach Unity Catalog.
#   3. Run the "Discovery" cells first to see available tab names and PDF paths.
#   4. Fill in the TAB_TO_PDF mapping below.
#   5. Run the "Comparison" cells to see the side-by-side view.
# =============================================================================

# COMMAND ----------

%pip install openpyxl

# COMMAND ----------

# Hard-coded paths — not parametrised (demo only)
EXCEL_PATH = "/Volumes/cedip_fevm_aws_classic_stable_catalog/ai/techfin_raw_files/ground_truth.xlsx"

SOURCE_TABLE = "cedip_fevm_aws_classic_stable_catalog.ai.raw_parsed_content"

# COMMAND ----------

# =============================================================================
# STEP 1 — Manual mapping: Excel tab name → full PDF path in the volume.
# Run the Discovery cells below first to populate this dict.
# =============================================================================

BASE = "dbfs:/Volumes/cedip_fevm_aws_classic_stable_catalog/ai/techfin_raw_files/input_files/"

TAB_TO_PDF: dict[str, str | None] = {
    # Confirmed matches (sheet name → PDF path in input_files/)
    " AESA AUTOMOLAS": BASE + "AESA AUTOMOLAS EQUIPAMENTOS LTDA balt 06 25.pdf",
    "CUSTOM PAPER":    BASE + "CUSTOM PAPER COMERCIO E SERVICOS DE INFORMATICA LTDA BALT 09 25.pdf",
    "Fazenda Iowa":    BASE + "FAZENDA IOWA LTDA BP 24 COMP 23.pdf",
    # No matching PDF found in input_files/ for the tabs below:
    "TURIM FERT BELTRAO ":          None,
    "TURIM FERT LTDA":              None,
    "TURIM INSUMOS E CEREAIS ":     None,
    "CAEDU COMERCIO":               None,
    "SJC BIOENERGIA (CARGILL)":     None,
    "COMPANHIA SIDERURGICA NACIONAL": None,
    "BR CONECTA LTDA":              None,
}

# COMMAND ----------

# =============================================================================
# DISCOVERY — List all Excel tab names
# =============================================================================

import pandas as pd

xl = pd.ExcelFile(EXCEL_PATH)
print("Excel tabs found:")
for name in xl.sheet_names:
    print(f"  {name!r}")

# COMMAND ----------

# =============================================================================
# DISCOVERY — List all PDF paths in the parsed content table
# =============================================================================

pdf_paths_df = spark.sql(f"SELECT path FROM {SOURCE_TABLE} ORDER BY path")
print("PDF paths in parsed content table:")
for row in pdf_paths_df.collect():
    print(f"  {row['path']!r}")

# COMMAND ----------

# =============================================================================
# COMPARISON — Side-by-side view for each mapped entry
# =============================================================================

from IPython.display import HTML, display

sheets: dict[str, pd.DataFrame] = pd.read_excel(EXCEL_PATH, sheet_name=None)

parsed_rows = {
    row["path"]: row["raw_parsed"]
    for row in spark.sql(f"SELECT path, raw_parsed FROM {SOURCE_TABLE}").collect()
}

mapped = {tab: pdf for tab, pdf in TAB_TO_PDF.items() if pdf is not None}

if not mapped:
    print("TAB_TO_PDF is empty or has no non-None entries. Fill it in above and re-run.")
else:
    for tab_name, pdf_path in mapped.items():
        reference_df = sheets.get(tab_name)
        parsed_text = parsed_rows.get(pdf_path, "(not found in parsed content table)")

        ref_html = (
            reference_df.to_html(index=False, border=1, classes="ref-table")
            if reference_df is not None
            else "<p><em>Tab not found in Excel</em></p>"
        )

        html = f"""
        <style>
          .comparison {{ display: flex; gap: 2em; font-family: monospace; font-size: 12px; }}
          .panel {{ flex: 1; overflow: auto; max-height: 600px; border: 1px solid #ccc; padding: 8px; }}
          .panel h3 {{ margin-top: 0; }}
          .ref-table {{ border-collapse: collapse; width: 100%; }}
          .ref-table th, .ref-table td {{ border: 1px solid #999; padding: 4px 8px; }}
          .ref-table th {{ background: #eee; }}
          pre {{ white-space: pre-wrap; word-break: break-word; }}
        </style>
        <h2>📄 {tab_name}</h2>
        <p><small>PDF: {pdf_path}</small></p>
        <div class="comparison">
          <div class="panel">
            <h3>Excel Reference</h3>
            {ref_html}
          </div>
          <div class="panel">
            <h3>Parsed Content (ai_parse_document)</h3>
            <pre>{parsed_text}</pre>
          </div>
        </div>
        <hr/>
        """
        display(HTML(html))
