# INSTRUCTIONS.md — Guia de Desenvolvimento Futuro

Este documento complementa o README.md com orientacoes praticas, decisoes arquiteturais e licoes aprendidas para quem for dar continuidade ao projeto.

---

## 1. Decisoes Arquiteturais

### Por que nao usamos Custom Model Serving Endpoint

A versao original do projeto registrava um modelo MLflow (`src/agents/extractor/agent.py`) como endpoint customizado (`extraction-agent-endpoint`). Esse modelo chamava a Foundation Model API (FMAPI) internamente via OpenAI SDK.

**Problema**: O ambiente de model serving do Databricks gera tokens de servico que **nao conseguem autenticar** contra a FMAPI. Resultado: erro `401 - Credential was not sent or was of an unsupported type for this API`. Isso nao e um bug do codigo — e uma limitacao do ambiente de model serving.

**Solucao adotada**: Chamar a FMAPI diretamente via `ai_query()` dentro do DLT pipeline. A funcao `ai_query` e nativa do Spark SQL e gerencia autenticacao automaticamente.

**Impacto**: Eliminamos a task `deploy_agent` do job (que registrava e servia o modelo), simplificando o pipeline de 4 para 3 tasks.

> **Referencia**: O codigo do agente MLflow esta em `src/agents/extractor/agent.py` apenas como referencia historica. Nao edite nem tente registra-lo novamente.

### Por que DLT com channel PREVIEW

A funcao `ai_query()` com endpoints FMAPI so funciona no canal `PREVIEW` do DLT. Sem isso, o pipeline falha com erro de funcao nao reconhecida. Essa configuracao esta em `resources/extract_pipeline.yml`:

```yaml
channel: PREVIEW  # Required for ai_query against FMAPI endpoints
```

### Por que serverless no DLT

O pipeline DLT usa `serverless: true` para evitar provisionar clusters dedicados. Isso tambem garante compatibilidade com `ai_query`.

### Carregamento do schema via workspace path

O arquivo `output_schema.json` (70+ campos financeiros) e carregado no DLT via `open(schema_ws_path)`, onde `schema_ws_path` e injetado como configuracao do pipeline apontando para o workspace filesystem:

```yaml
schema_ws_path: ${workspace.file_path}/src/agents/extractor/output_schema.json
```

**Nao use** `os.path.dirname(__file__)` — esse padrao nao funciona de forma confiavel no DLT serverless.

### MERGE INTO para idempotencia

Tanto o notebook `process_results` quanto a review app usam `MERGE INTO` com chave composta `(document_name, tipo_entidade, periodo)` para upserts. Isso garante que reprocessamentos nao dupliquem dados.

---

## 2. Fluxo de Desenvolvimento

### Setup inicial

```bash
# 1. Verificar Databricks CLI configurado com profile fevm
databricks auth describe --profile fevm

# 2. Instalar dependencias do frontend
cd review-app/frontend && npm install && cd ../..

# 3. Validar o bundle
databricks bundle validate -t dev
```

### Ciclo de desenvolvimento

```bash
# 1. Fazer alteracoes no codigo

# 2. Se alterou frontend: rebuild
cd review-app/frontend && npm run build && cd ../..

# 3. Deploy do bundle
databricks bundle deploy -t dev

# 4. Executar o job completo
databricks bundle run extraction_job -t dev

# 5. Ou executar uma task especifica (ex: apenas process_results)
databricks bundle run extraction_job -t dev --task process_results
```

### Build do frontend e obrigatorio antes do deploy

O diretorio `review-app/frontend/dist/` esta no `.gitignore` mas e incluido no deploy via:

```yaml
# databricks.yml
sync:
  include:
    - review-app/frontend/dist/**
```

Se esquecer o build, a app servira 404 no frontend.

### Deploy da Review App

Apos `databricks bundle deploy`, a app precisa ser iniciada/atualizada separadamente:

```bash
# Verificar se a app existe
databricks apps get techfin-review-dev --profile fevm

# Deploy do codigo da app
databricks apps deploy techfin-review-dev \
  --source-code-path /Workspace/Users/<user>/.bundle/techfin-ocr-balancos/dev/files/review-app \
  --profile fevm
```

---

## 3. Configuracao e Variaveis

### Variaveis do bundle (`databricks.yml`)

| Variavel | Onde e usada | Como alterar |
|---|---|---|
| `catalog` | Todas as tasks + app | Mudar default ou override no target |
| `write_schema` | Tabelas de saida | `ai` (dev), `ai_prod` (prod) |
| `endpoint_name` | DLT pipeline + review app | Nome do endpoint FMAPI |
| `warehouse_id` | Review app (Statement Execution API) | ID do SQL Warehouse |
| `pdf_volume_path` | parse_pdfs + review app | Volume UC com PDFs de entrada |

### Variaveis de ambiente da Review App (`app.yaml`)

A app le suas configuracoes de `app.yaml` > `env`. Se alterar tabelas ou warehouse, atualize ambos `databricks.yml` (para o pipeline) e `app.yaml` (para a app).

### Config padrao no codigo (`server/config.py`)

O `config.py` tem defaults hardcoded que sao usados se as env vars nao estiverem definidas. Mantenha-os sincronizados com `app.yaml`:

```python
WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID", "2c3975c5e258e46b")
RESULTS_TABLE = os.environ.get("RESULTS_TABLE", "cedip_fevm_aws_classic_stable_catalog.ai.ocr_results")
```

---

## 4. Permissoes (Criticas)

O Service Principal (SP) da Databricks App precisa de grants especificos. Sem eles, a app retorna 500 Internal Server Error.

```sql
-- Substituir <catalog>, <schema> e <sp-client-id> pelos valores reais
-- SP client ID atual: 72092ac5-964f-40e1-91e6-f1d4f36480d7

GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;
GRANT SELECT ON TABLE <catalog>.<schema>.ocr_results TO `<sp-client-id>`;
GRANT SELECT, MODIFY ON TABLE <catalog>.<schema>.ocr_corrections TO `<sp-client-id>`;
GRANT READ_VOLUME ON VOLUME <catalog>.<schema>.techfin_raw_files TO `<sp-client-id>`;
```

Alem disso, o grupo `users` precisa de `CAN_USE` no SQL Warehouse para que a app consiga executar queries.

**Dica**: Use o `client ID` do SP, nao o display name. Nomes como `app-1leomw techfin-review-dev` nao sao resolvidos pelo SQL GRANT.

---

## 5. Modificando o Schema de Extracao

O schema de campos financeiros esta em `src/agents/extractor/output_schema.json`. Para adicionar/modificar campos:

1. Edite o `output_schema.json` — cada campo tem nome, tipo e um extenso "de-para" com nomenclaturas alternativas
2. **Nao precisa alterar o DLT pipeline** — ele carrega o schema dinamicamente
3. Atualize `review-app/frontend/src/components/fieldDefinitions.ts` para que o frontend exiba o novo campo
4. Atualize `review-app/server/routes/export.py` se o campo deve aparecer no Excel exportado
5. Faca `databricks bundle deploy -t dev` para sincronizar o novo schema

**Importante**: O `process_results` extrai apenas campos-chave (razao_social, cnpj, ativo_total, lucro_liquido) para colunas dedicadas. O restante fica no `extracted_json`. Se precisar de um novo campo como coluna dedicada, edite o notebook.

---

## 6. Adicionando Novos Passos ao Pipeline

### Nova task no job

1. Crie o notebook em `src/pipelines/<nome>/`
2. Adicione a task em `resources/job.yml` com `depends_on` apropriado
3. Use widgets do `dbutils` para parametros, com defaults que funcionem standalone

### Nova rota na Review App

1. Crie o arquivo em `review-app/server/routes/`
2. Registre o router em `review-app/app.py`
3. Use `execute_sql()` de `server/db.py` para queries — ele gerencia a Statement Execution API
4. Para componentes React, adicione em `review-app/frontend/src/components/`

---

## 7. Debugging e Troubleshooting

### Pipeline falha: verificar cada task

```bash
# Ver status do job
databricks bundle run extraction_job -t dev

# Se uma task falhou, verificar logs no Databricks UI:
# Jobs > [dev] TechFin OCR Balancos > Run > Task > Logs
```

### DLT pipeline falha com erro de ai_query

- Verificar que `channel: PREVIEW` esta em `extract_pipeline.yml`
- Verificar que o endpoint FMAPI existe: `databricks serving-endpoints get databricks-claude-3-7-sonnet --profile fevm`
- Verificar que `serverless: true` esta habilitado

### Review app retorna 500

1. **Verificar permissoes do SP** (secao 4 acima)
2. Verificar que o SQL Warehouse esta ativo (nao suspenso/terminado)
3. Ver logs da app: `databricks apps get techfin-review-dev --profile fevm`

### Frontend mostra 404 ou pagina em branco

1. Verificar se o build foi feito: `ls review-app/frontend/dist/`
2. Verificar `sync.include` em `databricks.yml`
3. Refazer deploy: `npm run build && databricks bundle deploy -t dev`

### process_results falha mas funciona standalone

Pode ser cache de versao antiga do notebook. Solucao:

```bash
# Redeploy e executar novamente
databricks bundle deploy -t dev
databricks bundle run extraction_job -t dev --task process_results
```

### Upload/Reprocessamento da app falha com 401

O `_call_ocr_endpoint` em `upload.py` faz chamada HTTP direta ao endpoint FMAPI. Se o token do SP nao tiver permissao no endpoint, falhara com 401. Verifique:
- Se o OCR_ENDPOINT em `app.yaml` aponta para um endpoint valido
- Se o SP tem permissao CAN_QUERY no endpoint

---

## 8. Producao

### Diferenca entre dev e prod

| Aspecto | dev | prod |
|---|---|---|
| `mode` | development | production |
| `write_schema` | ai | ai_prod |
| Nome do job | [dev] TechFin OCR... | [prod] TechFin OCR... |
| Tabelas de saida | catalog.ai.* | catalog.ai_prod.* |

### Deploy para producao

```bash
# 1. Build frontend
cd review-app/frontend && npm run build && cd ../..

# 2. Deploy
databricks bundle deploy -t prod

# 3. Executar
databricks bundle run extraction_job -t prod

# 4. Criar tabelas e grants no schema ai_prod (primeira vez)
```

### Consideracoes

- O schema `ai_prod` precisa existir e ter grants equivalentes ao `ai`
- A review app precisa de uma instancia separada para prod com `app.yaml` apontando para `ai_prod`
- Considere configurar um schedule no job para execucao periodica

---

## 9. Diretorios de Referencia (Nao Editar)

| Diretorio | Conteudo | Status |
|---|---|---|
| `ocr-agent/` | Versao anterior do agente | Referencia |
| `old_app/` | App Streamlit + Docling + DSPy com DABs | Referencia |
| `src/agents/extractor/agent.py` | MLflow PythonModel (tinha 401 auth) | Referencia |

Esses diretorios existem como historico. A arquitetura atual nao depende deles.

---

## 10. Resultados Conhecidos

Na ultima execucao completa do pipeline:
- **parse_pdfs**: 25 PDFs processados com sucesso
- **extract_fields**: 24/25 documentos extraidos (96% sucesso)
- **process_results**: 30 linhas de resultado, 21 documentos distintos
- **Review app**: Funcional em `https://techfin-review-dev-7474656914510817.aws.databricksapps.com`

A taxa de extracao de 96% (1 falha em 25) e esperada — PDFs com layout muito incomum podem falhar. O campo `error_message` na tabela `extracted_content` mostra o motivo da falha.
