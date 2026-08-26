# 目录解耦规范 v2.0（my_agents 分层架构版）

> **核心原则**：记忆底座（core/）与工作人设（personas/）分离；教学平台与教学内容分离。平台只管"怎么教"，课程内容只管"教什么"。

---

## 一、my_agents 工程目录职责

```
D:\my_agents\
├── core/                     ← 记忆底层（领域无关：会话/情节/语义/状态/进化）
├── personas/tutor/           ← 导师工作人设（专属工具/表/提示词/进化能力）
├── personas/tutor/prompts/   ← 导师提示词（init/persona/methodology/workflow 等 9 个）
├── data/agents.db            ← 全部结构化数据（core 表 + tutor_ 扩展表）
├── diary/<agent_id>/         ← 教学日记（按 agent 隔离，每课一篇 YYYY-MM-DD.md）
├── scripts/                  ← 运维脚本（backup/db_health/import_v4_data 等）
├── tests/                    ← pytest 三层测试
├── server.py                 ← MCP 统一入口（core + personas 组装）
└── cli.py                    ← 人设管理 CLI
```

**课程内容**（位于系统外部 `D:\my_tutor\`）：
```
D:\my_tutor\
├── AI导师系统/              ← 旧 v4.0 工程（已迁移完成，只读存档）
├── subjects/                ← 课程内容（按科目分目录，每个科目自治）
│   └── hcie-datacom/        ←   思维导图/ 图表/ 笔记/ 实验/ 教材资料/ 课程截图/
├── 练习册/                  ← 练习题
```

## 二、diary/<agent_id>/ —— 教学日记

- **路径**：`diary/<agent_id>/YYYY-MM-DD.md`（如 `diary/alex/2026-08-26.md`）
- **写入**：仅通过 `tutor_write_diary` 工具（落盘 + excerpt + DB 同步一次完成）
- **索引**：`tutor_diary_entries` 表（UNIQUE(agent_id, date)），excerpt 供 FTS 检索
- **历史**：旧 v4.0 的 `D:\my_tutor\AI导师系统\diary\` 54 篇由 `scripts/import_v4_data.py` 复制并回写 filepath

## 三、subjects/<科目名>/ —— 课程内容，每个科目自治

```
subjects/<科目名>/
├── 思维导图/            ← MD 大纲（markmap 兼容格式）
├── 图表/                ← Mermaid 时序图/流程图 + SVG 拓扑/对比图
├── 笔记/                ← 课程随堂笔记（可按日期组织子目录）
├── 实验/                ← 实验配置步骤、拓扑文件、抓包截图
├── 教材资料/            ← PDF 教材、产品手册、参考文档
├── 课程截图/            ← 上课过程中的临时截图
├── 00-课程大纲.md        ← 该科目的总体学习路线
└── README.md            ← 科目索引
```

### 3.1 思维导图/ 规范

- 所有 `.md` 文件统一使用 markmap 兼容格式（YAML front matter + `markmap.autoFit: false` + `colorFreezeLevel: 3`）
- 文件名：`<协议/主题>_<子主题>.md`，中文优先，如 `OSPF_Hello报文详解.md`
- 每个 MD 文件自包含——打开即可在 markmap 中渲染，不依赖外部资源

### 3.2 图表/ 规范

- Mermaid 源文件存为 `.md`，内含单个 ` ```mermaid ` 代码块
- 孟菲斯配色统一使用 `%%{init: {...}}%%` 覆写 themeVariables
- SVG 文件存为独立 `.svg`，可被 HTML/Markdown 直接引用
- 文件命名：`<协议>_<场景描述>.<扩展名>`，如 `OSPF_DR_BDR选举流程.md`

### 3.3 现有科目清单

| 科目 | 路径 | 状态 |
|:-----|:-----|:-----|
| HCIE Datacom 数通 | `subjects/hcie-datacom/` | 活跃 |
| 操作系统 | `subjects/os/` | 待迁移 |
| Notebook 全栈项目 | `subjects/notebook-fullstack/` | 已完成 |
| Spring Boot 后端 | `subjects/spring-boot/` | 已完成 |

## 四、提示词文件引用

| 提示词 | 文件名 | 运行时角色 |
|--------|--------|-----------|
| 启动指令 + MCP 协议 | `personas/tutor/prompts/init.md` | 必读入口 |
| 教师人设 | `personas/tutor/prompts/persona.md` | 一节课读一次 |
| 教学法则 | `personas/tutor/prompts/methodology.md` | 参考手册（Grep 定点取） |
| 标准工作流 | `personas/tutor/prompts/workflow.md` | 流程 SSOT |
| 蒸馏规范 | `personas/tutor/prompts/distill-template.md` | 供 mem_distill 指引 |
| 创作备注 | `personas/tutor/prompts/persona-notes.md` | 运行时**禁读** |

## 五、迁移规则

### 5.1 新产出直接落地课程目录

上课过程中生成的教学产出（思维导图、图表、笔记），**当场写入对应科目的 `subjects/<科目>/` 子目录**，不走平台目录中转。

### 5.2 严禁的行为

- ❌ 在 `my_agents/` 下创建课程内容子目录（如 `思维导图/`、`图表/`）
- ❌ 在 `subjects/` 下放系统配置文件（如 `init`、`persona`）
- ❌ 直接操作 `data/agents.db`（一律走 MCP 工具或 `scripts/` 运维脚本）
- ❌ 将课程产出的 MD/SVG/Mermaid 文件临时放在桌面或下载目录

### 5.3 历史说明

- `AI导师系统/`（v4.0）已迁移至 `my_agents/`（v5.0），旧工程只读存档
- 旧 `legacy/` JSON fallback 机制已移除（MCP 不可用时跳过收尾、下轮重试）
- 旧 `temp/` 目录不再使用（无临时文件中转需求）

## 六、设计理由

平台可复用（core 换人设即可换行当）、科目可迁移（自包含文件夹直接拷贝）、Agent 协作清晰（课程 Agent 只读写 `subjects/<科目>/`，导师人设只读写 `my_agents/`——权限边界即目录边界）。
