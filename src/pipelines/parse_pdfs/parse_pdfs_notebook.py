# Databricks notebook source
# =============================================================================
# TechFin OCR — Parse PDFs with ai_parse_document
# =============================================================================
# Reads PDF files from a Unity Catalog Volume, parses them using the built-in
# ai_parse_document function, extracts the text content, and writes the results
# to a Delta table for downstream extraction.
#
# Parameters (injected via DABs job):
#   pdf_volume_path — Full volume path to the PDF folder
#   catalog         — Unity Catalog catalog name
#   schema          — Schema for source reads
#   write_schema    — Schema for output tables
# =============================================================================

# COMMAND ----------

from pyspark.sql.functions import col, concat_ws, current_timestamp, expr, lit, when
from pyspark.sql.functions import regexp_replace, regexp_extract

# COMMAND ----------

dbutils.widgets.text("pdf_volume_path", "/Volumes/cedip_fevm_aws_classic_stable_catalog/ai/techfin_raw_files/input_files/")
dbutils.widgets.text("catalog", "cedip_fevm_aws_classic_stable_catalog")
dbutils.widgets.text("schema", "ai")
dbutils.widgets.text("write_schema", "ai")

pdf_volume_path = dbutils.widgets.get("pdf_volume_path")
catalog         = dbutils.widgets.get("catalog")
schema          = dbutils.widgets.get("schema")
write_schema    = dbutils.widgets.get("write_schema")
dest_table      = f"{catalog}.{write_schema}.raw_parsed_content"

print(f"Source : {pdf_volume_path}")
print(f"Dest   : {dest_table}")

# COMMAND ----------

# MAGIC %md ## 1. Read PDF files from Volume

# COMMAND ----------

# Read all PDF files from the Volume as binary
all_files_df = (
    spark.read.format("binaryFile")
    .option("pathGlobFilter", "*.pdf")
    .option("recursiveFileLookup", "true")
    .load(pdf_volume_path)
    .withColumn("path", regexp_replace(col("path"), r"^dbfs:", ""))
    .select("path", "content")
)

# Skip files that were already successfully parsed
if spark.catalog.tableExists(dest_table):
    already_parsed_df = spark.table(dest_table).select("path")
    files_to_process_df = all_files_df.join(already_parsed_df, on="path", how="left_anti")
else:
    files_to_process_df = all_files_df

total      = all_files_df.count()
to_process = files_to_process_df.count()

print(f"Total files  : {total}")
print(f"Already done : {total - to_process}")
print(f"To process   : {to_process}")

if to_process == 0:
    print("Nothing new to process — table is already up to date.")
    dbutils.notebook.exit("no_new_files")

# COMMAND ----------

# MAGIC %md ## 2. Parse with ai_parse_document

# COMMAND ----------

# ai_parse_document returns a VARIANT with document structure.
# We repartition by file hash to parallelize across workers.
num_partitions = min(to_process, 16)

parsed_df = (
    files_to_process_df
    .repartition(num_partitions, expr("crc32(path) % 8"))
    .withColumn(
        "_ai_result",
        expr("ai_parse_document(content, map('version', '2.0'))")
    )
)

# COMMAND ----------

# MAGIC %md ## 3. Extract text from parsed VARIANT

# COMMAND ----------

# Extract text content from parsed document elements.
# Uses transform() + try_cast for safe access to the VARIANT structure.
text_df = (
    parsed_df
    .withColumn(
        "raw_parsed",
        when(
            col("_ai_result").isNotNull()
            & expr("try_cast(_ai_result:error_status AS STRING)").isNull(),
            concat_ws(
                "\n\n",
                expr("""
                    transform(
                        try_cast(_ai_result:document:elements AS ARRAY<VARIANT>),
                        element -> try_cast(element:content AS STRING)
                    )
                """),
            ),
        ).otherwise(lit(None)),
    )
    .withColumn(
        "error_status",
        expr("try_cast(_ai_result:error_status AS STRING)"),
    )
    .drop("_ai_result", "content")
)

success_count = text_df.filter(col("raw_parsed").isNotNull()).count()
failed_count  = text_df.filter(col("raw_parsed").isNull()).count()

print(f"ai_parse_document succeeded : {success_count}")
print(f"ai_parse_document failed    : {failed_count}")

# COMMAND ----------

# MAGIC %md ## 4. Write results to Delta table

# COMMAND ----------

results_df = (
    text_df
    .filter(col("raw_parsed").isNotNull())
    .withColumn("ingested_at", current_timestamp())
    .select("path", "raw_parsed", "ingested_at")
)

rows_to_write = results_df.count()
print(f"Rows to write: {rows_to_write}")

if rows_to_write > 0:
    (
        results_df
        .write.format("delta")
        .mode("append")
        .saveAsTable(dest_table)
    )
    print(f"Written to {dest_table}")
else:
    print("Nothing new to write.")

# Log errors for debugging
if failed_count > 0:
    print(f"\nFailed files ({failed_count}):")
    failed_files = (
        text_df
        .filter(col("raw_parsed").isNull())
        .select("path", "error_status")
        .collect()
    )
    for row in failed_files:
        print(f"  - {row['path']}: {row['error_status']}")
