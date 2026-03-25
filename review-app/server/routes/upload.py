import io
import json
import os
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from ..config import get_client, PDF_VOLUME_PATH, RESULTS_TABLE, OCR_ENDPOINT

router = APIRouter()

# In-memory status tracker (resets on app restart; sufficient for this demo)
_status: dict[str, dict] = {}

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "output_schema.json")

with open(_SCHEMA_PATH) as _f:
    _OUTPUT_SCHEMA = json.load(_f)

_SCHEMA_STR = json.dumps(_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)

_INSTRUCTIONS = (
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

_PROMPT_PREFIX = f"""Você é um especialista em análise de demonstrações financeiras brasileiras.
Sua tarefa é extrair informações estruturadas de documentos financeiros (Balanço Patrimonial e DRE).

Instruções adicionais:
{_INSTRUCTIONS}

Retorne SOMENTE um JSON array válido seguindo exatamente o schema fornecido. Sem texto adicional.

Extraia as informações financeiras do seguinte documento e retorne um JSON seguindo exatamente este schema:

{_SCHEMA_STR}

DOCUMENTO:
"""


def _extract_text_from_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def _call_ocr_endpoint(text: str, client) -> list:
    """Call FMAPI endpoint via SDK — WorkspaceClient handles M2M auth natively."""
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
    full_prompt = _PROMPT_PREFIX + text
    response = client.serving_endpoints.query(
        name=OCR_ENDPOINT,
        messages=[ChatMessage(role=ChatMessageRole.USER, content=full_prompt)],
        max_tokens=8192,
    )
    result_text = response.choices[0].message.content
    r = json.loads(result_text)
    if isinstance(r, dict):
        r = [r]
    return r


def _save_result(document_name: str, results: list, client):
    from ..db import execute_sql
    if isinstance(results, dict):
        results = [results]

    def _get(obj, path: str):
        parts = path.split(".")
        cur = obj
        for p in parts:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(p)
        return cur

    for result in results:
        extracted_json = json.dumps(result, ensure_ascii=False)
        params = [
            {"name": "doc",  "value": document_name},
            {"name": "te",   "value": str(_get(result, "tipo_entidade") or "")},
            {"name": "per",  "value": str(_get(result, "identificacao.periodo") or "")},
            {"name": "json", "value": extracted_json},
            {"name": "rs",   "value": str(_get(result, "razao_social") or "")},
            {"name": "cnpj", "value": str(_get(result, "cnpj") or "")},
            {"name": "at",   "value": str(_get(result, "ativo_total") or "")},
            {"name": "ll",   "value": str(_get(result, "dre.lucro_liquido") or "")},
        ]
        execute_sql(f"""
            MERGE INTO {RESULTS_TABLE} AS t
            USING (SELECT :doc AS document_name, :te AS tipo_entidade, :per AS periodo) AS s
              ON  t.document_name = s.document_name
              AND t.tipo_entidade = s.tipo_entidade
              AND t.periodo       = s.periodo
            WHEN MATCHED THEN UPDATE SET
                extracted_json = :json,
                razao_social   = :rs,
                cnpj           = :cnpj,
                ativo_total    = TRY_CAST(:at AS DOUBLE),
                lucro_liquido  = TRY_CAST(:ll AS DOUBLE)
            WHEN NOT MATCHED THEN INSERT
                (document_name, tipo_entidade, periodo, extracted_json,
                 razao_social, cnpj, ativo_total, lucro_liquido)
            VALUES (:doc, :te, :per, :json, :rs, :cnpj,
                    TRY_CAST(:at AS DOUBLE), TRY_CAST(:ll AS DOUBLE))
        """, params)


def _process_background(document_name: str, text: str):
    """Runs OCR + save in background so the upload response returns immediately."""
    try:
        _status[document_name] = {"status": "processing", "step": "ocr"}
        client = get_client()
        results = _call_ocr_endpoint(text, client)
        _status[document_name] = {"status": "processing", "step": "saving"}
        _save_result(document_name, results, client)
        _status[document_name] = {"status": "done", "records": len(results)}
    except Exception as e:
        _status[document_name] = {"status": "error", "detail": str(e)}


@router.post("/documents/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Apenas arquivos PDF são aceitos.")

    data = await file.read()
    document_name = file.filename
    client = get_client()

    # 1. Save PDF to volume (fast)
    volume_path = f"{PDF_VOLUME_PATH}/{document_name}"
    try:
        client.files.upload(volume_path, io.BytesIO(data), overwrite=True)
    except Exception as e:
        raise HTTPException(500, f"Erro ao salvar PDF no volume: {e}")

    # 2. Extract text (fast, local)
    try:
        text = _extract_text_from_pdf(data)
    except Exception as e:
        raise HTTPException(500, f"Erro ao extrair texto do PDF: {e}")

    if not text.strip():
        raise HTTPException(422, "Não foi possível extrair texto do PDF. O arquivo pode ser uma imagem escaneada sem OCR.")

    # 3. Queue OCR in background and return immediately
    _status[document_name] = {"status": "processing", "step": "ocr"}
    background_tasks.add_task(_process_background, document_name, text)

    return {"document_name": document_name, "status": "processing"}


@router.get("/documents/{document_name}/status")
def get_upload_status(document_name: str):
    return _status.get(document_name, {"status": "unknown"})
