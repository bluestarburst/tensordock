"""
Centralized logging setup for TensorDock server.
"""
import logging
import datetime
import os
import tempfile
from typing import Any, Optional, Dict


def _resolve_log_dir() -> str:
    """Determine a writable log directory respecting container constraints."""
    candidates = []

    env_dir = os.environ.get("TD_LOG_DIR")
    if env_dir:
        candidates.append(env_dir)

    # Fallback to system temporary directory (tmpfs inside container)
    candidates.append(os.path.join(tempfile.gettempdir(), "tensordock-logs"))

    for directory in candidates:
        if not directory:
            continue
        try:
            os.makedirs(directory, exist_ok=True)
            return directory
        except OSError:
            continue

    # Last resort: current working directory (may still fail but nothing else left)
    return os.getcwd()


def setup_logging(level: str = "INFO", log_file: str = "tensordock_server.log") -> logging.Logger:
    """Setup logging configuration with file output."""
    log_dir = _resolve_log_dir()
    log_path = os.path.join(log_dir, log_file)

    # Configure logging to write to both file and console
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S',
        handlers=[
            logging.FileHandler(log_path, mode='a', encoding='utf-8'),
            logging.StreamHandler()  # Console output
        ]
    )

    logger = logging.getLogger("tensordock")
    logger.info(f"Logging initialized - output will be written to: {log_path}")

    return logger


def debug_log(message: str, data: Optional[Any] = None, level: str = "INFO") -> None:
    """
    Enhanced debug logging with structured data.
    
    Args:
        message: The log message
        data: Optional data to log
        level: Log level (INFO, DEBUG, WARNING, ERROR)
    """
    timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    if data:
        if isinstance(data, dict):
            # Pretty print complex data structures
            import json
            data_str = json.dumps(data, indent=2, default=str)
            logging.log(
                getattr(logging, level.upper()),
                f"[{timestamp}] {message}\nData: {data_str}"
            )
        else:
            logging.log(
                getattr(logging, level.upper()),
                f"[{timestamp}] {message} - {data}"
            )
    else:
        logging.log(
            getattr(logging, level.upper()),
            f"[{timestamp}] {message}"
        )


class LoggerMixin:
    """Mixin class to add logging capabilities to other classes."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
    
    def log_debug(self, message: str, data: Optional[Any] = None):
        """Log debug message."""
        debug_log(message, data, "DEBUG")
    
    def log_info(self, message: str, data: Optional[Any] = None):
        """Log info message."""
        debug_log(message, data, "INFO")
    
    def log_warning(self, message: str, data: Optional[Any] = None):
        """Log warning message."""
        debug_log(message, data, "WARNING")
    
    def log_error(self, message: str, data: Optional[Any] = None):
        """Log error message."""
        debug_log(message, data, "ERROR")
