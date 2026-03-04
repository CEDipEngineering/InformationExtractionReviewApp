# Databricks notebook source
# =============================================================================
# Docling Smoke Test
# =============================================================================
# Verifies that docling[rapidocr] installs and can process a PDF end-to-end
# on Databricks compute.  Run this before deploying the parse_pipeline.
#
# Checks:
#   1. Package installs without errors
#   2. DocumentConverter initialises with RapidOCR options
#   3. DocumentStream accepts io.BytesIO input
#   4. PDF → markdown produces non-empty output
#   5. In-memory bytes path (as used by the Pandas UDF) works correctly
# =============================================================================

# COMMAND ----------

%pip install "docling[rapidocr]" onnxruntime

# COMMAND ----------

import io
import urllib.request

# ---------------------------------------------------------------------------
# Test 1 — imports
# ---------------------------------------------------------------------------
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import DocumentStream
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

print("✓ All docling imports succeeded")

# COMMAND ----------

# ---------------------------------------------------------------------------
# Test 2 — converter initialisation
# ---------------------------------------------------------------------------
opts = PdfPipelineOptions()
opts.do_ocr = True
opts.ocr_options = RapidOcrOptions(force_full_page_ocr=True)

converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
)
print("✓ DocumentConverter initialised with RapidOCR")

# COMMAND ----------

# ---------------------------------------------------------------------------
# Test 3 — download a small public PDF
# ---------------------------------------------------------------------------
TEST_URL = "https://www.w3.org/WAI/WCAG21/Techniques/pdf/img/table-word.pdf"
local_path, _ = urllib.request.urlretrieve(TEST_URL)
with open(local_path, "rb") as f:
    pdf_bytes = f.read()

print(f"✓ Downloaded test PDF ({len(pdf_bytes):,} bytes)")

# COMMAND ----------

# ---------------------------------------------------------------------------
# Test 4 — file-path conversion (baseline)
# ---------------------------------------------------------------------------
result_from_path = converter.convert(local_path)
md_from_path = result_from_path.document.export_to_markdown()
assert len(md_from_path) > 0, "Empty markdown from file path — docling failed"
print(f"✓ File-path conversion produced {len(md_from_path)} chars of markdown")

# COMMAND ----------

# ---------------------------------------------------------------------------
# Test 5 — in-memory bytes via DocumentStream (matches Pandas UDF pattern)
# ---------------------------------------------------------------------------
stream = DocumentStream(name="doc.pdf", stream=io.BytesIO(pdf_bytes))
result_from_stream = converter.convert(stream)
md_from_stream = result_from_stream.document.export_to_markdown()
assert len(md_from_stream) > 0, "Empty markdown from DocumentStream — docling failed"
print(f"✓ DocumentStream conversion produced {len(md_from_stream)} chars of markdown")

# COMMAND ----------

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("=" * 60)
print("  ALL DOCLING TESTS PASSED")
print("=" * 60)
print()
print("Markdown preview (first 500 chars):")
print(md_from_stream[:500])
