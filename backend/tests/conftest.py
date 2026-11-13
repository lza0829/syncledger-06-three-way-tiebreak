from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="syncledger-test-")
os.environ["DATA_DIR"] = _TEST_DATA_DIR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.seed import init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_database():
    init_db()
