#!/usr/bin/env python3
"""core.engine.storage — 存储后端 ABC（v4.0 契约保留）。"""
from __future__ import annotations

import abc


class StorageBackend(abc.ABC):
    @abc.abstractmethod
    def connect(self) -> None: ...

    @abc.abstractmethod
    def execute(self, sql: str, params: tuple = ()): ...


class SqliteBackend(StorageBackend):
    """默认后端：委托 core.db 单例。"""

    def __init__(self, db_path=None):
        self._db_path = db_path

    def connect(self) -> None:
        from ..db import get_db
        self._conn = get_db(self._db_path)

    def execute(self, sql: str, params: tuple = ()):
        if not hasattr(self, "_conn"):
            self.connect()
        cur = self._conn.execute(sql, params)
        return cur.fetchall()


class NullEmbedder:
    """离线路线：零 embedding（P2 向量预留）。"""

    def embed(self, text: str) -> list[float]:
        return []
