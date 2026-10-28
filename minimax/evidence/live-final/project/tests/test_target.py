import copy

import pytest


@pytest.mark.parametrize("status,expected", [("todo", [1, 3]), ("doing", [2]), ("done", [4, 5])])
def test_status_filter(service, tasks, status, expected):
    assert [task["id"] for task in service(tasks, status=status)] == expected


@pytest.mark.parametrize("status", ["unknown", "", "DONE"])
def test_invalid_status(service, tasks, status):
    with pytest.raises(ValueError, match="status"):
        service(tasks, status=status)


def test_filter_before_pagination(service, tasks):
    assert [task["id"] for task in service(tasks, status="done", offset=1, limit=1)] == [5]


def test_no_matches(service):
    assert service([{"id": 1, "status": "todo"}], status="done") == []


def test_filter_keeps_input_unchanged(service, tasks):
    before = copy.deepcopy(tasks)
    result = service(tasks, status="todo")
    result[0]["title"] = "changed output"
    assert tasks == before
