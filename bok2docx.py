from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

# Hjelpemoduler fra repoet – hvis de finnes bruker vi dem,
# ellers faller vi tilbake til ren pandoc-CLI.
try:
    import pandoc_wrapper  # type: ignore
except Exception:
    pandoc_wrapper = None  # fallback

try:
    import clean  # type: ignore
except Exception:
    clean = None  # fallback

try:
    import prepareXdocx  # type: ignore
except Exception:
    prepareXdocx = None  # fallback


def _run_pandoc_cli(infile: Path, outfile: Path) -> None:
    """Kjør pandoc direkte for HTML → DOCX."""
    cmd = [
        "pandoc",
        str(infile),
        "-f", "html",
        "-t", "docx",
        "-o", str(outfile),
    ]
    subprocess.run(cmd, check=True)


def _run_pandoc(infile: Path, outfile: Path) -> None:
    """Foretrukket: bruk pandoc_wrapper hvis tilgjengelig, ellers CLI."""
    if pandoc_wrapper and hasattr(pandoc_wrapper, "run_pandoc"):
        # Mange varianter finnes – prøv enkel signatur, ellers fall tilbake
        try:
            pandoc_wrapper.run_pandoc(
                input_path=str(infile),
                output_path=str(outfile),
                from_fmt="html",
                to_fmt="docx",
            )
            return
        except TypeError:
            # annen signatur i ditt repo?
            pandoc_wrapper.run_pandoc(str(infile), str(outfile), "html", "docx")
            return
    # Fallback
    _run_pandoc_cli(infile, outfile)


def _optional_prepare(docx_path: Path) -> None:
    if prepareXdocx and hasattr(prepareXdocx, "prepare_docx"):
        try:
            prepareXdocx.prepare_docx(str(docx_path))
        except Exception:
            # ikke fatal
            pass


def _optional_clean(docx_path: Path) -> None:
    if clean:
        # Støtt både modul- og funksjonsnavn som kan finnes i repoet
        for fn in ("clean_docx_file", "clean", "clean_docx"):
            f = getattr(clean, fn, None)
            if callable(f):
                try:
                    f(str(docx_path))
                except Exception:
                    pass
                break


def xhtml_to_docx(xhtml_bytes: bytes, output_filename: Optional[str] = "output.docx") -> bytes:
    """
    Konverter XHTML/HTML → DOCX med pandoc, og kjør ev. prepare/clean-trinn dersom modulene finnes.
    Returnerer DOCX-bytes.
    """
    if not output_filename or not output_filename.lower().endswith(".docx"):
        output_filename = (output_filename or "output") + ".docx"

    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        in_html = tmpdir / "input.xhtml"
        out_docx = tmpdir / Path(output_filename).name

        in_html.write_bytes(xhtml_bytes)

        _run_pandoc(in_html, out_docx)
        if not out_docx.exists():
            raise RuntimeError("Pandoc genererte ingen DOCX-fil")

        # Valgfri post-prosessering
        _optional_prepare(out_docx)
        _optional_clean(out_docx)

        return out_docx.read_bytes()
