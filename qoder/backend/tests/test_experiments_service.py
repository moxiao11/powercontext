"""Experiment records: searchable text, row decoding, comparison, best-by-metric, import guard."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.services.experiments import (
    ExperimentError,
    _row_to_dict,
    _searchable_text,
    best_experiment,
    compare_experiments,
    create_experiment,
    import_metrics_json,
)


def test_searchable_text_covers_every_text_field() -> None:
    text = _searchable_text(
        {
            "name": "HSM v2",
            "objective": "验证全局外观嵌入",
            "hypothesis": "同类物体嵌入可区分",
            "method": "重识别合并",
            "dataset": "EQA-Long",
            "result_summary": "准确率下降到 53.9%",
            "issues": "同一物体被拆成多条",
            "failure_reason": "阈值 0.85 过严",
            "next_steps": "改用房间 ID 硬约束",
            "log_markdown": "## 训练日志",
            "model_config": {"lr": 0.001},
        }
    )
    for fragment in (
        "HSM v2",
        "验证全局外观嵌入",
        "EQA-Long",
        "53.9%",
        "阈值 0.85 过严",
        "改用房间 ID 硬约束",
        "## 训练日志",
        '"lr": 0.001',
    ):
        assert fragment in text


def test_searchable_text_skips_missing_fields() -> None:
    assert _searchable_text({"name": "只有名字", "objective": None}) == "只有名字"


def test_row_to_dict_decodes_json_columns_and_drops_the_index_payload() -> None:
    row = _row_to_dict(
        {
            "experiment_id": "exp_1",
            "metrics": '{"accuracy": 58.7}',
            "model_config": '{"lr": 0.001}',
            "searchable_text": "内部索引字段",
            "created_at": datetime(2026, 10, 20, 9, 30),
            "updated_at": datetime(2026, 10, 21, 9, 30),
        }
    )
    assert row["metrics"] == {"accuracy": 58.7}
    assert row["model_config"] == {"lr": 0.001}
    assert "searchable_text" not in row
    assert row["created_at"] == "2026-10-20T09:30:00"


def test_row_to_dict_keeps_malformed_json_as_text() -> None:
    row = _row_to_dict({"metrics": "{not json", "model_config": None})
    assert row["metrics"] == "{not json"
    assert row["model_config"] is None


def test_compare_experiments_reports_field_and_metric_differences() -> None:
    left = {
        "experiment_id": "exp_1",
        "name": "HSM v1",
        "status": "completed",
        "dataset": "EQA-Long",
        "metrics": {"accuracy": 58.7, "vram_gb": 4.2},
    }
    right = {
        "experiment_id": "exp_2",
        "name": "HSM v2",
        "status": "abandoned",
        "dataset": "EQA-Long",
        "metrics": {"accuracy": 53.9, "vram_gb": 4.6, "count_error": 12},
    }

    result = compare_experiments(left, right)

    assert result["left"] == {"experiment_id": "exp_1", "name": "HSM v1"}
    assert result["right"] == {"experiment_id": "exp_2", "name": "HSM v2"}
    changed = {item["field"]: item for item in result["differences"]}
    assert set(changed) == {"name", "status"}
    assert changed["status"]["right"] == "abandoned"
    assert "dataset" not in changed

    deltas = {item["metric"]: item for item in result["metric_deltas"]}
    assert deltas["accuracy"]["delta"] == pytest.approx(-4.8)
    assert deltas["vram_gb"]["delta"] == pytest.approx(0.4)
    # A metric that only exists on one side has no delta, and must not be shown as 0.
    assert deltas["count_error"] == {"metric": "count_error", "left": None, "right": 12, "delta": None}


def test_best_experiment_honours_direction() -> None:
    experiments = [
        {"experiment_id": "exp_1", "metrics": {"accuracy": 58.7, "vram_gb": 4.2}},
        {"experiment_id": "exp_2", "metrics": {"accuracy": 53.9, "vram_gb": 11.8}},
        {"experiment_id": "exp_3", "metrics": None},
    ]
    assert best_experiment(experiments, "accuracy")["experiment_id"] == "exp_1"
    assert best_experiment(experiments, "accuracy", higher_is_better=False)["experiment_id"] == "exp_2"
    assert best_experiment(experiments, "vram_gb", higher_is_better=False)["experiment_id"] == "exp_1"


def test_best_experiment_returns_none_when_metric_is_absent() -> None:
    assert best_experiment([{"experiment_id": "exp_1", "metrics": {"accuracy": 1.0}}], "latency") is None
    assert best_experiment([], "accuracy") is None


def test_best_experiment_ignores_non_numeric_metrics() -> None:
    experiments = [
        {"experiment_id": "exp_1", "metrics": {"accuracy": "n/a"}},
        {"experiment_id": "exp_2", "metrics": {"accuracy": 0.4}},
    ]
    assert best_experiment(experiments, "accuracy")["experiment_id"] == "exp_2"


async def test_create_experiment_generates_ids_and_indexes_searchable_text(fake_db) -> None:
    record = await create_experiment(
        fake_db,
        {
            "project_id": "prj_1",
            "name": "HSM v1",
            "objective": "物体摘要记忆",
            "metrics": {"accuracy": 58.7},
            "model_config": {"lr": 0.001},
            "status": "completed",
        },
    )

    assert record["experiment_id"].startswith("exp_")
    assert record["metrics"] == {"accuracy": 58.7}
    assert record["model_config"] == {"lr": 0.001}
    assert record["status"] == "completed"

    sql, params = fake_db.statements[0]
    assert sql.startswith("INSERT INTO lt_experiments")
    # Every value is bound as a parameter; nothing is interpolated into the statement.
    assert sql.count("%s") == len(params)
    assert "%" not in sql.replace("%s", "")
    assert "HSM v1" in params
    assert '{"accuracy": 58.7}' in params
    assert any("物体摘要记忆" in str(param) for param in params)


async def test_create_experiment_defaults_status_to_planned(fake_db) -> None:
    record = await create_experiment(fake_db, {"project_id": "prj_1", "name": "空实验"})
    assert record["status"] == "planned"
    assert record["metrics"] is None


async def test_import_metrics_json_rejects_records_from_another_project(fake_db) -> None:
    with pytest.raises(ExperimentError, match="must belong to the target project"):
        await import_metrics_json(fake_db, "prj_1", [{"name": "外部记录", "project_id": "prj_other"}])


async def test_import_metrics_json_requires_a_name(fake_db) -> None:
    with pytest.raises(ExperimentError, match="needs at least a 'name'"):
        await import_metrics_json(fake_db, "prj_1", [{"metrics": {"accuracy": 1.0}}])


async def test_import_metrics_json_stamps_the_target_project(fake_db) -> None:
    created = await import_metrics_json(
        fake_db, "prj_1", [{"name": "导入实验", "metrics": {"accuracy": 0.5}}]
    )
    assert len(created) == 1
    assert created[0]["project_id"] == "prj_1"
