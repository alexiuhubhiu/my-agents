"""
personas — 工作人设层（领域层）
================================
每个子包 = 一个可插拔工作人设，独立维护：
- manifest.py       声明式注册（元信息/工具/扩展/进化/钩子）
- schema_ext.py     专属数据库扩展字段
- tools/            专属 MCP 工具集（<persona>_ 前缀）
- evolution.py      专属进化能力
- prompts/          人设提示词

接入记忆底层的唯一通道：core.api.MemoryAPI（经 registry 注入）。
"""
