# Databricks notebook source

# COMMAND ----------

%pip install docling
dbutils.library.restartPython()

# COMMAND ----------

import io
import os
from datetime import datetime

from pyspark.sql.types import StringType, StructField, StructType, TimestampType
from pyspark.sql.functions import col

# COMMAND ----------

dbutils.widgets.text("pdf_folder_path", "")
dbutils.widgets.text("catalog", "cedip_fevm_aws_classic_stable_catalog")
dbutils.widgets.text("schema", "ai")
dbutils.widgets.text("write_schema", "ai")

pdf_folder_path = dbutils.widgets.get("pdf_folder_path")
catalog        = dbutils.widgets.get("catalog")
schema         = dbutils.widgets.get("schema")
write_schema   = dbutils.widgets.get("write_schema")
dest_table     = f"{catalog}.{write_schema}.raw_parsed_content"

print(f"Source : {pdf_folder_path}")
print(f"Dest   : {dest_table}")

# COMMAND ----------

SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}

all_paths = {
    os.path.join(pdf_folder_path, fname)
    for fname in os.listdir(pdf_folder_path)
    if os.path.splitext(fname)[1].lower() in SUPPORTED_EXTS
}

# Skip files already written to the destination table
try:
    already_parsed = {
        row.path
        for row in spark.table(dest_table).select("path").collect()
    }
except Exception:
    already_parsed = set()  # destination table doesn't exist yet

file_paths = sorted(all_paths - already_parsed)

print(f"Total files  : {len(all_paths)}")
print(f"Already done : {len(already_parsed)}")
print(f"To process   : {len(file_paths)}")

# COMMAND ----------

from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import DocumentStream
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

opts = PdfPipelineOptions()
opts.do_ocr = True
opts.ocr_options = TesseractCliOcrOptions(force_full_page_ocr=True)
opts.do_table_structure = False  # keep TableFormer disabled to reduce memory

converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
)

# COMMAND ----------

rows = []
for path in file_paths:
    try:
        with open(path, "rb") as f:
            content = f.read()
        stream = DocumentStream(name="doc.pdf", stream=io.BytesIO(content))
        md = converter.convert(stream).document.export_to_markdown()
        print(f"OK  {path}  ({len(md)} chars)")
    except Exception as e:
        md = f"PARSE_ERROR: {e}"
        print(f"ERR {path}  {e}")
    rows.append({"path": path, "raw_parsed": md, "ingested_at": datetime.now()})

print(f"\nProcessed {len(rows)} files")

# COMMAND ----------

output_schema = StructType([
    StructField("path",        StringType(),    True),
    StructField("raw_parsed",  StringType(),    True),
    StructField("ingested_at", TimestampType(), True),
])

if rows:
    output_df = spark.createDataFrame(rows, schema=output_schema)
    (
        output_df
        .filter(~col("raw_parsed").startswith("PARSE_ERROR:"))
        .write.format("delta")
        .mode("append")
        .saveAsTable(dest_table)
    )
    print(f"Written to {dest_table}")
else:
    print("Nothing new to write — table is already up to date.")
