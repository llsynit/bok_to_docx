"""
Container configuration.
"""

# Built-in
import logging
import sys

def setup_logger():
    """Defines logger configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
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