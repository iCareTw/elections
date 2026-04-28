from __future__ import annotations

import logging
import logging.handlers
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
