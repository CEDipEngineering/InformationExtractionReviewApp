# Databricks notebook source
# =============================================================================
# TechFin OCR — Bootstrap & Grant App Service Principal Permissions
# =============================================================================
# Bootstraps a fresh environment (creates schema, tables, volume) and then
# grants Unity Catalog privileges to the Review App's auto-generated SP.
#
# Safe to re-run at any time (all DDL uses IF NOT EXISTS).
#
# Parameters (injected via DABs job — see resources/grant_job.yml):
#   sp_client_id    — App SP client ID (from ${resources.apps.review_app.service_principal_client_id})
#   catalog         — Unity Catalog catalog name
#   write_schema    — Schema that holds output tables and the PDF volume
#   pdf_volume_path — Full volume path (used to derive the volume name)
# =============================================================================

# COMMAND ----------

dbutils.widgets.text("sp_client_id", "")
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("write_schema", "")
dbutils.widgets.text("pdf_volume_path", "")

sp       = dbutils.widgets.get("sp_client_id")
catalog  = dbutils.widgets.get("catalog")
schema   = dbutils.widgets.get("write_schema")
vol_path = dbutils.widgets.get("pdf_volume_path")

assert sp,       "sp_client_id is required"
assert catalog,  "catalog is required"
assert schema,   "write_schema is required"
assert vol_path, "pdf_volume_path is required"

# Derive volume name from path: /Volumes/{catalog}/{schema}/{volume_name}/...
parts = [p for p in vol_path.strip("/").split("/") if p]
assert len(parts) >= 4, f"pdf_volume_path must be /Volumes/{{catalog}}/{{schema}}/{{volume}}/..., got: {vol_path}"
volume_name = parts[3]

print(f"SP client ID  : {sp}")
print(f"Catalog       : {catalog}")
print(f"Schema        : {schema}")
print(f"Volume        : {volume_name}")

# COMMAND ----------

# MAGIC %md ## 1. Bootstrap schema, tables, and volume (idempotent)

# COMMAND ----------

print(f"\nCreating schema {catalog}.{schema} if not exists...")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")

print(f"Creating ocr_results table if not exists...")
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.ocr_results (
        document_name  STRING,
        tipo_entidade  STRING,
        periodo        STRING,
        extracted_json STRING,
        razao_social   STRING,
        cnpj           STRING,
        ativo_total    DOUBLE,
        lucro_liquido  DOUBLE,
        processed_at   TIMESTAMP
    )
    USING DELTA
""")

print(f"Creating ocr_corrections table if not exists...")
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.ocr_corrections (
        document_name  STRING,
        campo          STRING,
        valor_extraido STRING,
        valor_correto  STRING,
        comentario     STRING,
        criado_em      TIMESTAMP
    )
    USING DELTA
""")

print(f"Creating volume {volume_name} if not exists...")
spark.sql(f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`{volume_name}`")

print("Bootstrap complete.")

# COMMAND ----------

# MAGIC %md ## 2. Grant permissions to app SP

# COMMAND ----------

grants = [
    f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{sp}`",
    f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.`{schema}` TO `{sp}`",
    f"GRANT SELECT ON TABLE `{catalog}`.`{schema}`.ocr_results TO `{sp}`",
    f"GRANT SELECT, MODIFY ON TABLE `{catalog}`.`{schema}`.ocr_corrections TO `{sp}`",
    f"GRANT READ_VOLUME, WRITE_VOLUME ON VOLUME `{catalog}`.`{schema}`.`{volume_name}` TO `{sp}`",
]

for stmt in grants:
    print(f"\n{stmt}")
    spark.sql(stmt)
    print("  OK")

print("\nAll permissions granted successfully.")
