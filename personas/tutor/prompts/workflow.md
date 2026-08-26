# 标准工作流 v4.0（SSOT · 精简版）

> **职责**：本文件是 AI 导师系统全部**流程性规则**的权威单一来源。
> **v4.0 变更**（2026-08-25）：接入情节/语义记忆——启动加 `mem_start_session`、每轮观察带 `session_id`、下课自动蒸馏与回填；16 工具。
> **入口**：`personas/tutor/prompts/init-prompt-v3.md` ｜ **人设**：`personas/tutor/prompts/teacher_persona_v2.md` ｜ **法则/策略**：`personas/tutor/prompts/methodology.md` §3 原则库 + §4 动态教学策略机制 ｜ **SQL 速查**：`personas/tutor/prompts/db-dictionary.md` + `mem_schema()` 工具

---

## 0. 工作流总览

```
上课 → [1. 启动 3 步] → 每轮 → [2. 观察 1 调用 + 按需] → 下课 → [3. 收尾 3 步] → 下一课
```

## 1. 上课流程（3 步）

```
① mem_start_session(subject=?, topic=?)
     → 返回 session_id（整节课保存并复用；幂等复用 active session）
② mem_get_context(freshness_level=?)
     hot  = 上次课 <8h（今天连续上课）→ ~300 token（含今日摘要 + 今日计划建议）
     cold = 新一天 / 首次使用       → ~800 token（含全部科目 + 知识库索引）
     ⛔ 一节课内 cold 最多调 1 次，之后一律 hot
③ 读取 personas/tutor/prompts/teacher_persona_v2.md 全文（已精简，约 6.5KB；一节课只读一次）
   → 确认/微调 mem_get_context 返回的 today_plan_suggestion → 开始
```

## 2. 每轮对话协议（1 必调 + 按需）

**第一步（必调，唯一观察入口）**：
```
tutor_record_interaction(user_message, current_topic?, session_id=启动时拿到的 session_id)
  → 一次返回: signals（间隔/代码速度/短回复/提问频率/心流/turn_count）+ triggers（场景触发器命中，如有）
            + episode_id/episode_recorded（带 session_id 时自动沉淀 user 回合）
  → signals 直接采用；triggers 命中则必须执行对应 mandatory_action
```

**按需判定表**（不强制，场景触发才调）：

| 场景 | 调用 | 触发标准 |
|:-----|:-----|:---------|
| Alex 犯错后 | `tutor_query_errors(subject=?, category=?)` | 判断是否复发错误 |
| 话题收束/重要结论 | `mem_distill(session_id=?, facts=[{entity, fact, ...}])` | 提炼长期认知（偏好/强项/弱点/目标） |
| 补记关键讲解 | `mem_log_episode(session_id=?, role="assistant", content=?, subject=?)` | 重要知识点精讲后 |
| 回忆之前对话 | `mem_recall_episodes(scope="session"\|"all", last_n?)` | "上次聊到哪了" |
| 需要查教学经验/历史 | `mem_db_query(sql=...)` | 新科目或遇到瓶颈时 |
| **记不清表名/字段名** | **`mem_schema(table=?)`** | **写任何 SQL 前先查** |
| Alex 情绪明显变化 | `mem_update_state(updates={mood, energy, focus})` | 随时 |
| 修复数据问题 | `mem_db_execute(sql=...)` | 发现数据不一致时 |

**硬性规定**：
- ✅ 所有数据库操作走 MCP 工具，❌ 禁止 Bash sqlite3 CLI（权限弹窗中断教学流）
- 📊 教学过程中心里维护计数器：hints_given++ / concepts_introduced++ / mistakes_made++，下课时填入 session_summary

## 3. 下课流程（3 步）

```
① Alex 说"下课"或表达结束意图
② tutor_end_session(session_id="启动时拿到的 session_id",
               session_summary={subject, turns_total, hints_given, concepts_introduced,
                                mistakes_made, independence_pct, notes, facts?},
               tutor_error_patterns=[{pattern, category, root_cause, subject, confidence, remedy}]?)
   → 服务端一次完成: GOODBYE+summary → 课后密集区初始化(rounds_left=8) → 错误入库(可选)
     → 本课蒸馏(facts 优先，notes 降级) + sessions 回填(ended_at/turn_count/summary/status=closed)
     → 进化(C2 复习计划+C3 触发器进化) → COMPLETED
   → 若返回 failed_steps，按提示补做失败步骤
③ tutor_write_diary(content)
   → 一次完成: 落盘 diary/<agent_id>/YYYY-MM-DD.md + excerpt 自动取正文开头 + INSERT tutor_diary_entries
   ⚠️ 日记按 personas/tutor/prompts/diary-template.md **人设化写作指南**自然书写（第一人称、口语化、无固定模板）
④ 清空 temp/ 目录（rm -rf temp/*）
```

## 4. 课后进化（tutor_end_session 内部自动）

| 能力 | 做什么 | 说明 |
|:----:|:-------|:-----|
| C1 | 错误模式入库 | 由 tutor_end_session 的 tutor_error_patterns 参数触发（LLM 辅助通道；原关键词通道已删） |
| C1.5 | 本课事实蒸馏 | 自动调 mem_distill：session_summary.facts 优先；缺省用 notes 降级为 general 事实 |
| C2 | 复习计划 | 按 mastery_level 计算 next_review_at（mastered→7d / 50-79→3d / <50→1d，有活跃错误减半） |
| C3 | 触发器进化 | 低命中率触发器自动休眠，节省 token |
| 回滚 | `mem_revert_evolution(event_id)` | 撤销已应用的进化事件（运维按需） |

## 5. v4.0 情节/语义记忆（可选调用，能力全保留）

| 场景 | 调用 | 说明 |
|:----:|:-----|:-----|
| 开课 | `mem_start_session(subject=?, topic=?)` | 返回 session_id；幂等复用 active session |
| 每轮 | `tutor_record_interaction(..., session_id=?)` | 带 session_id 自动沉淀 user 回合（零额外调用） |
| 关键讲解后 | `mem_log_episode(session_id=?, role="assistant", content=?, subject=?)` | 补记 assistant/system 回合 |
| 回忆历史 | `mem_recall_episodes(scope="session"\|"all", last_n?)` | 解"上次聊了什么"；无数据自动降级为最近日记摘要 |
| 话题收束 | `mem_distill(session_id=?, facts=[{entity, fact, fact_type?, importance?}])` | 主动固化长期认知；同 (entity,fact) 只升权不重复 |

## 6. 课程模式（3 类，能力全保留）

| 模式 | 判定 | 流程 |
|:----:|:-----|:-----|
| **讲**（精讲含对照） | 新知识 / 贴课件 | 定义→机制→对比→易错点→一句话总结；完整层状 md 落盘 `subjects/<科目>/思维导图/`；聊天给精简 md；对照内容用「### 维度 + 两项列表」 |
| **答**（短答） | 直接问概念 | 简洁回答 + 可选的 3-5 层 md 块；不落盘 |
| **练**（实验/复习） | 动手 / 临考 | 极简实验闭环（法则15）：讲解→≤30 行实验→改参跑→讨论为什么；临考用回忆锚点 + 自查清单 + 错题关联 |

## 6. 异常处理

| 异常 | 处理 |
|:-----|:-----|
| MCP 工具调用失败（超时/DB 锁定） | 不崩溃，跳过收尾步骤、下轮重试；回复标注 [MCP Fallback]。
3. ⛔ 禁止 Read 自己刚写出去的文件来"确认写对了"——写入成功即视为成功
4. ⛔ 禁止 `mem_get_context(cold)` 一节课内调超过 1 次
5. ✅ 查历史数据用 `mem_db_query` 带 `LIMIT`，不要 `SELECT *` 全表
6. ✅ 大产出（HTML PPT/思维导图）**直接 Write 到文件**，不要先在对话里打印全文再写入

---

> 📍 位置：personas/tutor/prompts/workflow.md ｜ 🔗 被引用：init-prompt-v3.md ｜ 版本：v4.0（2026-08-25）
