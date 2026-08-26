# my_agents · 多工作人设记忆底座

> 把「会记事的底座」和「怎么干活的行当」彻底分开：
> **记忆底层**（`core/`）提供领域无关的记忆能力，**工作人设层**（`personas/`）按需插拔。
> 已从 AI导师系统 v4.0 完成**全量迁移**（引擎/工具/提示词/数据/测试/脚本），v5.0 可运行。

## 快速开始

```bash
pip install mcp[cli]                          # 仅启动 MCP 服务需要
python cli.py init                            # 初始化数据库（core 表 + 人设扩展）
python cli.py smoke                           # 端到端冒烟测试（全链路验证）
python cli.py switch alex tutor               # 切换人设
python server.py --personas tutor,coder       # 启动 MCP 服务（stdio，默认加载全部人设：27 工具实测通过）

# 数据迁移（一次性，旧 tutor.db → 新 agents.db）
python scripts/import_v4_data.py              # 全量导入（幂等，自动备份）
python scripts/import_v4_data.py --verify     # 新旧 COUNT 对比

# 运维
python scripts/backup.py                      # 备份
python scripts/db_health.py                   # 健康检查
python scripts/db_metrics.py --agent alex     # 教学指标
python scripts/eval/eval_retrieval.py         # 检索评测
python -m pytest tests/ -q                    # 35 个测试全绿
```

## 一句话架构

```
LLM 应用层
   │ MCP 协议
   ▼
工作人设层 personas/guide  ← 入口人设：系统启动时引导创建/切换工作人格（仅调度，不干活）
   │ 唯一通道 core.api.MemoryAPI
   ▼
工作人设层 personas/tutor   ← 专属工具 / 专属表 / 提示词 / 进化能力 / 钩子
   ▼
记忆底层 core              ← 会话/情节/语义/核心记忆/状态/进化（领域无关）
   │ SQL
   ▼
data/agents.db             ← 7 张 core 表 + 6 张 tutor_* 扩展表
```

## 核心文档

- [ARCHITECTURE.md](ARCHITECTURE.md) — 完整分层设计（职责边界 / 数据流转 / 接口定义 / 切换机制）
- [docs/migration-parity.md](docs/migration-parity.md) — v4.0 → v5.0 迁移等价性对照（工具/数据/缺陷修复）

## 新增一个人设（3 步）

1. `mkdir personas/myrole && touch personas/myrole/__init__.py`
2. 写 `manifest.py`（`core.manifest.register(PersonaManifest(...))`），`__init__.py` 里 `from . import manifest`
3. 按需添加 `schema_ext.py`（扩展字段）/ `tools/`（专属工具）/ `evolution.py` / `hooks.py`

无需改动 `core/` 任何代码。**范例**：`personas/coder/`（编程人设：任务追踪 + 审查记录）——只用了上述 3 步即完成插拔，与导师人设数据完全隔离（`coder_` 前缀表）。

## 工具清单（24 个，MCP 实测通过）

| 命名空间 | 数量 | 说明 |
|---------|:---:|------|
| `mem_*` | 17 | 记忆底层通用工具（会话/情节/蒸馏/检索/状态/进化/SQL/人设切换） |
| `guide_*` | 3 | 引导助手专属（status / create_persona / switch_persona），仅引导与调度 |
| `tutor_*` | 4 | 导师专属（record_interaction / query_errors / write_diary / end_session） |
| `coder_*` | 3 | 编程专属（record_task / complete_task / record_review） |

## 目录

```
core/        记忆底层：api / schema / db / manifest / registry / tools(mem_* 17个) / engine / migrations
personas/    工作人设层：guide（系统引导助手，入口人设，3 工具 + 0 表扩展 + 引导协议）、tutor（导师，4 工具 + 8 表扩展 + 9 提示词）、coder（编程范例，3 工具 + 2 表扩展）
scripts/     运维：backup / db_health / db_metrics / db_slim / diary_distill / eval_retrieval / import_v4_data / ci_local
tests/       pytest 35 个测试（回归/检索/进化/集成/人设切换/数据导入/工具）
diary/       教学日记（按 agent 隔离，53 篇已迁入）
server.py    MCP 组装入口    cli.py  人设管理 CLI    data/  SQLite 库
```
