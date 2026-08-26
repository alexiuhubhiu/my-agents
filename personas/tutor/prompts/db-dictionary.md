# 数据库速查手册 · Data Dictionary v2.1（my_agents 分层架构版）

> **用途**：写 SQL 前的快速参考。**字段级细节不用记——用 `mem_schema(table?)` 工具即时查询**（返回 pragma_table_info 字段清单 + 行数）。
> 本文件只保留：表概览 + 场景 SQL 模板 + 类型约定。
> 所有查询走 `mem_db_query(sql)`，写操作走 `mem_db_execute(sql)`。
> 分层说明：core 基础表（无前缀）全人设共享；导师专属表带 `tutor_` 前缀。所有表按 `agent_id` 过滤（默认 'alex'）。

---

## 速查索引——按场景找表

| 我想知道... | 查哪张表 | 关键字段 |
|------------|---------|:--------:|
| Alex 现在情绪/精力/科目 | `agent_state`（按 agent_id 单行）+ `tutor_*` 扩展列 | tutor_mood/tutor_energy/tutor_focus/current_task/ritual_state |
| 某个科目进度/下次复习 | `tutor_learning_progress` | subject/status/mastery_level/next_review_at |
| 这节课上了多久/效果 | `tutor_teaching_metrics` | session_date/subject/turns_total/notes |
| Alex 之前犯过什么错 | `tutor_error_patterns` | pattern/category/status/remedy |
| 敏感内容预警规则 | `tutor_pitfall_triggers` | name/trigger_keywords/severity/active |
| 系统自己改了什么 | `evolution_events` | capability/change_before/change_after/applied |
| 怎么教某个知识点 | `tutor_teacher_knowledge` | category/title/content |
| 某天的日记写了什么 | `tutor_diary_entries`（+FTS5 tutor_diary_fts） | date/excerpt/mood_summary |
| 聊过什么（对话回合） | `sessions` + `episodes`（core） | session_id/role/content/turn_no |
| 长期记忆（语义事实） | `memory_facts`（core） | entity/fact/importance/confidence |

---

## 场景 SQL 模板

### 场景 1：上课开始（等价 mem_get_context("hot")）

```sql
SELECT tutor_mood, tutor_energy, tutor_focus, current_task, turn_count, ritual_state
FROM agent_state WHERE agent_id='alex';
SELECT subject, status, mastery_level FROM tutor_learning_progress
WHERE agent_id='alex' AND status='in_progress';
SELECT pattern, subject, status FROM tutor_error_patterns
WHERE agent_id='alex' AND status='active' LIMIT 5;
```

### 场景 2：Alex 犯错了

```sql
-- 查这个错误以前出现过吗
SELECT id, pattern, status, frequency_history, remedy
FROM tutor_error_patterns
WHERE agent_id='alex' AND subject='<科目>' AND pattern LIKE '%<关键词>%';
```

### 场景 3：下课——写 session 摘要后查今天数据

```sql
SELECT session_date, subject, turns_total, independence_pct, notes
FROM tutor_teaching_metrics
WHERE agent_id='alex' AND session_date=date('now','localtime');
```

### 场景 4：复习计划（快到期科目）

```sql
SELECT subject, next_review_at FROM tutor_learning_progress
WHERE agent_id='alex' AND status='in_progress' AND next_review_at <= date('now');
```

### 场景 5：系统维护——数据一致性

```sql
-- tutor_error_patterns 有无重复
SELECT pattern, count(*) as cnt FROM tutor_error_patterns
WHERE agent_id='alex' GROUP BY pattern HAVING cnt>1;
-- 日记和文件数对齐
SELECT count(*) FROM tutor_diary_entries WHERE agent_id='alex';
```

### 场景 6：科目交接（已完成科目经验）

```sql
SELECT pattern, category, remedy, cross_subject_mappings
FROM tutor_error_patterns WHERE agent_id='alex' AND subject='<原科目>';
```

### 场景 7：搜日记内容（FTS5 trigram）

```sql
SELECT date, snippet(tutor_diary_fts, 0, '<mark>', '</mark>', '...', 40)
FROM tutor_diary_fts WHERE tutor_diary_fts MATCH '<关键词>' LIMIT 5;
```

### 场景 8：查长期记忆（语义事实检索，或直接 mem_retrieve）

```sql
SELECT entity, fact, importance, confidence FROM memory_facts
WHERE agent_id='alex' AND status='active' AND (subject=? OR subject='')
ORDER BY importance DESC LIMIT 5;
```

---

## 字段类型约定

| SQLite 声明 | 实际存储 | MCP 工具传给 LLM 的格式 |
|------------|---------|------|
| TEXT | 字符串 | str |
| INTEGER | 整数 | int |
| REAL | 浮点 | float |
| BOOLEAN | 0/1 | int (0/1) |
| TEXT DEFAULT '[]' | JSON 字符串 | str（需 json_extract 解析） |

> ⚠️ `extra_data`、`frequency_history`、`cross_subject_mappings`、`change_before/after`、`agent_state.state_json` 等字段存的是 JSON 文本——用 `json_extract(col, '$.key')` 取值，不要当作原生 JSON 处理。

---

## 分层表清单（v5.0）

**core 基础表（全人设共享）**：`agent_state` / `sessions` / `episodes` / `memory_facts` / `core_memory` / `evolution_events` / `retrieval_log`（+ facts_fts / episodes_fts）

**tutor 专属表（带 tutor_ 前缀）**：`tutor_learning_progress` / `tutor_teaching_metrics` / `tutor_error_patterns` / `tutor_pitfall_triggers` / `tutor_teacher_knowledge` / `tutor_diary_entries`（+ tutor_diary_fts / tutor_knowledge_fts）

> 写 SQL 前用 `mem_schema(table?)` 确认字段；`agent_state` 的 `tutor_*` 扩展列在 `mem_update_state` 中自动路由，无需手动写列名。

---

> 📅 版本：v2.1（2026-08-26，适配 my_agents 分层 schema）
> 📍 位置：personas/tutor/prompts/db-dictionary.md ｜ 🔗 被引用：init.md、workflow.md
