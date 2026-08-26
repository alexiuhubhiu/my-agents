# 变更日志

所有重要变更记录于此文件，格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [1.0.0] - 2026-08-26

### 新增

- **记忆底层（通用层）`core/`**：领域无关的记忆底座
  - `MemoryAPI` 唯一门面：会话/情节/语义/核心记忆/工作状态/进化/上下文聚合
  - 三信号检索引擎（FTS trigram → LIKE 兜底 → 实体关系 → 元数据重排 → 摘要降级护栏）
  - 进化框架基座（`log_event` 不可变日志 / `run_evolution` 调度 / 四分支回滚）
  - 7 张基础表 + 2 张 FTS5 trigram 虚拟表
  - 17 个 `mem_*` 通用 MCP 工具（含 `mem_switch_persona` 人设切换）
- **工作人设层（领域层）`personas/`**：可插拔人设
  - `tutor` 导师人设：4 专属工具（数字信号采集/错题查询/日记/下课编排）、8 张扩展表、9 提示词、C2/C3 进化能力、context 钩子
  - `coder` 编程人设（范例）：3 专属工具（任务追踪/审查记录）、2 张扩展表、钩子
  - 声明式注册：新目录 + `manifest.py` 即插拔，core 零改动
- **数据迁移**：`scripts/import_v4_data.py` 全量导入旧 tutor.db（15 表映射、UNIQUE 差异 upsert、persona 回填、53 篇日记复制、import_log 幂等、`--verify` 对比）
- **测试**：35 个 pytest 测试（回归/检索/进化/集成/人设切换/数据导入/工具），conftest 隔离生产库
- **运维**：backup / db_health / db_metrics / db_slim / diary_distill / eval_retrieval / ci_local

### 修复（相对 v4.0）

- `memory_facts` UNIQUE 冲突键加入 `agent_id`（原跨 agent 撞键）
- `record_interaction` 空消息分支短回复计数语义（原无条件 +1）
- 蒸馏 importance/confidence 增加 [0,1] clamp
- `end_session` 下课编排不再裸写绕过乐观锁
- `start_session` 幂等复用补科目匹配语义

### 移除

- `legacy/` JSON fallback 机制（MCP 不可用时改为跳过收尾、下轮重试）
- `temp/` 目录与下课清空步骤

## [0.1.0] - 2026-08-25

- 初始骨架：分层架构设计（ARCHITECTURE.md）+ 记忆底层与导师人设最小可运行实现
