import os
import subprocess
import uuid
import shutil
from lxml import etree as ElementTree
from bs4 import BeautifulSoup
from typing import List, Optional, Tuple

from pathlib import Path
from utils.epub import Epub
from utils.filesystem import Filesystem

from pathlib import Path
from datetime import datetime, timezone
import re
from datetime import timedelta
import shutil
from typing import Optional, Tuple, Dict, Any

JOB_ID_RE = re.compile(
    r"^(?P<pn>\d+)-(?P<stamp>[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]+)$")

SAXON_JAR = os.environ.get("SAXON_JAR")
XSLT_DIR = os.environ.get("XSLT")


def generate_reference_number(production_number: str, source: str) -> str:

    reference_number = f"{production_number}_{source}_{uuid.uuid4().hex[:6]}"
    return reference_number


def remove_file(path: str, logger):
    try:
        os.remove(path)
        logger.info(f"Removed temp file: {path}")
    except Exception as e:
        logger.warning(f"Could not remove temp file: {e}")


def xslt_transform(xhtml_file, logger):
    stylesheets = {
        "prepare-for-braille.xsl": "Tilpasser innhold for punktskrift…",
        "pre-processing.xsl": "Bedre hefteinndeling, fjern tittelside og innholdsfortegnelse, flytte kolofon og opphavsrettside til slutten av boka…",
        "add-table-classes.xsl": "Bedre håndtering av tabeller…",
        "insert-boilerplate.xsl": "Lag ny tittelside og bokinformasjon…"
    }

    input_file = xhtml_file
    temp_files = []

    for sheet, description in stylesheets.items():
        xslt_path = os.path.join(XSLT_DIR, sheet)
        temp_output = input_file + f".{sheet}.tmp"
        command = [
            "java", "-jar", SAXON_JAR,
            "-s:" + input_file,
            "-xsl:" + xslt_path,
            "-o:" + temp_output
        ]
        logger.info(f"XSLT: {sheet} - {description}")
        logger.info("Running XSLT")
        logger.info("Processing  %s", command)

        try:
            result = subprocess.run(
                command, check=True, capture_output=True, text=True)
            logger.info(f"XSLT {sheet} output: {result.stdout}")
        except subprocess.TimeoutExpired:
            logger.error(f"XSLT {sheet} timed out.")
            return {"status": "fail", "error": f"Timeout on {sheet}"}
        except subprocess.CalledProcessError as e:
            logger.error(f"XSLT {sheet} failed: {e.stderr}")
            return {"status": "fail", "error": e.stderr}

        temp_files.append(temp_output)
        input_file = temp_output  # Next stylesheet uses previous output

    # After all stylesheets, return the final output file path
    return {"status": "success", "result": input_file}


def get_guidelines_from_opf(epub_folder, logger):
    # epub = Epub(logger, epub_file)
    # epub_folder = epub_file.asDir()
    logger.info(f"epub_folder: {epub_folder}")
    meta_name_content = None
    meta_name = None
    # Read the package.opf file to determine the guidelines version

    opf_path = None
    for root, _, files in os.walk(epub_folder):
        if "package.opf" in files:
            opf_path = Path(root) / "package.opf"
            break

    if not opf_path:
        logger.error(f"package.opf not found under {epub_folder}")
        return False

    try:

        xml_content = opf_path.read_text(encoding='utf-8')
        soup = BeautifulSoup(xml_content, 'xml')  # Use 'xml' parser

        # Extract content with property 'nordic:guidelines'
        meta_property = soup.find("meta", property="nordic:guidelines")
        meta_property_content = meta_property.text if meta_property else None
        logger.info(
            f"Content of meta with property 'nordic:guidelines': {meta_property_content}")

        # Extract single content with name 'nordic:guidelines'
        meta_name = soup.find("meta", attrs={"name": "nordic:guidelines"})
        meta_name_content = meta_name['content'] if meta_name and "content" in meta_name.attrs else None
        logger.info(
            f"Content of meta with name 'nordic:guidelines': {meta_name_content}")

    except Exception as e:
        logger.error(f"Error reading {opf_path}: {e}")

    if (meta_property_content is not None and meta_property_content == "2020-1") or (meta_name_content is not None and meta_name_content == "2020-1"):
        logger.info("Using 2020-1 guidelines")
        return "2020-1"
    else:
        logger.info("Using 2015-1 guidelines")
    return "2015-1"


def _parse_job_id(name: str):
    """
    Expect job_id like '863440-2025-09-11-110101568350'.
    Returns (production_number, raw_stamp, human_stamp)
    """
    if "-" not in name:
        return None, None, None
    try:
        pn, stamp = name.split("-", 1)
        # Try to parse the timestamp part
        # Example stamp: 2025-09-11-110101568350
        # We split by '-' first three parts = YYYY, MM, DD
        parts = stamp.split("-")
        if len(parts) >= 4:
            yyyy, mm, dd, timechunk = parts[0], parts[1], parts[2], parts[3]
            # timechunk is like 110101568350 (HHMMSS######)
            hh, mi, ss = timechunk[0:2], timechunk[2:4], timechunk[4:6]
            # Build datetime string
            dt_str = f"{yyyy}-{mm}-{dd} {hh}:{mi}:{ss}"
            dt_obj = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            human = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
        else:
            human = stamp
        return pn, stamp, human
    except Exception:
        return None, None, None


def _dir_stats(dir_path: Path) -> Tuple[int, int]:
    """Count files and total size (bytes) recursively under dir_path."""
    files, size = 0, 0
    for p in dir_path.rglob("*"):
        if p.is_file():
            files += 1
            try:
                size += p.stat().st_size
            except Exception:
                pass
    return files, size


def human_size(num_bytes: int) -> str:
    """Convert bytes into a human-readable string (KB, MB, GB...)."""
    step_unit = 1024.0
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < step_unit:
            return f"{size:.2f} {unit}"
        size /= step_unit
    return f"{size:.2f} PB"


def summarize_artifacts(ARTIFACTS_ROOT: Path) -> Dict[str, Any]:
    """
    - total_artifacts: number of job folders under ARTIFACTS_ROOT
    - items: list per job folder with parsed production_number and date/time part
    """
    root = Path(ARTIFACTS_ROOT)
    total_artifacts = 0
    total_size_all = 0
    items = []

    if not root.exists():
        return {
            "total_artifacts": 0,
            "total_size": "0 B",
            "items": [],
            "root": str(root),
        }

    for entry in root.iterdir():                    # <-- iterate children
        if not entry.is_dir():
            continue
        total_artifacts += 1
        job_id = entry.name
        pn, raw_stamp, human_stamp = _parse_job_id(job_id)
        file_count, total_size = _dir_stats(entry)
        total_size_all += total_size
        items.append({
            "job_id": job_id,
            "production_number": pn,
            "date_time_raw": raw_stamp,     # original string (for reference)
            "date_time": human_stamp,                   # e.g. 2025-09-11-110101568350
            "files": file_count,
            "bytes": human_size(total_size),
        })

    # sort newest first
    items.sort(key=lambda x: x["date_time_raw"], reverse=True)
    return {
        "root": str(root.resolve()),
        "total_artifacts": total_artifacts,
        "total_size": human_size(total_size_all),
        "items": items,
    }


def _stamp_to_datetime_utc(raw_stamp: str, logger) -> Optional[datetime]:
    """
    raw_stamp like '2025-09-11-110101568350' -> datetime(2025,09,11,11,01,01, tz=UTC)
    We ignore microseconds part (the trailing digits after seconds).
    """
    try:
        parts = raw_stamp.split("-")
        if len(parts) < 4:
            return None
        yyyy, mm, dd, timechunk = parts[0], parts[1], parts[2], parts[3]
        if len(timechunk) < 6:
            return None
        hh, mi, ss = timechunk[0:2], timechunk[2:4], timechunk[4:6]
        dt_str = f"{yyyy}-{mm}-{dd} {hh}:{mi}:{ss}"
        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        logger("(Failed to parse stamp %r", raw_stamp)
        return None


def _should_delete(job_dir: Path, now_utc: datetime, ARTIFACTS_RETENTION_HOURS, logger) -> bool:
    """
    Decide if job_dir should be deleted based on job_id embedded time.
    Fallback: if name can't be parsed, use mtime.
    Never delete the current running job dir, if known.
    """
    # Avoid deleting the currently running job (if we have its job_id)
    # current_job_id = (app.state.current_job or {}).get("job_id")
    # if current_job_id and job_dir.name == current_job_id:
    #    return False

    pn, raw, human_stamp = _parse_job_id(job_dir.name)

    if raw:
        dt = _stamp_to_datetime_utc(raw, logger)
        if dt:
            age = now_utc - dt
            logger.info(f"Artifact: {job_dir.name} age ----- {age}")

            return age > timedelta(hours=ARTIFACTS_RETENTION_HOURS)
    # Fallback to filesystem mtime if parsing fails
    try:
        mtime = datetime.fromtimestamp(
            job_dir.stat().st_mtime, tz=timezone.utc)
        age = now_utc - mtime
        return age > timedelta(hours=ARTIFACTS_RETENTION_HOURS)
    except Exception:
        # If we cannot stat, be conservative and do not delete
        return False


def cleanup_artifacts_once(ARTIFACTS_DIR, ARTIFACTS_RETENTION_HOURS, logger) -> Dict[str, Any]:
    """
    Run one cleanup pass. Returns stats dict.
    """
    stats = {"checked": 0, "deleted": 0, "errors": 0,
             "kept": 0, "root": str(ARTIFACTS_DIR)}
    now_utc = datetime.now(timezone.utc)

    if not ARTIFACTS_DIR.exists():
        return stats

    for entry in ARTIFACTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        stats["checked"] += 1
        try:
            if _should_delete(entry, now_utc, ARTIFACTS_RETENTION_HOURS, logger):
                shutil.rmtree(entry, ignore_errors=False)
                stats["deleted"] += 1
                logger.info("Artifacts cleanup: deleted %s", entry)
            else:
                stats["kept"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.warning(
                "Artifacts cleanup: failed to delete %s: %r", entry, e)

    return stats
