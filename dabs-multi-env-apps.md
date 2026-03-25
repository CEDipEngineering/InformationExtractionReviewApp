# Parameterizing Databricks Apps with DABs — Multi-Environment Guide

## Core Pattern

DABs supports Apps as a first-class resource. The strategy is:
- **`databricks.yml`** — declares variables, target overrides, and resource bindings
- **`app.yaml`** — stable runtime contract with sensible defaults; environment-specific values are overridden per target

## 1. Declare Variables at the Top Level

```yaml
bundle:
  name: mission-control

variables:
  sql_warehouse_id:
    description: "SQL Warehouse ID"
  catalog_name:
    description: "Unity Catalog catalog name"
    default: "system"
  secret_scope:
    description: "Secret scope for this environment"
    default: "mission-control-dev"
```

## 2. Define the App Resource with Variable References

```yaml
resources:
  apps:
    mission_control:
      name: "mission-control-${bundle.target}"   # auto-suffixed per env
      description: "Lakeflow FinOps - cost and ops monitoring"
      source_code_path: .
      config:
        command:
          - uvicorn
          - backend.app.main:app
          - --host=0.0.0.0
          - --port=8000
        env:
          - name: CATALOG_NAME
            value: ${var.catalog_name}
          - name: SQL_WAREHOUSE_ID
            value: ${var.sql_warehouse_id}
          - name: APP_ENVIRONMENT
            value: ${bundle.target}
      resources:
        - name: "sql-warehouse"
          sql_warehouse:
            id: ${var.sql_warehouse_id}
            permission: CAN_USE
        - name: "app-secrets"
          secret:
            scope: ${var.secret_scope}
            key: "app-token"
            permission: READ
```

## 3. Override Per Target

```yaml
targets:
  dev:
    default: true
    mode: development
    workspace:
      host: https://dev-workspace.cloud.databricks.com
      profile: fevm
    variables:
      sql_warehouse_id: "dev-warehouse-123"
      catalog_name: "system"
      secret_scope: "mission-control-dev"

  staging:
    workspace:
      host: https://staging-workspace.cloud.databricks.com
      profile: fevm-staging
    variables:
      sql_warehouse_id: "staging-warehouse-456"
      catalog_name: "system"
      secret_scope: "mission-control-staging"

  prod:
    mode: production
    workspace:
      host: https://prod-workspace.cloud.databricks.com
      profile: fevm-prod
    variables:
      sql_warehouse_id: "prod-warehouse-789"
      catalog_name: "system"
      secret_scope: "mission-control-prod"
    run_as:
      service_principal_name: "mission-control-prod-sp"
```

## 4. Variable Resolution Precedence (highest to lowest)

1. `--var` CLI flag: `databricks bundle deploy --var sql_warehouse_id=xyz`
2. `BUNDLE_VAR_*` env vars (great for CI/CD): `export BUNDLE_VAR_sql_warehouse_id=xyz`
3. `.databricks/bundle/<target>/variable-overrides.json` (local dev, gitignored)
4. Target-level `variables` in `databricks.yml`
5. Top-level `default` value

## 5. Secrets Best Practice

**Never put secrets as plain `value` in env vars.** Use Databricks secret scopes:

```yaml
# In databricks.yml — bind the secret as a resource
resources:
  apps:
    mission_control:
      resources:
        - name: "api-token"
          secret:
            scope: "mission-control-${bundle.target}"
            key: "api-token"
            permission: READ
```

```yaml
# In app.yaml — reference by resource name
env:
  - name: API_TOKEN
    valueFrom: "api-token"    # resolved from the secret binding
```

Create per-env scopes: `mission-control-dev`, `mission-control-staging`, `mission-control-prod`.

## 6. SP Grants Automation

Each app gets an auto-generated service principal. Use the built-in substitution to grant it permissions:

```yaml
resources:
  jobs:
    grant_permissions:
      name: "mc-grant-permissions-${bundle.target}"
      tasks:
        - task_key: grant
          notebook_task:
            notebook_path: ./scripts/grant_app_permissions.py
            base_parameters:
              principal: ${resources.apps.mission_control.service_principal_client_id}
```

## 7. Deployment — Two-Step Process (Critical Gotcha)

```bash
# Step 1: Deploy bundle (creates app resource, syncs source code)
databricks bundle deploy --target prod

# Step 2: Run the app (applies config + env vars and starts it)
databricks bundle run mission_control --target prod
```

The `config` block in `databricks.yml` is **only applied via `bundle run`**, not via `databricks apps deploy`. This is the most common pitfall.

## Key Gotchas

| Issue | Detail |
|---|---|
| `config` requires CLI v0.283.0+ | Older versions don't support `config.env` in the app resource |
| `mode: development` prefixes names | App names get prefixed — ensure the result is still valid (lowercase + hyphens) |
| `app.yaml` is NOT templated | You can't use `${var.*}` inside `app.yaml` — use `databricks.yml` config/env overrides instead |
| `databricks apps deploy` can wipe config | Always use `bundle run` for DABs-managed apps |

## Summary

| Concern | Where | Mechanism |
|---|---|---|
| Warehouse ID | `databricks.yml` variables | Resource binding + `valueFrom` |
| Catalog name, log level, flags | `databricks.yml` target `config.env` | `${var.*}` substitution |
| Secrets | Secret scopes per env | `valueFrom` in `app.yaml` |
| SP credentials | Automatic | Injected by Apps runtime |
| OBO user tokens | Automatic | `X-Forwarded-Access-Token` header |
