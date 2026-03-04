"""
Financial Extraction Agent
==========================
DSPy-based structured extraction wrapped as an MLflow pyfunc model.

Input  : {"messages": [{"role": "user", "content": "<OCR text>"}]}
         (standard ai_query / chat endpoint format)
Output : JSON string matching the financial extraction schema
         (metadados_empresa + relatorios array)

The agent uses DSPy ChainOfThought with the FinancialExtraction signature,
backed by a Databricks Foundation Model (configurable via EXTRACTION_LM env var).
"""

import os

import dspy
import mlflow


# ---------------------------------------------------------------------------
# DSPy signature
# ---------------------------------------------------------------------------
class FinancialExtraction(dspy.Signature):
    """
    Extract structured financial data from a Brazilian financial statement
    (Balanço Patrimonial + DRE).  Return valid JSON matching the schema exactly.
    Use null for any field that is not present in the document.
    Only include periods that are explicitly stated in the document.
    """

    document: str = dspy.InputField(
        desc="Full OCR markdown text of the financial statement"
    )
    json_output: str = dspy.OutputField(
        desc=(
            "JSON string with two top-level keys: "
            "'metadados_empresa' (razao_social, cnpj) and "
            "'relatorios' (array of periodo/balanco/dre objects)"
        )
    )


class ExtractionModule(dspy.Module):
    def __init__(self):
        self.extract = dspy.ChainOfThought(FinancialExtraction)

    def forward(self, document: str) -> str:
        result = self.extract(document=document)
        return result.json_output


# ---------------------------------------------------------------------------
# MLflow pyfunc wrapper
# ---------------------------------------------------------------------------
class ExtractionAgent(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        lm_name = os.environ.get(
            "EXTRACTION_LM", "databricks/databricks-claude-3-7-sonnet"
        )
        lm = dspy.LM(lm_name)
        dspy.configure(lm=lm)
        self.module = ExtractionModule()

    def predict(self, context, model_input, params=None):
        # Normalise input: accept DataFrame, list of dicts, or single dict
        if hasattr(model_input, "to_dict"):
            rows = model_input.to_dict(orient="records")
        elif isinstance(model_input, list):
            rows = model_input
        else:
            rows = [model_input]

        results = []
        for row in rows:
            # Extract text from chat-style {"messages": [...]} envelope
            if isinstance(row, dict) and "messages" in row:
                messages = row["messages"]
                text = messages[-1]["content"] if messages else ""
            else:
                text = str(row)
            results.append(self.module(document=text))
        return results


# Register with MLflow so log_model(python_model="agent.py") picks it up
mlflow.models.set_model(ExtractionAgent())
