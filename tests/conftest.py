#!/usr/bin/env python3
"""conftest — 测试隔离层（my_agents 适配版）

规则：
- 所有测试一律使用临时库（CORE_SCHEMA_SQL + apply_persona_schema 建的副本），严禁触碰生产 data/agents.db；
- fixture `db` 提供可复用的 Row 连接（临时库，含种子数据）；
- fixture `api` 提供 MemoryAPI（db_path 注入）；`persona_ctx` 提供已加载的 tutor 人设；
- autouse `_isolate_db`：设置 AGENTS_DB_PATH + 清 core.db 单例 + 清 registry._loaded，
  防止任何间接 get_db() 打到生产库或跨测试串库。
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.db import get_db, reset_conn  # noqa: E402
from core.schema import CORE_SCHEMA_SQL  # noqa: E402

_SEED_FACTS = [
    ("python", "闭包", "闭包能捕获外层变量，装饰器常用它实现", "knowledge", 0.9, 0.95, "alex"),
    ("python", "递归", "递归必须先写终止条件否则栈溢出", "mistake", 0.8, 0.9, "alex"),
    ("network", "TCP", "TCP 三次握手 SYN/SYN-ACK/ACK", "knowledge", 0.7, 0.9, "alex"),
    ("python", "bob喜欢Rust", "bob 喜欢 Rust 所有权模型", "preference", 0.9, 0.95, "bob"),
]
_SEED_KNOWLEDGE = [
    ("concept", "python", "闭包与装饰器", "闭包：函数返回函数时捕获外层作用域。装饰器 = 高阶函数包装。", 10),
    ("concept", "network", "子网划分速查", "判断网络位/主机位：/24 前 3 段是网络位。", 9),
]
_SEED_DIARY = [
    ("alex", "2026-08-20", "diary/alex/2026-08-20.md", "他今天自己把闭包调通了，我偷偷开心了好久。", 1, "开心"),
]
_SEED_SESSION = ("sess-test-0001", "alex", "tutor", "python", "闭包", "active", 3)
_SEED_EPISODES = [
    ("sess-test-0001", 1, "user", "闭包里能不能改外层变量？", "闭包", "alex"),
    ("sess-test-0001", 2, "assistant", "能，但要 nonlocal 声明。", "闭包", "alex"),
]
_SEED_ERRORS = [
    ("alex", "忘记写递归终止条件", "技能缺失", "对终止条件重视不足", "python", "active"),
]
_SEED_LP = [
    ("alex", "python", "闭包", "in_progress", 60, "2026-08-25"),
    ("alex", "network", "TCP", "in_progress", 90, "2026-08-25"),
]


def _build_db(path: str | Path) -> sqlite3.Connection:
    """建全 schema（core + tutor 扩展）+ 种子数据。"""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(CORE_SCHEMA_SQL)
    from core import registry
    from personas.tutor import schema_ext as tutor_ext

    registry.apply_persona_schema(tutor_ext, "tutor", conn)
    # agent_state
    conn.execute(
        "INSERT INTO agent_state (agent_id, active_persona, ritual_state) VALUES ('alex', 'tutor', 'IDLE')"
    )
    # core 记忆
    conn.executemany(
        "INSERT INTO memory_facts (subject, entity, fact, fact_type, importance, confidence, agent_id)"
        " VALUES (?,?,?,?,?,?,?)",
        _SEED_FACTS,
    )
    conn.execute(
        "INSERT INTO sessions (id, agent_id, persona, subject, topic, status, turn_count)"
        " VALUES (?,?,?,?,?,?,?)",
        _SEED_SESSION,
    )
    conn.executemany(
        "INSERT INTO episodes (session_id, turn_no, role, content, topic, agent_id)"
        " VALUES (?,?,?,?,?,?)",
        _SEED_EPISODES,
    )
    # tutor 扩展表
    conn.executemany(
        "INSERT INTO tutor_teacher_knowledge (category, subject, title, content, priority) VALUES (?,?,?,?,?)",
        _SEED_KNOWLEDGE,
    )
    conn.executemany(
        "INSERT INTO tutor_diary_entries (agent_id, date, filepath, excerpt, has_romance, mood_summary)"
        " VALUES (?,?,?,?,?,?)",
        _SEED_DIARY,
    )
    conn.executemany(
        "INSERT INTO tutor_error_patterns (agent_id, pattern, category, root_cause, subject, status)"
        " VALUES (?,?,?,?,?,?)",
        _SEED_ERRORS,
    )
    conn.executemany(
        "INSERT INTO tutor_learning_progress (agent_id, subject, topic, status, mastery_level, next_review_at)"
        " VALUES (?,?,?,?,?,?)",
        _SEED_LP,
    )
    conn.commit()
    return conn


@pytest.fixture()
def sample_db_path(tmp_path: Path) -> Path:
    p = tmp_path / "sample.db"
    conn = _build_db(p)
    conn.close()
    return p


@pytest.fixture()
def db(sample_db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(sample_db_path))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture()
def api(sample_db_path: Path) -> "MemoryAPI":
    from core.api import MemoryAPI

    return MemoryAPI(db_path=str(sample_db_path))


@pytest.fixture()
def persona_ctx(api) -> "PersonaContext":
    from core import registry

    return registry.load_persona("tutor", api)


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch, tmp_path):
    """自动隔离：测试期间所有 get_db() 都连独立临时库，清单例 + 清 registry。"""
    tmp_db = tmp_path / "isolated.db"
    monkeypatch.setenv("AGENTS_DB_PATH", str(tmp_db))
    reset_conn()
    from core import registry

    old = dict(registry._loaded)
    registry._loaded.clear()
    yield tmp_db
    registry._loaded.clear()
    registry._loaded.update(old)
    reset_conn()
