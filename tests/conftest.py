from __future__ import annotations

import os


TEST_SCHEMA = os.environ.get("PYTEST_POSTGRES_SCHEMA", "test_elections")

if TEST_SCHEMA in {"elections", "public"}:
    raise RuntimeError(f"Refusing to run tests against schema: {TEST_SCHEMA}")

os.environ["POSTGRES_SCHEMA"] = TEST_SCHEMA
