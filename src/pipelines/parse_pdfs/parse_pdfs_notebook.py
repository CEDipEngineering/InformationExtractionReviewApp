# Databricks notebook source

# COMMAND ----------

%pip install "docling==2.37.0"
dbutils.library.restartPython()

# COMMAND ----------

import io
import pandas as pd

from pyspark.sql.types import StringType, StructType, StructField
from pyspark.sql.functions import col, when, to_json, expr, current_timestamp, pandas_udf, regexp_replace

# COMMAND ----------

dbutils.widgets.text("pdf_folder_path", "")
dbutils.widgets.text("catalog", "cedip_fevm_aws_classic_stable_catalog")
dbutils.widgets.text("schema", "ai")
dbutils.widgets.text("write_schema", "ai")

pdf_folder_path = dbutils.widgets.get("pdf_folder_path")
catalog         = dbutils.widgets.get("catalog")
schema          = dbutils.widgets.get("schema")
write_schema    = dbutils.widgets.get("write_schema")
dest_table      = f"{catalog}.{write_schema}.raw_parsed_content"

print(f"Source : {pdf_folder_path}")
print(f"Dest   : {dest_table}")

# COMMAND ----------

SUPPORTED_EXTS_PATTERN = r"(?i)\.(pdf|jpg|jpeg|png|docx?)$"

# Read all supported files from the Volume as binary.
# Normalize path: strip the "dbfs:" prefix that binaryFile format adds,
# so paths stay consistent with any existing "/Volumes/..." entries in dest_table.
all_files_df = (
    spark.read.format("binaryFile")
    .load(pdf_folder_path)
    .filter(col("path").rlike(SUPPORTED_EXTS_PATTERN))
    .withColumn("path", regexp_replace(col("path"), r"^dbfs:", ""))
    .select("path", "content")
)

# Skip files that were already successfully parsed
if spark.catalog.tableExists(dest_table):
    already_parsed_df = spark.table(dest_table).select("path")
    files_to_process_df = all_files_df.join(already_parsed_df, on="path", how="left_anti")
else:
    files_to_process_df = all_files_df  # dest table doesn't exist yet

total      = all_files_df.count()
to_process = files_to_process_df.count()

print(f"Total files  : {total}")
print(f"Already done : {total - to_process}")
print(f"To process   : {to_process}")

# COMMAND ----------

# Step 1: Docling + Tesseract via Pandas UDF (primary).
# Runs distributed across workers; Tesseract is a pre-installed system binary
# on Databricks nodes so no extra ML model downloads are needed.
@pandas_udf(StringType())
def docling_tesseract_udf(content_series: pd.Series) -> pd.Series:
    import io
    import os
    # torch._dynamo fails to resolve the cache directory in Spark worker environments.
    # Pre-setting this env var bypasses the default_cache_dir() call at torch import time.
    os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", "/tmp/torch_inductor_cache")
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.datamodel.document import DocumentStream

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.ocr_options = TesseractCliOcrOptions(force_full_page_ocr=True)
    opts.do_table_structure = False

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )

    results = []
    for raw_bytes in content_series:
        try:
            stream = DocumentStream(name="doc.pdf", stream=io.BytesIO(bytes(raw_bytes)))
            md = converter.convert(stream).document.export_to_markdown()
        except Exception as e:
            md = f"PARSE_ERROR: {e}"
        results.append(md)
    return pd.Series(results)

num_partitions = min(to_process, 16) if to_process > 0 else 1
docling_attempted_df = (
    files_to_process_df
    .repartition(num_partitions)
    .withColumn("raw_parsed", docling_tesseract_udf(col("content")))
    .select("path", "content", "raw_parsed")
)

docling_success_df = docling_attempted_df.filter(~col("raw_parsed").startswith("PARSE_ERROR:")).select("path", "raw_parsed")
docling_failed_df  = docling_attempted_df.filter(col("raw_parsed").startswith("PARSE_ERROR:")).select("path", "content")

docling_success_count = docling_success_df.count()
docling_failed_count  = docling_failed_df.count()

print(f"Docling+Tesseract succeeded : {docling_success_count}")
print(f"Docling+Tesseract failed    : {docling_failed_count}")

# COMMAND ----------

# Step 2: ai_parse_document fallback (Databricks built-in, serverless-friendly).
# failOnError => false returns a result with an error field instead of throwing.
# TRY() is an additional safety net in case the function still raises.
if docling_failed_count > 0:
    ai_attempted_df = (
        docling_failed_df
        .withColumn(
            "_ai_result",
            expr("TRY(ai_parse_document(content, map('failOnError', 'false')))")
        )
        .withColumn(
            "raw_parsed",
            when(col("_ai_result").isNotNull(), to_json(col("_ai_result"))).otherwise(None)
        )
        .drop("_ai_result")
        .select("path", "raw_parsed")
    )
else:
    ai_attempted_df = spark.createDataFrame(
        [],
        schema=StructType([
            StructField("path",       StringType(), True),
            StructField("raw_parsed", StringType(), True),
        ])
    )

ai_success_count = ai_attempted_df.filter(col("raw_parsed").isNotNull()).count()
ai_failed_count  = ai_attempted_df.filter(col("raw_parsed").isNull()).count()

print(f"ai_parse_document succeeded : {ai_success_count}")
print(f"ai_parse_document failed    : {ai_failed_count}")

# COMMAND ----------

# Combine both result sets, drop nulls, and write incrementally
combined_df = (
    docling_success_df.union(
        ai_attempted_df.filter(col("raw_parsed").isNotNull())
    )
    .withColumn("ingested_at", current_timestamp())
)

rows_to_write = combined_df.count()
print(f"Rows to write: {rows_to_write}")

if rows_to_write > 0:
    (
        combined_df
        .write.format("delta")
        .mode("append")
        .saveAsTable(dest_table)
    )
    print(f"Written to {dest_table}")
else:
    print("Nothing new to write — table is already up to date.")
