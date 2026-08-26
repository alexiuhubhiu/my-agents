#!/usr/bin/env python3
"""
personas.tutor.tools — 导师人设专属 MCP 工具
==============================================
工具函数签名统一：fn(api: MemoryAPI, params: dict) -> dict
（api 由 registry 注入，工具内可自由读写 core 表 + tutor_ 扩展表）
"""

from . import diary, interaction, query, session  # noqa: F401
