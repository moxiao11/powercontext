# Context Pack 的独立会议测量数据

会议来自 Yale-LILY/QMSum，固定 commit `83d7768c1f2b4dfeb091385d3dc7e239b8e5bb7e`，文件为 `data/ALL/test/ES2004a.json`。原文件 SHA-256 为 `911e56db0d8482f1e730bae0a8fcf0ab0095c94abb000ba0516e975fa6e48b31`，采用 MIT 许可，见 LICENSE。

仅使用 `meeting_transcripts`，保留原始 speaker、完整 content 与原始 turn_index。先取 `speaker + ": " + content` 的 UTF-8 长度在 120 至 7500 字节之间的前 8 个 turn，再从其后的同等长度 turn 中按原序取包含 remote、design、control 或 product 的前 8 个作为后续追加数据；不裁剪或拼接 turn。

本地 40 轮序列从前 8 个 turn 开始。在第 6、11、16、21、26、31、36 轮分别追加下一个完整 turn；查询每 10 轮在 remote 和 control 之间切换。普通 prepare 的 max_bytes 为 8000。每轮直接验证与普通 prepare 正文完全一致、真实 wire 长度及摘要；每轮非空，至少产生四种不同 Context，且检索出的证据正文也至少有四种不同组合。

这是产品自有测量配置，不是平台隐藏配置。脚本同时报告普通正文、完整 v1 pack、实际增量传输、每轮独立 gzip 的累计字节与三项节省率。gzip 使用 compresslevel=9、mtime=0，不复用跨请求状态。

receiver.py 是独立接收端 oracle，只导入 Python 标准库。测试在新的 Python 进程中传入首次完整包和后续 delta，校验接收端逐轮重建的正文与摘要；不向接收端传入发送端对象、目标正文或缓存。
