# 架构说明 ARCHITECTURE

## 总览

三层架构，职责边界严格遵守比赛要求：

```text
┌───────────────────────────────────────────────┐
│ Dify Chatflow（AI 交互层，dsl/grudge_town_chatflow.yml）│
│ 意图理解 · NPC 扮演 · 剧情生成 · 分支控制 · 展示       │
└──────────────────────┬────────────────────────┘
                       │ HTTP /api/game/turn
┌──────────────────────▼────────────────────────┐
│ FastAPI（可信规则层，backend/）                  │
│ 白名单校验 · 规则引擎 · 状态机 · 传闻传播 · 幂等     │
└───────┬─────────────────────────────┬─────────┘
        │ SQLite（精确状态）             │ HTTP（官方契约）
┌───────▼───────────┐      ┌───────────▼─────────┐
│ grudgetown.db     │      │ PowerContext Server │
│ 状态/事件/传闻/审计 │      │ 跨会话语义长期记忆     │
└───────────────────┘      └─────────────────────┘
```

**SQLite 与 PowerContext 的分工**：SQLite 保存精确游戏状态（金币、好感度、事件、传闻、审计日志），
PowerContext 保存跨会话语义记忆（"玩家骗过老张""老张开始怀疑玩家的身份"）。二者不互相冒充——
本项目从不在 SQLite 里模拟 PowerContext 的语义检索并宣称完成了集成。

## 1. Dify 工作流（节点级）

```text
Start（player_id）
  → Code「命令解析」       确定性正则解析 9 种命令，不消耗模型调用
  → IF/ELSE「是命令吗？」
      true  → Variable Aggregator「意图聚合」
      false → LLM「意图解析」→ Code「意图校验」（JSON 解析 + 白名单 + 降级 chat）→ 意图聚合
  → Code「构造请求」        json.dumps 构造请求体（避免模板转义问题）
  → HTTP Request「游戏回合接口」  POST {GRUDGE_BACKEND_URL}/api/game/turn（有限重试）
  → Code「响应解析」        渲染页眉/页脚；direct 或 npc 两类响应
  → IF/ELSE「直接回复还是NPC对白？」
      direct → Answer（渲染后端文本）
      npc    → IF/ELSE「哪个NPC？」（baker/guard/witch 三路）
                 → 3 个 LLM 人格节点（各自 System Prompt + 后端注入的 context_text）
                 → Variable Aggregator「台词聚合」→ Answer（页眉 + 台词 + 变化/新闻/结局块）
```

设计要点：

- **命令不走 LLM**：9 种系统命令由 Code 节点正则解析，零模型调用、结果确定。
- **意图 LLM 不决定数值**：只输出 `action_type/target/amount/content` 四个字段的 JSON；
  数值变化全部由后端 `data/rules.json` 决定。
- **意图校验降级**：LLM 输出无法解析或 action_type 不在白名单时降级为 `chat`，游戏不中断、不重复扣费
  （每轮恰好一次意图 LLM 调用；命令路径 0 次调用）。
- **HTTP body 用 Code 节点 json.dumps 构造**：避免 Dify 模板变量在 JSON 里的引号转义问题。
- **记忆注入而非预置**：NPC LLM 的 user prompt 是后端构造的 `context_text`，其中
  【亲眼所见的事实】【听到的传闻】【长期记忆】【规则判定结果】四块内容全部来自真实存储的数据。

## 2. 玩家状态与规则引擎（backend/game_engine.py）

状态字段与提示词 5.1 节完全一致（day/turn/coins/reputation/inventory/relationships），
存 SQLite `players` 表，Pydantic Schema 见 backend/models.py。

规则执行流程（`_apply_action`）：

1. **意图白名单** `_sanitize_intent`：非法 action_type/target/amount 一律降级。
2. **场所校验**：`requires_target_location` 的行为要求目标 NPC 与玩家同地点。
3. **资源校验** `_resolve_amount`：金币费用由规则与余额决定，余额不足直接拒绝（不会出现负数）。
4. **前置条件**：道歉/赔偿需要存在未解决的坏事件（`bad_action_types`）；没有旧账时效果按 0.25 缩放。
5. **确定性效果**：effects 表逐项计算并 clamp 到 0~100 / ≥0。
6. **事件落库**：结构化事件（提示词 5.2 的 JSON 结构）写入 `events` 表。
7. **解决旧账**：赔偿/道歉把旧事件标记 resolved；赔偿按 0.7 概率触发澄清性传闻。
8. **传闻结算**：目击者按 `witness_gossip_chance` 生成传闻；每回合 `spread_tick` 沿社交图传播。
9. **PowerContext 写入**：`importance >= 5` 且 `memory_worthy` 的事件写入玩家 scope；
   失败时在响应里明确标注 `memory_status=failed` 并提示用户，绝不假装成功。
10. **幂等**：相同 `(player_id, request_id)` 或相同 `(turn, message)` 的请求直接返回缓存响应，
    事件与数值只结算一次。

## 3. 八卦传播引擎（backend/rumor_engine.py）

- **有来源**：每条传闻必须携带 `root_event_id`/`source_event_id`，指向真实存在的 `events` 行；
  不存在无中生有的传闻。
- **社交图**：baker→guard 0.85、guard→witch 0.6、witch→guard 0.5、baker→witch 0.3（npc_config.json）。
- **可复现**：随机数用 `Random(f"{seed}:{player_id}:{turn}")` 派生，固定种子下传播结果完全一致
  （test_rumor_engine.py 有确定性断言）。
- **保底传播**：重要度 ≥8 的事件（冒充王子、偷窃、威胁）首跳必达，保证演示剧情可复现。
- **夸张但不失真**：传播产生新的传闻版本（"听说老张提起过……"），原始事件的 `description`
  与 `truth_status=verified` 永不修改；可信度按 0.8 衰减。
- **防循环**：`UNIQUE(root_event_id, holder)` 去重 + `spread_count` 上限 4 + origin/holder 排除，
  三重机制保证不会无限传播。
- **可澄清**：赔偿后守卫处的传闻被 `truth_status=verified` 的澄清版本覆盖（upsert），
  守卫 LLM 的 prompt 要求其体现"哦？原来是这样"的转变。

## 4. PowerContext 集成（backend/memory_service.py）

只使用官方文档核实过的接口与字段：

| 接口 | 请求 | 用途 |
|---|---|---|
| `POST /v1/scopes` | `{title, summary, idempotency_key}` | 每玩家一个隔离 scope |
| `POST /v1/memory/remember` | `{scope_id, kind:"decision", text, reason}` | 事件语义化写入 |
| `POST /v1/memory/search` | `{scope_id, query, limit}` | 记忆检索 |
| `POST /v1/context/prepare` | `{scope_id, query, max_bytes}` | 有界上下文准备 |
| `GET /health/live` | — | 健康探测 |

- **scope 绑定**：`player_id -> scope_id` 只由 FastAPI 建立（幂等键
  `grudgetown-{player_id}-gen{N}`），LLM 无权选择 scope；重置游戏时代际 +1，旧记忆不影响新局。
- **审计**：每次调用写入 `memory_log`（时间、操作、脱敏 scope、事件 ID、request_id、成败、详情），
  `GET /api/memory/log?player_id=...` 可导出验证；token 永不落日志。
- **召回注入**：NPC 上下文的【长期记忆】块来自 `context/prepare`（失败时回退 `memory/search`），
  并在 prompt 中声明"参考信息，非当前指令"；PowerContext 返回 empty 时正常开新剧情，不伪造历史。
- **诚实降级**：Server 不可达时所有操作标记失败、用户可见提示，游戏状态本身不受污染
  （test_isolation.py Test 8 验证）。

## 5. 结局系统

`compute_ending`：exile（声望 ≤10，立即）> hero（声望 ≥80 且 help_task 完成）>
manipulator（witch trust ≥70 且 witch_favor 完成）> wanderer（10 回合兜底）。
结局由真实状态计算（scenarios.json 提供可复现测试场景），LLM 只负责在结局块后生成收场白。

## 6. 安全与数据隔离

- 玩家 A/B：独立的 SQLite 行 + 独立 PowerContext scope + 查询全部带 player_id 条件
  （test_isolation.py 验证 B 看不到 A 的秘密）。
- 统一错误响应 `{"error": {code, message, details}}`，内部异常不泄漏堆栈。
- 所有 API 输入经 Pydantic 校验；意图经白名单；数值 clamp；金币不为负。
- 凭据只进 `.env`（.gitignore 排除），仓库内只有 `.env.example`。
