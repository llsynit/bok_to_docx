from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse

import io
import os

import bok2docx

APP_NAME = os.getenv("MODULE_NAME", "bok_to_docx")
PORT = int(os.getenv("PORT", "9004"))

app = FastAPI(title=APP_NAME, version="0.1.0")

@app.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"

@app.post("/run")
async def run(
    file: UploadFile = File(..., description="XHTML (.xhtml) fra forrige steg"),
    output_filename: Optional[str] = Form("output.docx", description="Ønsket filnavn (.docx)"),
):
    if not output_filename.lower().endswith(".docx"):
        output_filename += ".docx"

    # Les inn hele inputen
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Tom inputfil")

    try:
        docx_bytes = bok2docx.xhtml_to_docx(data, output_filename)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Konvertering feilet: {e}")

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{Path(output_filename).name}"'
        },
    )
