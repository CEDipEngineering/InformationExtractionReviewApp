# Databricks notebook source
# =============================================================================
# TechFin OCR — Process Extraction Results
# =============================================================================
# Reads the DLT-produced extracted_content table, parses the JSON array
# returned by the agent, and writes individual rows to ocr_results in the
# format expected by the review app.
#
# Also ensures the ocr_corrections table exists.
#
# Parameters (injected via DABs job):
#   catalog      — Unity Catalog catalog
#   write_schema — Schema for output tables
# =============================================================================

# COMMAND ----------

import json
from pyspark.sql.functions import col, current_timestamp, regexp_extract

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("write_schema", "")

catalog      = dbutils.widgets.get("catalog")
write_schema = dbutils.widgets.get("write_schema")

extracted_table  = f"{catalog}.{write_schema}.extracted_content"
results_table    = f"{catalog}.{write_schema}.ocr_results"
corrections_table = f"{catalog}.{write_schema}.ocr_corrections"

print(f"Source : {extracted_table}")
print(f"Dest   : {results_table}")

# COMMAND ----------

# MAGIC %md ## 1. Ensure target tables exist

# COMMAND ----------

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {results_table} (
        document_name STRING,
        tipo_entidade STRING,
        periodo STRING,
        extracted_json STRING,
        razao_social STRING,
        cnpj STRING,
        ativo_total DOUBLE,
        lucro_liquido DOUBLE,
        processed_at TIMESTAMP
    )
    USING DELTA
""")

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {corrections_table} (
        document_name STRING,
        campo STRING,
        valor_extraido STRING,
        valor_correto STRING,
        comentario STRING,
        criado_em TIMESTAMP
    )
    USING DELTA
""")

print("Target tables ready.")

# COMMAND ----------

# MAGIC %md ## 2. Read extracted content and identify new rows

# COMMAND ----------

extracted_df = spark.table(extracted_table).filter(col("extracted").isNotNull())

# Show sample for debugging
extracted_df.select("path", "extracted").show(2, truncate=100)

if spark.catalog.tableExists(results_table) and spark.table(results_table).count() > 0:
    # Only process documents not yet in results
    existing_docs = spark.table(results_table).select("document_name").distinct()
    new_extracted = (
        extracted_df
        .withColumn("document_name", regexp_extract(col("path"), r"([^/]+)$", 1))
        .join(existing_docs, on="document_name", how="left_anti")
    )
else:
    new_extracted = extracted_df.withColumn(
        "document_name", regexp_extract(col("path"), r"([^/]+)$", 1)
    )

rows_to_process = new_extracted.count()
print(f"New documents to process: {rows_to_process}")

if rows_to_process == 0:
    print("Nothing new to process.")
    dbutils.notebook.exit("no_new_results")

# COMMAND ----------

# MAGIC %md ## 3. Parse JSON and explode into individual rows

# COMMAND ----------

def get_nested(d, path):
    """Safely navigate a nested dict by dot-separated path."""
    for k in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


rows = new_extracted.select("document_name", "extracted").collect()
output_rows = []

for row in rows:
    doc_name = row["document_name"]
    raw_json = row["extracted"]

    try:
        parsed = json.loads(raw_json)
        # ai_query with failOnError=>false wraps output: {"result": "...", "errorMessage": null}
        if isinstance(parsed, dict) and "result" in parsed:
            if parsed.get("errorMessage"):
                print(f"  ✗ ai_query error for {doc_name}: {str(parsed['errorMessage'])[:200]}")
                continue
            inner = parsed["result"]
            if inner is None:
                print(f"  ✗ Null result for {doc_name}")
                continue
            if isinstance(inner, str):
                parsed = json.loads(inner)
            else:
                parsed = inner
        results = parsed if isinstance(parsed, list) else [parsed]
    except (json.JSONDecodeError, TypeError) as e:
        print(f"  ✗ Failed to parse JSON for {doc_name}: {e}")
        continue

    for result in results:
        if isinstance(result, dict) and result.get("error") == "parse_failed":
            print(f"  ✗ Agent returned parse error for {doc_name}")
            continue

        def safe_float(val):
            try:
                return float(val) if val else 0.0
            except (ValueError, TypeError):
                return 0.0

        output_rows.append({
            "document_name": doc_name,
            "tipo_entidade": get_nested(result, "tipo_entidade") or "",
            "periodo": get_nested(result, "identificacao.periodo") or "",
            "extracted_json": json.dumps(result, ensure_ascii=False),
            "razao_social": get_nested(result, "razao_social") or "",
            "cnpj": get_nested(result, "cnpj") or "",
            "ativo_total": safe_float(get_nested(result, "ativo_total")),
            "lucro_liquido": safe_float(get_nested(result, "dre.lucro_liquido")),
        })

print(f"Total result rows: {len(output_rows)}")

# COMMAND ----------

# MAGIC %md ## 4. Write to ocr_results via MERGE

# COMMAND ----------

if output_rows:
    from pyspark.sql.types import (
        DoubleType, StringType, StructField, StructType,
    )

    schema = StructType([
        StructField("document_name", StringType()),
        StructField("tipo_entidade", StringType()),
        StructField("periodo", StringType()),
        StructField("extracted_json", StringType()),
        StructField("razao_social", StringType()),
        StructField("cnpj", StringType()),
        StructField("ativo_total", DoubleType()),
        StructField("lucro_liquido", DoubleType()),
    ])

    new_df = (
        spark.createDataFrame(output_rows, schema=schema)
        .withColumn("processed_at", current_timestamp())
    )

    new_df.createOrReplaceTempView("new_results")

    spark.sql(f"""
        MERGE INTO {results_table} AS t
        USING new_results AS s
          ON  t.document_name = s.document_name
          AND t.tipo_entidade = s.tipo_entidade
          AND t.periodo       = s.periodo
        WHEN MATCHED THEN UPDATE SET
            extracted_json = s.extracted_json,
            razao_social   = s.razao_social,
            cnpj           = s.cnpj,
            ativo_total    = s.ativo_total,
            lucro_liquido  = s.lucro_liquido,
            processed_at   = s.processed_at
        WHEN NOT MATCHED THEN INSERT *
    """)

    print(f"Merged {len(output_rows)} rows into {results_table}")
else:
    print("No valid results to write.")

# COMMAND ----------

# MAGIC %md ## 5. Summary

# COMMAND ----------

total_results = spark.table(results_table).count()
total_docs = spark.table(results_table).select("document_name").distinct().count()
print(f"\n{'='*50}")
print(f"Total rows in {results_table}: {total_results}")
print(f"Distinct documents: {total_docs}")
print(f"New rows processed this run: {len(output_rows)}")
