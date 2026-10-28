# 样例资料与授权

本目录的论文笔记、实验数字与研究计划均为原创测试数据，不对应真实科研结果、论文结论或用户使用效果。
全部样例以 CC0-1.0 提供，可为比赛验证复制和分发。

- `papers/*.md`：三个 EQA / 3D 场景记忆主题示例文档。
- `papers/sample-pdf-eqa.pdf`：两页原创英文 PDF，第 1 页包含 `FRAMEBUFFER2026`，第 2 页包含 `ROOMMERGE2026`。
- `experiments/sample-experiments.json`：四条示例实验，供指标对比和周报验证。
- `generated-sample-report.md`：运行演示脚本后导出的示例周报。

重建 PDF（只在重建时需要 ReportLab）：

```bash
pip install reportlab
python scripts/generate_sample_pdf.py
```

PDF 验收：上传 PDF 后以关键词 `ROOMMERGE2026` 检索，预期引用均指向第 2 页。
完整自动化见 `backend/tests/test_submission_live.py`，需要真实后端、seekdb 和 PowerContext。
