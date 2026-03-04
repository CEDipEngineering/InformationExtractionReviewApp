# Databricks notebook source

# COMMAND ----------

import io

import dlt
import pandas as pd
from pyspark.sql.functions import col, current_timestamp, pandas_udf
from pyspark.sql.types import StringType

PDF_FOLDER = spark.conf.get("pdf_folder_path")


# ---------------------------------------------------------------------------
# Pandas UDF: binary PDF bytes → markdown string via docling
# ---------------------------------------------------------------------------
@pandas_udf(StringType())
def docling_parse_udf(content_series: pd.Series) -> pd.Series:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.document import DocumentStream
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions()
    opts.do_ocr = True
    opts.ocr_options = RapidOcrOptions(force_full_page_ocr=True)

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )

    results = []
    for raw_bytes in content_series:
        try:
            stream = DocumentStream(name="doc.pdf", stream=io.BytesIO(raw_bytes))
            md = converter.convert(stream).document.export_to_markdown()
        except Exception as e:
            md = f"PARSE_ERROR: {e}"
        results.append(md)
    return pd.Series(results)


# COMMAND ----------

# ---------------------------------------------------------------------------
# Step 1: Ingest raw binary content, one row per file
# ---------------------------------------------------------------------------
@dlt.table(
    name="raw_parse_output",
    comment="Raw binary PDF content from UC Volume, one row per file",
)
def raw_parse_output():
    return (
        spark.readStream
        .format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .load(PDF_FOLDER)
        .filter(col("path").rlike(r"(?i)\.(pdf|jpg|jpeg|png|docx?)$"))
        .select(
            col("path"),
            col("content"),
            current_timestamp().alias("ingested_at"),
        )
    )


# ---------------------------------------------------------------------------
# Step 2: Apply docling UDF to convert bytes → markdown
# ---------------------------------------------------------------------------
@dlt.table(
    name="raw_parsed_content",
    comment="Markdown text extracted from financial PDFs via docling (RapidOCR), consumed by extract_pipeline",
)
@dlt.expect_or_drop("no_parse_error", "raw_parsed NOT LIKE 'PARSE_ERROR:%'")
def raw_parsed_content():
    return (
        dlt.read_stream("raw_parse_output")
        .withColumn("raw_parsed", docling_parse_udf(col("content")))
        .select("path", "raw_parsed", "ingested_at")
    )
