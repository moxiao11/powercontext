import copy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def service():
    path = Path(__file__).resolve().parents[1] / "taskboard.py"
    spec = importlib.util.spec_from_file_location("taskboard_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.list_tasks


@pytest.fixture
def tasks():
    return copy.deepcopy([
        {"id": 5, "title": "publish", "status": "done"},
        {"id": 2, "title": "design", "status": "doing"},
        {"id": 4, "title": "review", "status": "done"},
        {"id": 1, "title": "scope", "status": "todo"},
        {"id": 3, "title": "implement", "status": "todo"},
    ])
