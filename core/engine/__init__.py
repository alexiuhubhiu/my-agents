#!/usr/bin/env python3
"""
core.engine — 领域无关引擎层（v4.0 迁移占位 + 薄封装）
======================================================
v4.0 中 engine/retrieval.py(475行)、engine/evolution.py(564行) 已是领域无关，
此处保留模块边界，实现委托给 core.api.MemoryAPI（最小可跑），
完整三信号检索/进化调度逻辑从 AI导师系统/tutor_mcp/engine/ 平移即可。
"""

from . import models, retrieval, storage  # noqa: F401
