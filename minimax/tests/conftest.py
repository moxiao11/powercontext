import shutil
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(BASE / "examples" / "taskboard" / "project", root,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return root
