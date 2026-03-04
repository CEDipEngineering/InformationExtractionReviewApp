# Databricks notebook source
# =============================================================================
# Extract Financial Fields Pipeline
# =============================================================================
# Reads raw parsed document text from raw_parsed_content and calls the
# model serving endpoint (via ai_query) to produce structured JSON per document.
#
# Configuration (injected from resources/extract_pipeline.yml):
#   endpoint_name — Model serving endpoint name (LangChain/DSPy agent or Agent Bricks)
#   source_table  — Fully-qualified parse pipeline output table
#                   (resolved at deploy time to catalog.schema.raw_parsed_content)
# =============================================================================

# COMMAND ----------

import dlt
from pyspark.sql.functions import col, current_timestamp, expr

endpoint_name = spark.conf.get("endpoint_name")
source_table  = spark.conf.get("source_table")


@dlt.table(
    name="extracted_content",
    comment="Structured financial data extracted via ai_query, one row per document",
)
def extracted_content():
    return (
        spark.table(source_table)
        .filter(col("raw_parsed").isNotNull())
        .withColumn(
            "response",
            expr(f"ai_query('{endpoint_name}', raw_parsed, failOnError => false)"),
        )
        .select(
            col("path"),
            col("raw_parsed"),
            col("response.result").alias("extracted"),
            col("response.errorMessage").alias("error"),
            current_timestamp().alias("extracted_at"),
        )
    )
