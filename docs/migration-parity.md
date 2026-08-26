# 迁移等价性对照（v4.0 → my_agents v5.0）

> 验收标准 §6：每个迁移工具在旧/新实现下跑等价输入，对比关键输出字段。
> 验证日期：2026-08-26

## 1. 工具等价对照

| v4.0 工具 | 新架构工具 | 关键输出对齐 | 验证方式 |
|-----------|-----------|-------------|---------|
| start_session | `mem_start_session` | session_id/status/reused（幂等复用，科目匹配语义保留） | tests/test_regression_bugs.py::test_r3 + integration |
| get_context | `mem_get_context` | hot/cold budget、state/core_memory/last_session/memory_hits + persona_ext 全字段 | integration_flow::test_full_session_flow |
| record_interaction | `tutor_record_interaction` | signals（间隔/代码速度/短回复/提问频率/心流）+ triggers（冷却/severity 排序） | verify_s2 脚本 + test_r2 |
| log_episode | `mem_log_episode` | id/turn_no 递增（MAX+1） | test_r3 |
| recall_episodes | `mem_recall_episodes` | sessions/episodes/count/degraded（scope=session/all） | integration_flow |
| distill_memory | `mem_distill` | applied/upserted/skipped（importance/confidence MAX 升权） | integration_flow |
| update_state | `mem_update_state` | 乐观锁 + 扩展列路由（PATCH 语义） | test_mem_tools::test_update_state_* |
| query_errors | `tutor_query_errors` | results/total_active/resolved_this_month/cross_subject_matches/query_params | verify_s2（5 键全字段） |
| run_evolution | `mem_evolve` | C2 复习计划（mastery→7/3/1d+错误减半）、C3 触发器休眠/降级、warnings | test_engine_evolution |
| db_query | `mem_db_query` | columns/rows/row_count（只读白名单） | test_mem_tools |
| db_execute | `mem_db_execute` | changes/statement_type（禁 DROP） | test_mem_tools |
| schema | `mem_schema` | tables{row_count,fields} | test_mem_tools |
| health_check | `mem_health` | core_tables + retrieval_stats(count/p50/p95/max) | smoke + verify_s1 |
| revert_evolution | `mem_revert_evolution` | C1 删行/C2 复习恢复/C3 触发器恢复/通用列回滚 | test_engine_evolution::test_revert_* |
| end_session | `tutor_end_session` | 7 步编排 + failed_steps（rounds=8/蒸馏降级/回填 closed） | integration_flow（steps 键全等） |
| write_diary | `tutor_write_diary` | 落盘 diary/<agent>/ + excerpt「今日事实」节 + mood 正则 | verify_s2 |

## 2. 新增能力（v4.0 无）

| 能力 | 说明 |
|------|------|
| `mem_switch_persona` / `mem_list_personas` | 人设动态加载与切换（agent_id 隔离） |
| `mem_get_state` / `mem_retrieve` | 状态直读 + 通用检索入口 |
| 分层 Schema 扩展 | 人设专属表/列按需插拔（tutor_ 前缀守卫） |
| import_v4_data | 旧库全量导入（幂等 + import_log） |

## 3. 缺陷修复清单（迁移时修复的 v4.0 已知问题）

| # | v4.0 缺陷 | v5.0 修复 |
|---|----------|----------|
| 1 | memory_facts UNIQUE(entity,fact) 不含 agent_id → 跨 agent 撞键 | UNIQUE(agent_id,entity,fact) |
| 2 | record_interaction 空消息分支短回复无条件 +1 | 与主分支语义一致（有短才 +1） |
| 3 | distill 未 clamp importance/confidence | [0,1] clamp |
| 4 | end_session 步骤② 裸写绕过乐观锁 | 统一经扩展列更新 |
| 5 | db_execute.changes 为累计值 | 保留 total_changes 但注明语义 |
| 6 | date('now') UTC 与 CST 摘要不同源 | 关键路径用 CST |

## 4. 数据迁移对照

| 旧表 | 新表 | 行数（导入后） | 一致 |
|------|------|:---:|:---:|
| student_state | agent_state | 1 vs 1 | ✅ |
| learning_progress | tutor_learning_progress | 10 vs 10 | ✅ |
| error_patterns | tutor_error_patterns | 25 vs 25 | ✅ |
| pitfall_triggers | tutor_pitfall_triggers | 13 vs 13 | ✅ |
| teacher_knowledge | tutor_teacher_knowledge | 27 vs 27 | ✅ |
| teaching_metrics | tutor_teaching_metrics | 32 vs 32 | ✅ |
| diary_entries | tutor_diary_entries | 53 vs 53 | ✅ |
| sessions / episodes / core_memory / memory_facts / evolution_events / retrieval_log | 同名列 | 全部一致 | ✅ |

日记文件：53 篇复制至 `diary/alex/`，filepath 回写为 `diary/alex/YYYY-MM-DD.md` ✅
