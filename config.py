"""
Container configuration.
"""

# Built-in
import logging
import sys
import os

def setup_logger():
    """
    Configures and returns the module-level logger.

    Outputs INFO-level logs to stdout in timestamped format.
    """
    module_log_level = os.getenv("MODULE_NAME", "unknown").upper() + "_LOG_LEVEL" # Pulls log level from .env
    level = int(os.getenv(module_log_level, logging.INFO))
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logging.getLogger("python_multipart.multipart").setLevel(logging.WARNING) # Supresses DEBUG prints from python-multipart
    return logging.getLogger(__name__)

logger = setup_logger()

class ListHandler(logging.Handler):
    """Captures log records into a list for returning to controller."""
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append({
            "level": record.levelname,
            "message": record.getMessage(),
            "timestamp": record.created,
        })