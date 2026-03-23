"""
Container API — creates connections that can be used to start the processes within the container.
"""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Local
from bok2docx import convert
from config import logger

# In-built
import io, zipfile
import json
import os
import tempfile
import asyncio
import shutil
from typing import Optional
from types import SimpleNamespace
from pathlib import Path

# Pip installed
from fastapi import FastAPI, UploadFile
from fastapi.responses import Response

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------

app = FastAPI(title="Bok to Docx")

# -----------------------------------------------------------------------------
# API methods
# -----------------------------------------------------------------------------

current_job = {"status": "Idle", "step": None} # step returns "x/y - step name" meaning currently on x out of y steps

@app.get("/health")
async def health():
    """Returns health state of container."""
    return {"health": "ok"}


@app.post("/process")
async def process(file: UploadFile, config: UploadFile, file2: Optional[UploadFile] = None):
    """
    Receives files and config from controller, runs module processing,
    and returns results as a zip. 

    Args:
        file: Primary file to process (multipart form upload).
        config: JSON config file with module parameters (multipart form upload).
        file2: Optional secondary file (e.g. PDF reference for validation).

    Returns:
        Response: Zip containing up to three entries:
            - processed file (original filename),
            - log.json (list of log records from processing),
            - report file (extension defined by module).
    """
    # --- Staging area 1: Unpack ---
    # Where you prepare the module input the way it needs it
    try:
        module_name = os.getenv("MODULE_NAME", "unknown")
        logger.info(f"/process inside {module_name} started")

        config_data = json.loads(await config.read())

        def to_bool(val):
            return str(val).lower() == "true"
        
        def trinn_to_grade(trinn_list):
            mapping = {
                "Barnehage": 0, "1.kl": 1, "2.kl": 2, "3.kl": 3,
                "4.kl": 4, "5.kl": 5, "6.kl": 6, "7.kl": 7,
                "8.kl": 8, "9.kl": 9, "10.kl": 10,
                "Vg1": 11, "Vg2": 12, "Vg3": 13
            }
            grades = [mapping[t] for t in trinn_list if t in mapping]
            return max(grades) if grades else None

        grade=trinn_to_grade(config_data.get("trinn", []))
        mathematics=to_bool(config_data.get("mathematics", False))
        science=to_bool(config_data.get("science", False))
        no_excel=to_bool(config_data.get("no_excel", True))
        book=to_bool(config_data.get("book", False))
        file_bytes = await file.read()
        filename = file.filename

        tmp_dir = tempfile.mkdtemp()
        input_path = Path(tmp_dir) / filename
        input_path.write_bytes(file_bytes)
        job_dir = Path(tmp_dir) / "output"
        job_dir.mkdir()

        args = SimpleNamespace(
            input=str(input_path),
            output=None,
            reference_docx=None,
            pandoc_args=[],
            stdout=False,
            job_dir=job_dir,
            production_number=Path(filename).stem,
            logger=logger,
            grade=grade,                                          # P: to be passed in from trinn
            mathematics=mathematics,
            science=science,
            no_excel=no_excel,
            book=book,
            toc_levels=None,                                     # P: inactive
            verbose=0,                                           # P: inactive
            link_footnotes=False,                                # P: inactive
            p_length=None,                                       # P: inactive
            index=False,                                         # P: inactive
        )

        # --- Process ---
        return_code = await asyncio.to_thread(convert, args)
        log_records = [{
            "level": "INFO" if return_code == 0 else "ERROR",
            "message": f"convert() returned {return_code}",
            "timestamp": None
        }]  # F: bok2docx uses its own logger — wire up ListHandler here if needed
        report = None
        report_extension = None

        # --- Staging area 2: Pack zip ---
        module_name = os.getenv("MODULE_NAME", "unknown")
        module_version = os.getenv(f"{module_name.upper()}_VERSION", "unknown")
            
        docx_path = job_dir / f"{args.production_number}.docx"
        result_bytes = docx_path.read_bytes() if docx_path.exists() else None
        filename = docx_path.name  # so zip entry has .docx extension
        log_records.insert(0, {
            "level": "INFO",
            "message": module_version,
            "timestamp": None
        })
        manifest = {
            "primary": filename,
            "secondary": None,
            "log": "log.json",
            "report":  None
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            if result_bytes:
                zf.writestr(filename, result_bytes)
            if log_records:
                zf.writestr("log.json", json.dumps(log_records))
            if report:
                zf.writestr(f"report{report_extension or '.bin'}", report)
        buf.seek(0)
    
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info(f"/process inside {module_name} returns")
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}.zip"'}
    )

@app.get("/status")
async def status():
    """Returns process status of container."""
    return current_job