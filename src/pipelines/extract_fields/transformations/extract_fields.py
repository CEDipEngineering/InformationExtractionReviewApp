# Databricks notebook source
# =============================================================================
# Extract Financial Fields Pipeline (DLT)
# =============================================================================
# Reads raw parsed document text from raw_parsed_content and calls the
# Foundation Model API endpoint (databricks-claude-3-7-sonnet) directly
# via ai_query to produce structured JSON per document.
#
# Configuration (injected from resources/extract_pipeline.yml):
#   endpoint_name  — Foundation Model API endpoint (e.g. databricks-claude-3-7-sonnet)
#   source_table   — Fully-qualified parse pipeline output table
#   schema_ws_path — Workspace path to output_schema.json
# =============================================================================

# COMMAND ----------

import json
import dlt
from pyspark.sql.functions import col, current_timestamp, expr, concat, lit

endpoint_name  = spark.conf.get("endpoint_name")
source_table   = spark.conf.get("source_table")
schema_ws_path = spark.conf.get("schema_ws_path")

# COMMAND ----------

# Load the output schema from workspace filesystem
with open(schema_ws_path) as f:
    OUTPUT_SCHEMA = json.load(f)

SCHEMA_STR = json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2)

INSTRUCTIONS = (
    "* O documento pode conter MÚLTIPLAS colunas de dados: diferentes tipos de entidade "
    "(Consolidado, Controladora/Individual) e/ou diferentes períodos (datas de referência). "
    "Você DEVE extrair TODAS as combinações presentes, gerando um elemento no array para cada "
    "combinação única de (tipo_entidade, periodo). Exemplos comuns: "
    "[Consolidado 2024-12-31, Controladora 2024-12-31], "
    "[Consolidado 2024-12-31, Consolidado 2023-12-31], "
    "[Consolidado 2024-12-31, Controladora 2024-12-31, Consolidado 2023-12-31, Controladora 2023-12-31].\n"
    "* Para cada elemento, preencha `tipo_entidade` com CONSOLIDADO, CONTROLADORA ou INDIVIDUAL, "
    "conforme o cabeçalho da coluna correspondente no documento.\n"
    "* Substitua qualquer valor null, vazio ou não informado por zero.\n"
    "* Formate todos os números para exibir exatamente 2 casas decimais, usando ponto como separador, "
    "mesmo que o valor seja inteiro ou zero (ex: 834988.00, 0.00, 15.50).\n"
    "* Preencha o objeto `fontes` no JSON de saída: para cada campo extraído, indique qual texto exato do PDF "
    "originou o valor. Use o caminho do campo como chave (ex: 'ativo_circulante.impostos_a_recuperar') "
    "e como valor descreva brevemente: o(s) nome(s) da(s) linha(s) do documento, os valores individuais "
    "e a operação realizada (ex: soma, leitura direta). "
    "Exemplo: 'Impostos a recuperar (2.411) + IRPJ e CSLL a compensar (4.596) = 7.007 (escala: milhares)'. "
    "Se o valor foi lido diretamente de uma única linha, indique apenas o nome da linha e o valor. "
    "Inclua fontes apenas para campos com valor diferente de zero."
)

PROMPT_PREFIX = f"""Você é um especialista em análise de demonstrações financeiras brasileiras.
Sua tarefa é extrair informações estruturadas de documentos financeiros (Balanço Patrimonial e DRE).

Instruções adicionais:
{INSTRUCTIONS}

Retorne SOMENTE um JSON array válido seguindo exatamente o schema fornecido. Sem texto adicional.

Extraia as informações financeiras do seguinte documento e retorne um JSON seguindo exatamente este schema:

{SCHEMA_STR}

DOCUMENTO:
"""

# COMMAND ----------

@dlt.table(
    name="extracted_content",
    comment="Structured financial data extracted via ai_query (FMAPI), one row per document",
)
def extracted_content():
    return (
        spark.table(source_table)
        .filter(col("raw_parsed").isNotNull())
        .withColumn("full_prompt", concat(lit(PROMPT_PREFIX), col("raw_parsed")))
        .withColumn(
            "response",
            expr(
                f"ai_query('{endpoint_name}', full_prompt, returnType => 'STRING', failOnError => false)"
            ),
        )
        .select(
            col("path"),
            col("raw_parsed"),
            col("response.result").alias("extracted"),
            col("response.errorMessage").alias("error_message"),
            current_timestamp().alias("extracted_at"),
        )
    )
