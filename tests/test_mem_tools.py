#!/usr/bin/env python3
"""通用工具测试：mem_db_execute 白名单/禁 DROP、mem_schema、mem_update_state 列路由。"""

from core.tools import _db_execute, _db_query, _schema


def test_db_execute_insert(api):
    r = _db_execute(api, {"sql": "INSERT INTO core_memory (agent_id, block_key, block_value) VALUES ('alex', 'k1', 'v1')"})
    assert r["success"] is True
    assert r["statement_type"] == "INSERT"


def test_db_execute_rejects_drop(api):
    r = _db_execute(api, {"sql": "DROP TABLE memory_facts"})
    assert r["success"] is False
    assert "DROP" in r["error"]


def test_db_execute_rejects_select(api):
    r = _db_execute(api, {"sql": "SELECT 1"})
    assert r["success"] is False


def test_db_query_readonly(api):
    r = _db_query(api, {"sql": "SELECT COUNT(*) AS n FROM agent_state"})
    assert "columns" in r and "row_count" in r
    assert r["row_count"] >= 0


def test_db_query_rejects_write(api):
    r = _db_query(api, {"sql": "DELETE FROM agent_state"})
    assert r["success"] is False


def test_schema_lists_tables(api):
    r = _schema(api, {})
    assert "agent_state" in r["tables"]
    assert "tutor_learning_progress" in r["tables"]
    assert "fields" in r["tables"]["agent_state"]


def test_update_state_routes_columns_and_json(api):
    """mem_update_state：tutor_ 扩展列写列，其他键进 state_json。"""
    r = api.update_state("alex", {"tutor_mood": "tired", "custom_flag": True})
    assert r["success"] is True
    assert "tutor_mood" in r["columns"]
    assert "custom_flag" in r["json_keys"]
    st = api.get_state("alex")["state"]
    assert st["tutor_mood"] == "tired"
    assert st["state_json"]["custom_flag"] is True


def test_update_state_optimistic_lock(api):
    """乐观锁：expected_version 不匹配则拒绝。"""
    r = api.update_state("alex", {"tutor_energy": 5}, expected_version=999)
    assert r["success"] is False
    assert "乐观锁" in r["reason"]
