# TechFin OCR — Balancos Patrimoniais

Solucao de extracao automatica de dados financeiros de Balancos Patrimoniais e DRE em PDF, usando IA generativa (Claude 3.7 Sonnet) no Databricks. Pipeline orquestrada via Databricks Asset Bundles (DABs) com aplicacao web de revisao humana (FastAPI + React).

## Arquitetura

```
PDFs no Volume UC
       |
       v
[1. parse_pdfs] ---------> raw_parsed_content (texto extraido)
       |
       v
[2. extract_fields (DLT)] --> extracted_content (JSON estruturado via Claude)
       |
       v
[3. process_results] -------> ocr_results (tabela normalizada)
                                 |
                                 v
                     [Review App — FastAPI + React]
                       |-- Revisao por abas (Ativo, Passivo, DRE, Fontes)
                       |-- Correcoes manuais -> ocr_corrections
                       |-- Upload de novos PDFs (async)
                       |-- Export Excel (3 abas)
                       +-- Visualizacao do PDF original
```

## Estrutura do Projeto

```
techfin-ocr-balancos/
├── databricks.yml                          # Config do bundle (variaveis, targets)
├── resources/
│   ├── job.yml                             # Job com 3 tasks (DAG)
│   ├── extract_pipeline.yml                # DLT pipeline (ai_query)
│   └── review_app.yml                      # Databricks App
├── src/
│   ├── pipelines/
│   │   ├── parse_pdfs/
│   │   │   └── parse_pdfs_notebook.py      # PDF -> texto (ai_parse_document)
│   │   ├── extract_fields/
│   │   │   └── transformations/
│   │   │       └── extract_fields.py       # DLT: ai_query -> extracted_content
│   │   └── process_results/
│   │       └── process_results_notebook.py # JSON -> ocr_results
│   └── agents/
│       └── extractor/
│           ├── agent.py                    # MLflow PythonModel (referencia, nao usado)
│           └── output_schema.json          # Schema financeiro (~70 campos)
├── review-app/
│   ├── app.py                              # FastAPI main
│   ├── app.yaml                            # Config da Databricks App
│   ├── requirements.txt                    # Dependencias Python
│   ├── server/                             # Backend (rotas, DB, config)
│   │   ├── config.py                       # Configuracao e WorkspaceClient
│   │   ├── db.py                           # Wrapper SQL (Statement Execution API)
│   │   └── routes/                         # Endpoints REST
│   │       ├── documents.py                # CRUD documentos, PDF, reprocessamento
│   │       ├── corrections.py              # Salvar/deletar correcoes
│   │       ├── metrics.py                  # Dashboard de metricas
│   │       ├── upload.py                   # Upload PDF + OCR async
│   │       └── export.py                   # Export Excel (3 abas)
│   └── frontend/                           # React + TypeScript + Vite + Tailwind
│       ├── src/
│       │   ├── App.tsx                     # Layout principal
│       │   └── components/
│       │       ├── DocumentList.tsx         # Lista de documentos
│       │       ├── FinancialReview.tsx      # Editor multi-aba
│       │       ├── FieldSection.tsx         # Editor de campos
│       │       ├── MetricsDashboard.tsx     # Metricas de correcoes
│       │       ├── FontesPanel.tsx          # Painel de fontes/audit trail
│       │       └── fieldDefinitions.ts      # Metadados dos 70+ campos
│       └── dist/                           # Build estatico (gitignored, incluido no sync)
├── ocr-agent/                              # Referencia (versao anterior do agente)
└── old_app/                                # Referencia (Streamlit + Docling + DSPy)
```

## Pipeline de Extracao (3 Tasks)

### Task 1: `parse_pdfs` (Notebook)
- Le todos os `*.pdf` de um Volume UC
- Extrai texto via `ai_parse_document()` (funcao nativa Databricks)
- Processamento incremental: pula arquivos ja processados
- Saida: `{catalog}.{write_schema}.raw_parsed_content`

### Task 2: `extract_fields` (DLT Pipeline)
- Le `raw_parsed_content`
- Monta prompt completo: instrucoes do sistema + `output_schema.json` + texto do documento
- Chama `ai_query('databricks-claude-3-7-sonnet', full_prompt)` diretamente via Foundation Model API
- `failOnError => false` para capturar erros sem interromper o pipeline
- Saida: `{catalog}.{write_schema}.extracted_content` (JSON por documento)

### Task 3: `process_results` (Notebook)
- Le `extracted_content`, parseia o JSON array retornado pelo Claude
- Cada documento pode gerar multiplas linhas (ex: Consolidado 2024 + Controladora 2024)
- Extrai campos-chave: tipo_entidade, periodo, razao_social, cnpj, ativo_total, lucro_liquido
- Grava em `ocr_results` via `MERGE INTO` (idempotente)
- Cria tabela `ocr_corrections` para correcoes manuais

## Review App

Aplicativo Databricks (FastAPI + React) para revisar e corrigir dados extraidos.

**URL**: `https://techfin-review-{target}-{workspace_id}.aws.databricksapps.com`

### Funcionalidades
- Listagem de documentos com razao social, CNPJ, ativo total, lucro liquido
- Visualizacao por abas: Identificacao, Ativo Circulante, Passivo, DRE, Fontes
- Correcao manual inline com comentario (salvo em `ocr_corrections`)
- Upload de novos PDFs com processamento assincrono (polling de status)
- Reprocessamento individual de documentos existentes
- Export para Excel formatado (3 abas: Dados Financeiros, Correcoes, Fontes)
- Visualizacao inline do PDF original do Volume UC
- Dashboard de metricas: total de correcoes, acuracia, correcoes por campo/documento

### API Endpoints

| Rota | Metodo | Descricao |
|---|---|---|
| `/api/documents` | GET | Lista todos os documentos |
| `/api/documents/{name}` | GET | Detalhe com JSON extraido (todos os periodos/entidades) |
| `/api/documents/{name}/pdf` | GET | Download do PDF original do Volume |
| `/api/documents/{name}/reprocess` | POST | Reprocessa documento via FMAPI |
| `/api/documents/upload` | POST | Upload de novo PDF + processamento async |
| `/api/documents/{name}/status` | GET | Status do processamento em andamento |
| `/api/corrections/{name}` | GET | Correcoes do documento |
| `/api/corrections` | POST | Salvar correcao de um campo |
| `/api/corrections/{name}/{campo}` | DELETE | Remover correcao |
| `/api/metrics` | GET | Metricas agregadas de correcoes |
| `/api/export/excel` | GET | Download do Excel completo |

## Variaveis do Bundle

| Variavel | Default | Descricao |
|---|---|---|
| `catalog` | `cedip_fevm_aws_classic_stable_catalog` | Unity Catalog catalog |
| `schema` | `ai` | Schema de leitura (tabelas fonte) |
| `write_schema` | `ai` (prod: `ai_prod`) | Schema de escrita (tabelas de saida) |
| `pdf_volume_path` | `/Volumes/.../techfin_raw_files/input_files/` | Volume com PDFs de entrada |
| `warehouse_id` | `2c3975c5e258e46b` | SQL Warehouse ID |
| `endpoint_name` | `databricks-claude-3-7-sonnet` | Endpoint FMAPI para extracao |

## Tabelas

| Tabela | Gerenciada por | Descricao |
|---|---|---|
| `raw_parsed_content` | parse_pdfs | Texto extraido dos PDFs (path, raw_parsed, ingested_at) |
| `extracted_content` | extract_fields (DLT) | JSON do Claude por documento |
| `ocr_results` | process_results | Dados estruturados para revisao (1 linha por tipo_entidade x periodo) |
| `ocr_corrections` | review_app | Correcoes manuais dos revisores |

## Deploy

### Pre-requisitos
- Databricks CLI configurado com profile `fevm`
- Node.js >= 18 e npm (para build do frontend)
- Workspace com SQL Warehouse ativo
- Volume UC com PDFs de balancos patrimoniais

### Passo a passo

```bash
# 1. Validar o bundle
databricks bundle validate -t dev

# 2. Build do frontend (obrigatorio antes do deploy)
cd review-app/frontend && npm install && npm run build && cd ../..

# 3. Deploy dos recursos
databricks bundle deploy -t dev

# 4. Executar pipeline de extracao
databricks bundle run extraction_job -t dev

# 5. Iniciar/deploy da review app
databricks apps start techfin-review-dev --profile fevm
databricks apps deploy techfin-review-dev \
  --source-code-path /Workspace/Users/<user>/.bundle/techfin-ocr-balancos/dev/files/review-app \
  --profile fevm
```

### Permissoes da App

O Service Principal da app precisa de:
```sql
GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;
GRANT SELECT ON TABLE <catalog>.<schema>.ocr_results TO `<sp-client-id>`;
GRANT SELECT, MODIFY ON TABLE <catalog>.<schema>.ocr_corrections TO `<sp-client-id>`;
GRANT READ_VOLUME ON VOLUME <catalog>.<schema>.techfin_raw_files TO `<sp-client-id>`;
```
O grupo `users` precisa de `CAN_USE` no SQL Warehouse.

### Producao

```bash
databricks bundle deploy -t prod
databricks bundle run extraction_job -t prod
```

### Comandos uteis

```bash
# Logs da app
databricks apps get techfin-review-dev --profile fevm

# Destruir recursos (cuidado!)
databricks bundle destroy -t dev
```

## Schema de Extracao

O `output_schema.json` define ~70 campos financeiros organizados em:

| Secao | Campos | Descricao |
|---|---|---|
| Identificacao | 6 | tipo_entidade, razao_social, cnpj, periodo, moeda, escala_valores |
| Ativo Circulante | 9 | disponibilidades, titulos a receber, estoques, impostos, etc. |
| Ativo Nao Circulante | 8 | realizavel a longo prazo |
| Ativo Permanente | 4 | investimentos, imobilizado, intangivel |
| Passivo Circulante | 10 | fornecedores, financiamentos, tributos, provisoes, etc. |
| Passivo Nao Circulante | 9 | obrigacoes de longo prazo |
| Patrimonio Liquido | 8 | capital social, reservas, lucros acumulados |
| DRE | 25 | receita bruta ate lucro liquido |
| Fontes | dinamico | mapeamento campo -> texto exato do PDF |

Cada campo inclui um extenso De-Para com nomenclaturas alternativas encontradas em balancos brasileiros, permitindo ao modelo mapear corretamente mesmo com variacao de terminologia.
