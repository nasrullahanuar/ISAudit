from decimal import Decimal
from pathlib import Path

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator

from services.transaction_uploads import (
    MAX_UPLOAD_BYTES,
    UploadValidationError,
    parse_transactions,
)


BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DATA_PATH = BASE_DIR / "data" / "sample_transactions.csv"
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME = "gemma3:latest"

app = FastAPI(title="AI Audit System")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Uploaded records stay in memory and are replaced only after a valid upload.
TRANSACTIONS: list[dict] = []


class AuditQuestion(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)

    @validator("question", pre=True)
    def trim_question(cls, value):
        return value.strip() if isinstance(value, str) else value


@app.get("/", response_class=FileResponse)
def home() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/dashboard", response_class=FileResponse)
def dashboard() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "dashboard.html")


@app.get("/sample_transactions.csv", response_class=FileResponse)
def sample_transactions() -> FileResponse:
    return FileResponse(
        SAMPLE_DATA_PATH,
        media_type="text/csv",
        filename="sample_transactions.csv",
    )


def _dashboard_summary() -> dict:
    total_amount = sum(
        (Decimal(transaction["amount"]) for transaction in TRANSACTIONS),
        Decimal("0"),
    )
    return {
        "total_transactions": len(TRANSACTIONS),
        "vendor_count": len({transaction["vendor_name"] for transaction in TRANSACTIONS}),
        "total_amount_myr": format(total_amount, ",.2f"),
    }


@app.get("/api/dashboard")
def dashboard_data() -> dict:
    return {
        "summary": _dashboard_summary(),
        "recent_transactions": list(reversed(TRANSACTIONS[-10:])),
    }


@app.post("/api/transactions")
async def upload_transactions(file: UploadFile = File(...)) -> dict:
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        transactions = parse_transactions(file.filename or "", content)
    except UploadValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        await file.close()

    TRANSACTIONS.clear()
    TRANSACTIONS.extend(transactions)
    return {
        "message": f"Loaded {len(transactions)} transactions. They are stored in memory for this session.",
        "summary": _dashboard_summary(),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask-ai")
def ask_ai(data: AuditQuestion) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "You are an AI audit assistant. Explain audit and accounting "
                "concepts clearly and professionally. Do not invent financial "
                "evidence or claim to have examined documents that were not "
                "provided. State uncertainty where appropriate. Your answers "
                "are preliminary guidance and require review by a human auditor."
            ),
        },
        {"role": "user", "content": data.question},
    ]

    try:
        result = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=180,
        )
        result.raise_for_status()
    except requests.exceptions.Timeout as error:
        raise HTTPException(
            status_code=504,
            detail="Ollama took too long to respond. Please try again.",
        ) from error
    except requests.exceptions.ConnectionError as error:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to Ollama. Check that it is running locally.",
        ) from error
    except requests.exceptions.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama returned an error (HTTP {error.response.status_code}).",
        ) from error
    except requests.exceptions.RequestException as error:
        raise HTTPException(
            status_code=502,
            detail="The request to Ollama failed. Please try again.",
        ) from error

    try:
        payload = result.json()
    except ValueError as error:
        raise HTTPException(
            status_code=502,
            detail="Ollama returned an invalid response.",
        ) from error

    message = payload.get("message") if isinstance(payload, dict) else None
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise HTTPException(
            status_code=502,
            detail="Ollama returned an empty or invalid response.",
        )

    return {"answer": answer.strip()}
