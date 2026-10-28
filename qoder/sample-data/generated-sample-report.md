# 3D-MEM 场景记忆研究（演示） 科研周报（2026-10-22 ~ 2026-10-28）

> 项目：3D-MEM 场景记忆研究（演示） · 统计区间：2026-10-22 至 2026-10-28

## 本周概述

_（未配置大模型 API，本节为空）_

## 一、本周阅读的论文

- **sample-memory-survey**（sample-memory-survey.md，1 页 / 3 个分块 · 主题：Embodied QA / 3D Scene Memory）
- **sample-sequential-eqa**（sample-sequential-eqa.md，1 页 / 3 个分块 · 主题：Embodied QA / 3D Scene Memory）
- **sample-3d-mem**（sample-3d-mem.md，1 页 / 3 个分块 · 主题：Embodied QA / 3D Scene Memory）

## 二、完成的实验与结果

### HSM v1：物体摘要 + IoU 合并 （exp_58055c282dd744c9）
- 状态：completed
- 数据集：EQA-Long (sample)
- 模型配置：`{"detector": "YOLO-World", "detector_conf_threshold": 0.35, "segmenter": "SAM", "memory": "hsm_symbolic_v1", "merge_iou_threshold": 0.5, "top_k": 8, "llm": "7b-instruct", "temperature": 0.0}`
- 指标：accuracy=58.7, history_dependent_accuracy=54.1, peak_memory_gb=4.2, latency_ms=265
- 结果：准确率 58.7%，显存 4.2 GB，延迟 265 ms，达成假设目标
- 遇到的问题：相邻房间同类物体被错误合并，计数类问题错误占全部错误的 23%
- 下一步改进：加入房间 ID 约束的合并策略，并引入外观嵌入做重识别

### Frame-Buffer 64 帧稠密记忆 （exp_60ae13a9013d43e3）
- 状态：completed
- 数据集：EQA-Long (sample)
- 模型配置：`{"detector": "none", "memory": "frame_buffer", "buffer_frames": 64, "llm": "7b-instruct", "temperature": 0.0}`
- 指标：accuracy=52.4, history_dependent_accuracy=39.8, peak_memory_gb=11.8, latency_ms=480
- 结果：准确率 52.4%，显存峰值 11.8 GB，单问延迟 480 ms，超出预期开销
- 遇到的问题：5 房间序列跑到第 4 个房间时显存接近上限；延迟过高难以交互式使用
- 下一步改进：改用符号化摘要记忆，把内存与帧数解耦

### No-Memory Baseline (EQA-Long) （exp_d11a99c899154531）
- 状态：completed
- 数据集：EQA-Long (sample)
- 模型配置：`{"detector": "none", "memory": "none", "llm": "7b-instruct", "temperature": 0.0, "frames_per_step": 1}`
- 指标：accuracy=41.2, history_dependent_accuracy=22.6, peak_memory_gb=3.1, latency_ms=210
- 结果：准确率 41.2%，历史依赖型问题子集准确率仅 22.6%，确认无记忆无法完成长时序问答
- 遇到的问题：计数类问题几乎全部失败；智能体反复回答当前房间可见物体
- 下一步改进：实现符号化物体摘要记忆，先验证能否提升历史依赖型问题准确率

### HSM v2 尝试：全局外观嵌入重识别 （exp_9872eb2e6da54695）
- 状态：abandoned
- 数据集：EQA-Long (sample)
- 模型配置：`{"detector": "YOLO-World", "segmenter": "SAM", "memory": "hsm_symbolic_v2", "appearance_embedding_dim": 512, "merge_iou_threshold": 0.5, "merge_cosine_threshold": 0.85, "llm": "7b-instruct"}`
- 指标：accuracy=53.9, history_dependent_accuracy=48.3, peak_memory_gb=5.6, latency_ms=340, count_error_rate=0.31
- 结果：准确率下降到 53.9%，计数错误未减少；同类物体外观嵌入区分度不足，反而把同一物体拆成多条
- 遇到的问题：同一物体在不同视角下余弦相似度常低于 0.85，导致重复条目；记忆条目数量增加 2.4 倍
- 失败原因：外观嵌入对视角变化过于敏感，阈值 0.85 过严；该方案在当前检测器输出质量下不可行，已放弃
- 下一步改进：放弃全局外观嵌入方案，改为在合并时加入房间 ID 硬约束 + 多视角平均嵌入

## 三、技术决策（来自 PowerContext 记忆）

- 符号化物体摘要在显存与准确率上同时优于稠密帧缓存 [session:demo-session-day1]
- 全局外观嵌入重识别方案不可行：视角变化导致相似度阈值失效，已放弃 [session:demo-session-day1]

## 四、失败与教训

- HSM v2 全局外观嵌入重识别使准确率从 58.7% 降到 53.9%；原因：experiment HSM v2 abandoned [session:demo-session-day1]

## 五、进展

- 完成 HSM v1 物体摘要记忆（accuracy 58.7%，显存 4.2 GB） [session:demo-session-day1]
- 完成 Frame-Buffer 64 帧对照实验（accuracy 52.4%，显存 11.8 GB） [session:demo-session-day1]
- 完成无记忆 baseline 评测（accuracy 41.2%） [session:demo-session-day1]

## 六、尚未完成的任务与下周计划

- 最近一次保存的研究进度（Handoff）下一步：实现房间 ID 硬约束 + 多视角平均嵌入的合并策略（HSM v3）; 在 EQA-Long 上复测计数类问题子集
- 未解决问题：计数类问题错误率仍占 23%，需要房间 ID 硬约束的合并策略
- 实现房间 ID 硬约束 + 多视角平均嵌入的合并策略（HSM v3） [session:demo-session-day1]
- 在 EQA-Long 上复测计数类问题子集 [session:demo-session-day1]

---

说明：论文与实验数据来自 OceanBase seekdb 的真实记录，决策/失败/进展/计划来自 PowerContext 中当前有效的记忆条目（PowerContext 记忆列表接口不返回时间戳，因此该部分为截至生成时刻的有效记忆，而非仅本区间新增）。