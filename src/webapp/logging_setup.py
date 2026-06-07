from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    ops_handler = logging.handlers.RotatingFileHandler(
        log_dir / "operations.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    ops_handler.setFormatter(fmt)
    ops_handler.setLevel(logging.INFO)

    err_handler = logging.handlers.RotatingFileHandler(
        log_dir / "errors.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    err_handler.setFormatter(fmt)
    err_handler.setLevel(logging.ERROR)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(ops_handler)
    root.addHandler(err_handler)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    import os
    schema = os.environ.get("POSTGRES_SCHEMA", "")
    log_prefix = "test" if schema.startswith("test_") else "candidates"
    candidates_handler = logging.FileHandler(
        log_dir / f"{timestamp}_{log_prefix}.log", encoding="utf-8"
    )
    candidates_handler.setFormatter(fmt)
    candidates_handler.setLevel(logging.INFO)

    clog = logging.getLogger("candidates")
    clog.addHandler(candidates_handler)
    clog.propagate = False
