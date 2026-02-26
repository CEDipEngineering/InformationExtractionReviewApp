# Agent Bricks: Information Extraction

> **Status:** Beta — requires _Mosaic AI Agent Bricks Preview_ enabled on the workspace.
> **Docs:** https://docs.databricks.com/aws/en/generative-ai/agent-bricks/key-info-extraction

## Overview

Agent Bricks Information Extraction (Key Information Extraction / KIE) converts unstructured
document text into structured JSON. In this project it is used to extract balance-sheet and
income-statement (DRE) fields from parsed financial PDFs.

The deployed agent is invoked at scale via the `ai_query` SQL function inside the Lakeflow
`extract_pipeline` (`src/pipelines/extract_fields/`).

---

## Prerequisites

| Requirement | Detail |
|---|---|
| Workspace feature | Mosaic AI Agent Bricks Preview enabled |
| Compute | Serverless compute activated |
| Catalog | Unity Catalog with `system.ai` foundation model access |
| Budget | Serverless budget policy with nonzero allocation |
| SQL support | `ai_query` function available |
| Source data | Documents in a UC volume or table (≥ 1 document) |
| Region | `us-east-1` or `us-west-2` |
| PDF support | PDFs must be pre-processed with `ai_parse_document` → markdown (done by `parse_pipeline`) |

---

## Setup Steps

### Step 1 — Create the agent

1. In the Databricks workspace, go to **Mosaic AI → Agent Bricks**.
2. Click **Create** and choose **Information Extraction**.
3. Name the agent (e.g. `Unlabeled Dataset`).
4. Select **Unlabeled dataset** and point it at the parsed documents source
   (table `cedip_fevm_aws_classic_stable_catalog.ai.raw_parsed_content`,
   column `raw_parsed`).
5. Paste or upload the target JSON schema (see [Output Schema](#output-schema) below).
   Agent Bricks auto-infers field descriptions; review and adjust them.
6. Choose an optimization strategy:
   - **Scale optimization** (default) — high throughput, lower cost
   - **Complexity optimization** — higher accuracy for complex layouts

### Step 2 — Refine with sample outputs

1. Review the sample extractions generated from your documents.
2. Use thumbs-up / thumbs-down feedback on individual fields.
3. Edit field descriptions in the schema if the model misunderstands a field.
4. Optionally add **global instructions** (e.g. "Values are in BRL thousands unless stated otherwise").
5. Iterate until the sample outputs are satisfactory.

### Step 3 — Deploy

1. Click **Deploy** to publish the agent as a model-serving endpoint.
2. Note the endpoint name — it becomes the `endpoint_name` bundle variable.
   - Current endpoint: **`kie-76e4b503-endpoint`** (set as default in `databricks.yml`)
3. Grant permissions to any users/service principals that need to call the endpoint
   (`Can Query` for the pipeline service principal; `Can Manage` for team leads).

### Step 4 — Evaluate quality (optional but recommended)

1. From the agent page, click **Evaluate**.
2. Run against a labeled sample (e.g. the three ground-truth entries in
   `src/validation/validate_against_reference.py`).
3. Review the quality report: overall accuracy, per-field scores, cost, throughput.
4. If accuracy is insufficient, return to Step 2 and refine descriptions or add instructions.

---

## Output Schema

The schema below was used to configure this agent. Each document produces one JSON object
with company metadata and an array of financial reports (one per period found in the document).

```json
{
  "metadados_empresa": {
    "razao_social": "TELESIL ENGENHARIA LTDA",
    "cnpj": "01.637.593/0001-64"
  },
  "relatorios": [
    {
      "identificacao": {
        "periodo": "2021-12-31",
        "tipo_demonstrativo": "ANUAL",
        "moeda": "REAL",
        "escala_valores": "MILHARES"
      },
      "balanco": {
        "ativo": {
          "ativo_circulante": {
            "disponibilidades": 0,
            "titulos_a_receber": 0,
            "estoques": 0,
            "adiantamentos": 0,
            "impostos_a_recuperar": 0,
            "outros_ativos_circulantes": 0,
            "conta_corrente_socios_control_colig": 0,
            "outros_ativos_financeiros": 0,
            "total_ativo_circulante": 0
          },
          "ativo_nao_circulante": {
            "titulos_a_receber": 0,
            "estoques": 0,
            "adiantamentos": 0,
            "impostos_a_recuperar": 0,
            "despesas_pagas_antecipadamente": 0,
            "conta_corrente_socios_control_colig": 0,
            "outros_realizavel_a_longo_prazo": 0,
            "total_ativo_nao_circulante": 0
          },
          "ativo_permanente": {
            "investimentos": 0,
            "imobilizado": 0,
            "intangivel_diferido": 0,
            "total_ativo_permanente": 0
          },
          "ativo_total": 0
        },
        "passivo_patrimonio_liquido": {
          "passivo_circulante": {
            "fornecedores": 0,
            "financiamentos_com_instituicoes_de_credito": 0,
            "salarios_contribuicoes": 0,
            "tributos": 0,
            "adiantamentos": 0,
            "conta_corrente_socios_coligadas_controladas": 0,
            "outros_passivos_circulante": 0,
            "provisoes": 0,
            "outros_passivos_financeiros": 0,
            "total_passivo_circulante": 0
          },
          "passivo_nao_circulante": {
            "fornecedores": 0,
            "financiamentos_com_instituicoes_de_credito": 0,
            "salarios_contribuicoes": 0,
            "tributos": 0,
            "adiantamentos": 0,
            "conta_corrente_socios_coligadas_controladas": 0,
            "outros_passivos_nao_circulantes": 0,
            "provisoes": 0,
            "total_passivo_nao_circulante": 0
          },
          "patrimonio_liquido": {
            "capital_social": 0,
            "reserva_de_capital": 0,
            "reservas_de_lucro": 0,
            "reservas_de_reavaliacao": 0,
            "outras_reservas": 0,
            "lucros_ou_prejuizos_acumulados": 0,
            "acoes_em_tesouraria": 0,
            "total_patrimonio_liquido": 0
          },
          "passivo_total": 0
        }
      },
      "dre": {
        "receita_operacional_bruta": 0,
        "deducoes_de_receita_bruta": {
          "vendas_anuladas": 0,
          "abatimentos": 0,
          "impostos_incidentes_sobre_vendas": 0,
          "total_deducoes": 0
        },
        "receita_operacional_liquida": 0,
        "custo_servicos_produtos_mercadorias_vendidas": 0,
        "lucro_bruto": 0,
        "despesas_operacionais": {
          "despesas_com_vendas": 0,
          "provisao_para_devedores_duvidosos": 0,
          "outras_receitas_despesas_operacionais": 0,
          "despesas_administrativas": 0,
          "despesas_tributarias": 0,
          "despesas_gerais": 0,
          "depreciacao": 0,
          "amortizacao": 0,
          "total_despesas_operacionais": 0
        },
        "lucro_operacional": 0,
        "resultado_financeiro": {
          "despesas_financeiras": 0,
          "receitas_financeiras": 0,
          "total_resultado_financeiro": 0
        },
        "resultado_de_equivalencia_patrimonial": 0,
        "lucro_antes_imposto_de_renda": 0,
        "provisao_imposto_de_renda_csll": 0,
        "lucro_liquido": 0
      }
    }
  ]
}
```

---

## Querying the Endpoint

Once deployed, the endpoint can be called with `ai_query`. This is what the `extract_pipeline`
does at scale, but you can also run ad-hoc queries:

```sql
SELECT
  path,
  ai_query(
    'kie-76e4b503-endpoint',
    raw_parsed
  ) AS extracted_json
FROM cedip_fevm_aws_classic_stable_catalog.ai.raw_parsed_content
LIMIT 5;
```

The result is already a `VARIANT`. Use the `:` semi-structured accessor directly:

```sql
SELECT
  path,
  ai_query('kie-76e4b503-endpoint', raw_parsed):metadados_empresa:razao_social::STRING AS razao_social,
  ai_query('kie-76e4b503-endpoint', raw_parsed):relatorios[0]:identificacao:periodo::STRING AS periodo
FROM cedip_fevm_aws_classic_stable_catalog.ai.raw_parsed_content
LIMIT 5;
```

---

## Known Limitations

- Maximum context length: **128k tokens**
- Not supported on Enhanced Security and Compliance workspaces
- Union schema types are not supported
- Only available in `us-east-1` and `us-west-2`
