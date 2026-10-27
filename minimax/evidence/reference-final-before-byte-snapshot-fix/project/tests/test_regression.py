import copy

import pytest


def test_default_order(service, tasks):
    assert [task["id"] for task in service(tasks)] == [1, 2, 3, 4, 5]


def test_explicit_none(service, tasks):
    assert service(tasks, status=None) == service(tasks)


def test_pagination(service, tasks):
    assert [task["id"] for task in service(tasks, offset=1, limit=2)] == [2, 3]


def test_default_limit(service):
    tasks = [{"id": i, "status": "todo"} for i in range(30)]
    assert len(service(tasks)) == 20


@pytest.mark.parametrize("kwargs", [{"offset": -1}, {"limit": 0}, {"limit": -1}])
def test_invalid_pagination(service, kwargs):
    with pytest.raises(ValueError):
        service([], **kwargs)


def test_empty(service):
    assert service([]) == []


def test_offset_beyond_end(service, tasks):
    assert service(tasks, offset=100) == []


def test_input_not_mutated(service, tasks):
    before = copy.deepcopy(tasks)
    result = service(tasks)
    result[0]["title"] = "changed output"
    assert tasks == before
