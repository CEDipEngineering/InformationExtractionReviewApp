# Databricks notebook source
# =============================================================================
# Evaluate Information Extraction Accuracy Against Ground Truth
# =============================================================================
# Compares extracted_content (Agent Bricks KIE output) against the Excel
# ground truth for the 3 documents where a tab ↔ PDF match exists.
#
# Usage:
#   1. Import into a Databricks workspace notebook.
#   2. Attach to any cluster that can reach Unity Catalog.
#   3. Run all cells.  The final cell renders a colour-coded comparison table
#      and prints an accuracy summary for each document.
# =============================================================================

# COMMAND ----------

%pip install openpyxl

# COMMAND ----------

import json
import re
from datetime import datetime, date

import pandas as pd
from IPython.display import HTML, display

# ---------------------------------------------------------------------------
# Paths — edit if the environment changes
# ---------------------------------------------------------------------------
EXCEL_PATH       = "/Volumes/cedip_fevm_aws_classic_stable_catalog/ai/techfin_raw_files/ground_truth.xlsx"
EXTRACTED_TABLE  = "cedip_fevm_aws_classic_stable_catalog.ai.extracted_content"
BASE             = "dbfs:/Volumes/cedip_fevm_aws_classic_stable_catalog/ai/techfin_raw_files/input_files/"

# Only the three tabs that have a confirmed PDF counterpart
TAB_TO_PDF: dict[str, str] = {
    " AESA AUTOMOLAS": BASE + "AESA AUTOMOLAS EQUIPAMENTOS LTDA balt 06 25.pdf",
    "CUSTOM PAPER":    BASE + "CUSTOM PAPER COMERCIO E SERVICOS DE INFORMATICA LTDA BALT 09 25.pdf",
    "Fazenda Iowa":    BASE + "FAZENDA IOWA LTDA BP 24 COMP 23.pdf",
}

# COMMAND ----------

# =============================================================================
# Row-label → JSON path mapping
# =============================================================================
# Duplicate labels in the Excel (e.g. "Títulos a Receber" appears in both
# ativo_circulante and ativo_nao_circulante) are resolved via a section tracker
# that follows the fixed row order of every sheet.
#
# Rows intentionally omitted from the map:
#   • Sub-items whose parent subtotal is already mapped
#     (e.g. "Encargos Financeiros" → parent is "Despesas financeiras")
#   • Rows with no clean 1-to-1 JSON counterpart
#     (e.g. "Lucro Financeiro" ≈ lucro_operacional + resultado_financeiro)
# =============================================================================

# Transitions: when we finish reading a section-subtotal row, the NEXT rows
# belong to a new section.  Order matters — do NOT reorder.
_SECTION_AFTER: dict[str, str] = {
    "Ativo Circulante":       "ativo_ncirc",
    "Ativo Não Circulante":   "ativo_perm",
    "Passivo":                "pass_circ",
    "Passivo Circulante":     "pass_ncirc",
    "Passivo Não Circulante": "pl",
    "DRE":                    "dre",
}

# (section, excel_label) → dotted JSON path inside relatorios[i]
ROW_MAP: dict[tuple[str, str], str] = {
    # ── Ativo Circulante ────────────────────────────────────────────────────
    ("ativo_circ", "Disponibilidades"):
        "balanco.ativo.ativo_circulante.disponibilidades",
    ("ativo_circ", "Títulos a Receber"):
        "balanco.ativo.ativo_circulante.titulos_a_receber",
    ("ativo_circ", "Estoques"):
        "balanco.ativo.ativo_circulante.estoques",
    ("ativo_circ", "Adiantamentos"):
        "balanco.ativo.ativo_circulante.adiantamentos",
    ("ativo_circ", "Impostos a Recuperar"):
        "balanco.ativo.ativo_circulante.impostos_a_recuperar",
    ("ativo_circ", "Outros ativos circulantes"):
        "balanco.ativo.ativo_circulante.outros_ativos_circulantes",
    ("ativo_circ", "Conta corrente coop/socios/control./Colig."):
        "balanco.ativo.ativo_circulante.conta_corrente_socios_control_colig",
    ("ativo_circ", "Outros ativos financeiros"):
        "balanco.ativo.ativo_circulante.outros_ativos_financeiros",
    ("ativo_circ", "Ativo Circulante"):
        "balanco.ativo.ativo_circulante.total_ativo_circulante",
    # ── Ativo Não Circulante ─────────────────────────────────────────────────
    ("ativo_ncirc", "Títulos a Receber"):
        "balanco.ativo.ativo_nao_circulante.titulos_a_receber",
    ("ativo_ncirc", "Estoques"):
        "balanco.ativo.ativo_nao_circulante.estoques",
    ("ativo_ncirc", "Adiantamentos"):
        "balanco.ativo.ativo_nao_circulante.adiantamentos",
    ("ativo_ncirc", "Impostos a Recuperar"):
        "balanco.ativo.ativo_nao_circulante.impostos_a_recuperar",
    ("ativo_ncirc", "Despesas pagas antecipadamente"):
        "balanco.ativo.ativo_nao_circulante.despesas_pagas_antecipadamente",
    ("ativo_ncirc", "Conta corrente coop/socios/control./Colig."):
        "balanco.ativo.ativo_nao_circulante.conta_corrente_socios_control_colig",
    ("ativo_ncirc", "Outros realizável a longo prazo"):
        "balanco.ativo.ativo_nao_circulante.outros_realizavel_a_longo_prazo",
    ("ativo_ncirc", "Ativo Não Circulante"):
        "balanco.ativo.ativo_nao_circulante.total_ativo_nao_circulante",
    # ── Ativo Permanente ─────────────────────────────────────────────────────
    ("ativo_perm", "Investimentos"):
        "balanco.ativo.ativo_permanente.investimentos",
    ("ativo_perm", "Imobilizado"):
        "balanco.ativo.ativo_permanente.imobilizado",
    ("ativo_perm", "Intangível / Diferido"):
        "balanco.ativo.ativo_permanente.intangivel_diferido",
    ("ativo_perm", "Ativo Permanente"):
        "balanco.ativo.ativo_permanente.total_ativo_permanente",
    ("ativo_perm", "Ativo Total"):
        "balanco.ativo.ativo_total",
    # ── Passivo Circulante ───────────────────────────────────────────────────
    ("pass_circ", "Fornecedores"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.fornecedores",
    ("pass_circ", "Financiamentos com instituições de crédito"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.financiamentos_com_instituicoes_de_credito",
    ("pass_circ", "Salários/Contribuições"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.salarios_contribuicoes",
    ("pass_circ", "Tributos"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.tributos",
    ("pass_circ", "Adiantamentos"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.adiantamentos",
    ("pass_circ", "Conta Corrente sócios/coligadas/controladas"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.conta_corrente_socios_coligadas_controladas",
    ("pass_circ", "Outros passivos circulante"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.outros_passivos_circulante",
    ("pass_circ", "Provisões"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.provisoes",
    ("pass_circ", "Outros passivos financeiros"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.outros_passivos_financeiros",
    ("pass_circ", "Passivo Circulante"):
        "balanco.passivo_patrimonio_liquido.passivo_circulante.total_passivo_circulante",
    # ── Passivo Não Circulante ───────────────────────────────────────────────
    ("pass_ncirc", "Fornecedores"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.fornecedores",
    ("pass_ncirc", "Financiamentos com instituições de crédito"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.financiamentos_com_instituicoes_de_credito",
    ("pass_ncirc", "Salários/Contribuições"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.salarios_contribuicoes",
    ("pass_ncirc", "Tributos"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.tributos",
    ("pass_ncirc", "Adiantamentos"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.adiantamentos",
    ("pass_ncirc", "Conta Corrente sócios/coligadas/controladas"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.conta_corrente_socios_coligadas_controladas",
    ("pass_ncirc", "Outros Passivos Não Circulantes"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.outros_passivos_nao_circulantes",
    ("pass_ncirc", "Provisões"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.provisoes",
    ("pass_ncirc", "Passivo Não Circulante"):
        "balanco.passivo_patrimonio_liquido.passivo_nao_circulante.total_passivo_nao_circulante",
    # ── Patrimônio Líquido ───────────────────────────────────────────────────
    ("pl", "Capital Social"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.capital_social",
    ("pl", "Reserva de capital"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.reserva_de_capital",
    ("pl", "Reservas de lucro"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.reservas_de_lucro",
    ("pl", "Reservas de reavaliação"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.reservas_de_reavaliacao",
    ("pl", "Outras reservas"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.outras_reservas",
    ("pl", "Lucros ou prejuízos acumulados"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.lucros_ou_prejuizos_acumulados",
    ("pl", "Ações em tesouraria"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.acoes_em_tesouraria",
    ("pl", "Patrimônio líquido"):
        "balanco.passivo_patrimonio_liquido.patrimonio_liquido.total_patrimonio_liquido",
    ("pl", "Passivo Total"):
        "balanco.passivo_patrimonio_liquido.passivo_total",
    # ── DRE ─────────────────────────────────────────────────────────────────
    ("dre", "Receita operacional bruta"):
        "dre.receita_operacional_bruta",
    ("dre", "Vendas anuladas"):
        "dre.deducoes_de_receita_bruta.vendas_anuladas",
    ("dre", "Abatimentos"):
        "dre.deducoes_de_receita_bruta.abatimentos",
    ("dre", "Impostos incidentes sobre vendas"):
        "dre.deducoes_de_receita_bruta.impostos_incidentes_sobre_vendas",
    ("dre", "Deduções de receita bruta"):
        "dre.deducoes_de_receita_bruta.total_deducoes",
    ("dre", "Receita operacional líquida"):
        "dre.receita_operacional_liquida",
    ("dre", "Custo Serviços/Produtos/Mercadorias Vendidas"):
        "dre.custo_servicos_produtos_mercadorias_vendidas",
    ("dre", "Lucro Bruto"):
        "dre.lucro_bruto",
    ("dre", "Despesas com vendas"):
        "dre.despesas_operacionais.despesas_com_vendas",
    ("dre", "Provisão para devedores duvidosos"):
        "dre.despesas_operacionais.provisao_para_devedores_duvidosos",
    ("dre", "Outras Receitas(-)/ Despesas Operacionais"):
        "dre.despesas_operacionais.outras_receitas_despesas_operacionais",
    ("dre", "Despesas administrativas"):
        "dre.despesas_operacionais.despesas_administrativas",
    ("dre", "Despesas tributarias"):
        "dre.despesas_operacionais.despesas_tributarias",
    ("dre", "Despesas gerais"):
        "dre.despesas_operacionais.despesas_gerais",
    ("dre", "Depreciação"):
        "dre.despesas_operacionais.depreciacao",
    ("dre", "Amortização"):
        "dre.despesas_operacionais.amortizacao",
    ("dre", "Despesas operacionais"):
        "dre.despesas_operacionais.total_despesas_operacionais",
    ("dre", "Lucro operacional"):
        "dre.lucro_operacional",
    ("dre", "Despesas financeiras"):
        "dre.resultado_financeiro.despesas_financeiras",
    ("dre", "Receitas financeiras"):
        "dre.resultado_financeiro.receitas_financeiras",
    ("dre", "(-/+)Resultado de equivalência patrimonial"):
        "dre.resultado_de_equivalencia_patrimonial",
    ("dre", "Lucro antes do imposto de renda"):
        "dre.lucro_antes_imposto_de_renda",
    ("dre", "Lucro líquido"):
        "dre.lucro_liquido",
}

# COMMAND ----------

# =============================================================================
# Helper: parse one Excel sheet → {period_str: {json_path: float}}
# =============================================================================

def parse_excel_sheet(excel_path: str, tab_name: str) -> dict[str, dict[str, float]]:
    """
    Returns a dict keyed by period string (e.g. "2024-12-31").
    Each value is a flat dict mapping JSON path → numeric ground-truth value.
    Only columns whose PERÍODO cell is a proper date are included.
    """
    import openpyxl

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb[tab_name]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Locate the PERÍODO row to discover which columns hold period data
    period_cols: dict[int, str] = {}   # col_index → "YYYY-MM-DD"
    for row in rows:
        if row[0] == "PERÍODO":
            for i, val in enumerate(row):
                if i < 2:
                    continue
                if isinstance(val, (datetime, date)) and hasattr(val, "year"):
                    period_cols[i] = val.strftime("%Y-%m-%d")
            break

    if not period_cols:
        raise ValueError(f"No date-valued PERÍODO columns found in sheet {tab_name!r}")

    result: dict[str, dict[str, float]] = {p: {} for p in period_cols.values()}

    section = "ativo_circ"
    seen_dre_receitas = False   # handle the duplicate "Receitas financeiras" row

    for row in rows:
        label = str(row[0]).strip() if row[0] is not None else ""
        if not label:
            continue

        # 1. Extract data for the current section BEFORE any transition
        key = (section, label)
        if key in ROW_MAP:
            # Special case: "Receitas financeiras" appears twice in DRE;
            # use the second occurrence (the subtotal) by tracking the first.
            if key == ("dre", "Receitas financeiras"):
                if not seen_dre_receitas:
                    seen_dre_receitas = True
                    # skip first occurrence — the second is the subtotal
                    if label in _SECTION_AFTER:
                        section = _SECTION_AFTER[label]
                    continue
            json_path = ROW_MAP[key]
            for col_idx, period_str in period_cols.items():
                if col_idx < len(row) and row[col_idx] is not None:
                    try:
                        result[period_str][json_path] = float(row[col_idx])
                    except (ValueError, TypeError):
                        pass

        # 2. Apply section transition for subsequent rows
        if label in _SECTION_AFTER:
            section = _SECTION_AFTER[label]

    return result

# COMMAND ----------

# =============================================================================
# Helper: navigate a nested dict with a dot-separated path
# =============================================================================

def get_nested(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj

# COMMAND ----------

# =============================================================================
# Helper: find the best-matching relatorio for a given ground-truth period
# =============================================================================

def parse_period_to_ym(period_str: str) -> str | None:
    """
    Extract YYYY-MM from a period string, handling:
      - ISO date:          "2025-06-30"                          → "2025-06"
      - Brazilian date:    "30/06/2025"                          → "2025-06"
      - Natural language:  "2º Trimestre de 2025 - 30/06/2025"  → "2025-06"
    Returns None if no recognisable date is found.
    """
    # ISO format: YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-\d{2}", period_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    # Brazilian format: DD/MM/YYYY (also embedded in natural-language strings)
    m = re.search(r"\d{2}/(\d{2})/(\d{4})", period_str)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return None


def match_gt_to_relatorio(relatorios: list[dict], gt_period: str) -> dict | None:
    """
    Return the relatorio whose period year-month matches gt_period's year-month.
    gt_period is always YYYY-MM-DD (from parse_excel_sheet).
    Returns None — does NOT fall back — when no genuine match is found.
    """
    target_ym = gt_period[:7]   # "YYYY-MM"
    for rel in relatorios:
        raw = get_nested(rel, "identificacao.periodo") or ""
        if parse_period_to_ym(raw) == target_ym:
            return rel
    return None

# COMMAND ----------

# =============================================================================
# Helper: compare one ground-truth value against one extracted value
# =============================================================================

_TOLERANCE = 0.01   # 1% relative tolerance

def compare_values(gt, ex) -> tuple[str, float | None]:
    """
    Returns (status, relative_error_or_None).
    Statuses: exact | close | wrong | zero_both | missing_ex | missing_gt
    """
    try:
        gt = float(gt) if gt is not None else None
        ex = float(ex) if ex is not None else None
    except (ValueError, TypeError):
        return ("missing_gt", None)

    if gt is None:
        return ("missing_gt", None)
    if ex is None:
        return ("missing_ex", None)
    if gt == 0 and ex == 0:
        return ("zero_both", 0.0)
    if gt == ex:
        return ("exact", 0.0)
    if gt != 0:
        rel_err = abs(ex - gt) / abs(gt)
        return ("close", rel_err) if rel_err <= _TOLERANCE else ("wrong", rel_err)
    return ("wrong", None)   # gt == 0, ex != 0

# COMMAND ----------

# =============================================================================
# Load extracted_content once (avoid repeated Spark queries)
# =============================================================================

extracted_pdf = spark.sql(
    f"SELECT path, TO_JSON(extracted) AS extracted_json, error "
    f"FROM {EXTRACTED_TABLE}"
).toPandas()

extracted_map: dict[str, dict] = {}
for _, row in extracted_pdf.iterrows():
    raw = row["extracted_json"]
    if raw:
        try:
            extracted_map[row["path"]] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

print(f"Loaded {len(extracted_map)} rows from {EXTRACTED_TABLE}")

# COMMAND ----------

# =============================================================================
# Main evaluation loop
# =============================================================================

_STATUS_COLOR = {
    "exact":      "#d4edda",   # green
    "close":      "#d4edda",   # green
    "zero_both":  "#e2e3e5",   # grey
    "wrong":      "#f8d7da",   # red
    "missing_ex": "#fff3cd",   # yellow
    "missing_gt": "#ffffff",   # white / skip
}

for tab_name, pdf_path in TAB_TO_PDF.items():
    print(f"\n{'═'*72}")
    print(f"  {tab_name}  →  {pdf_path.split('/')[-1]}")
    print(f"{'═'*72}")

    # ── Guard: extraction present? ───────────────────────────────────────────
    extracted = extracted_map.get(pdf_path)
    if not extracted:
        print(f"  ⚠  Not found in {EXTRACTED_TABLE} (path may differ)")
        continue

    relatorios = extracted.get("relatorios") or []
    if not relatorios:
        print("  ⚠  Extracted JSON has no 'relatorios' entries")
        continue

    # ── Ground truth ─────────────────────────────────────────────────────────
    gt_by_period = parse_excel_sheet(EXCEL_PATH, tab_name)
    gt_periods   = [p for p, fields in gt_by_period.items() if fields]
    ex_periods   = [get_nested(r, "identificacao.periodo") for r in relatorios]

    print(f"\n  Ground-truth periods : {gt_periods}")
    print(f"  Extracted periods    : {ex_periods}")

    all_rows: list[dict] = []

    for gt_period, gt_fields in gt_by_period.items():
        if not gt_fields:
            continue

        relatorio = match_gt_to_relatorio(relatorios, gt_period)
        if relatorio is None:
            print(f"\n  ⚠  GT period {gt_period} — no matching extracted relatorio (skipped)")
            continue

        ex_period = get_nested(relatorio, "identificacao.periodo")
        print(f"\n  Comparing GT {gt_period}  ↔  extracted {ex_period}")

        for json_path, gt_val in sorted(gt_fields.items()):
            ex_val            = get_nested(relatorio, json_path) if relatorio else None
            status, rel_err   = compare_values(gt_val, ex_val)
            all_rows.append({
                "period":       gt_period,
                "field":        json_path.split(".")[-1],
                "json_path":    json_path,
                "ground_truth": gt_val,
                "extracted":    ex_val,
                "status":       status,
                "rel_err_%":    round(rel_err * 100, 2) if rel_err is not None else None,
            })

    if not all_rows:
        print("  No comparable fields found.")
        continue

    df = pd.DataFrame(all_rows)

    # ── Accuracy summary ─────────────────────────────────────────────────────
    countable   = df[df["status"].isin(["exact", "close", "zero_both", "wrong"])]
    correct     = df[df["status"].isin(["exact", "close", "zero_both"])]
    missing_ex  = (df["status"] == "missing_ex").sum()
    accuracy    = len(correct) / len(countable) * 100 if len(countable) else 0.0

    print(f"\n  Fields with GT value : {len(df)}")
    print(f"  Comparable fields    : {len(countable)}")
    print(f"  Correct (±1%)        : {len(correct)}")
    print(f"  Missing in extraction: {missing_ex}")
    print(f"  Accuracy             : {accuracy:.1f}%")

    # ── Colour-coded detail table ─────────────────────────────────────────────
    def _colour(row):
        c = _STATUS_COLOR.get(row["status"], "#ffffff")
        return [f"background: {c}"] * len(row)

    styled = (
        df.sort_values(["period", "json_path"])
        [["period", "field", "ground_truth", "extracted", "status", "rel_err_%"]]
        .reset_index(drop=True)
        .style
        .apply(_colour, axis=1)
        .format({
            "ground_truth": lambda v: f"{v:,.2f}" if v is not None else "—",
            "extracted":    lambda v: f"{v:,.2f}" if v is not None else "—",
            "rel_err_%":    lambda v: f"{v:.2f}" if v is not None else "—",
        })
    )
    display(styled)
