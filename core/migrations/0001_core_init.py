#!/usr/bin/env python3
"""
core.migrations.0001_core_init — core 基础表初始化
====================================================
= core.schema.CORE_SCHEMA_SQL（幂等：全部 IF NOT EXISTS）。
人设扩展表（tutor_*）由 registry.apply_persona_schema 在加载人设时应用，不在此。
"""

from __future__ import annotations

from ..schema import CORE_SCHEMA_SQL

UP_SQL = CORE_SCHEMA_SQL
