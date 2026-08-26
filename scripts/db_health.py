#!/usr/bin/env python3
"""
my_agents — 数据库健康检查（v4.0 db_health.py 适配：core + tutor 表）
======================================================================
检查项：表行数 / agent_state 单行 / 重复键 / 日记对齐 / 检索 P95 / DB 大小
用法:
  python scripts/db_health.py
  python scripts/db_health.py --fix        # 自动修复可修复项
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "agents.db"

# 全部业务表（core + tutor）
REQUIRED_TABLES = [
    "agent_state", "sessions", "episodes", "memory_facts", "core_memory",
    "evolution_events", "retrieval_log",
    "tutor_learning_progress", "tutor_teaching_metrics", "tutor_error_patterns",
    "tutor_pitfall_triggers", "tutor_teacher_knowledge", "tutor_diary_entries",
]


def check() -> dict:
    import sqlite3

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    issues: list[str] = []
    table_row_counts: dict[str, int] = {}

    # 1) 表存在 + 行数
    for t in REQUIRED_TABLES:
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            table_row_counts[t] = n
        except sqlite3.Error:
            issues.append(f"表 {t} 缺失")

    # 2) agent_state 单行校验（每个 agent 一行）
    dup_agents = conn.execute(
        "SELECT agent_id, COUNT(*) c FROM agent_state GROUP BY agent_id HAVING c > 1"
    ).fetchall()
    for r in dup_agents:
        issues.append(f"agent_state 重复: {r['agent_id']} x{r['c']}")

    # 3) tutor_learning_progress 重复 (agent_id, subject, topic)
    dup_lp = conn.execute(
        """SELECT agent_id, subject, COUNT(*) c FROM tutor_learning_progress
           GROUP BY agent_id, subject HAVING c > 1"""
    ).fetchall()
    for r in dup_lp:
        issues.append(f"tutor_learning_progress 重复: {r['agent_id']}/{r['subject']} x{r['c']}")

    # 4) 日记对齐（tutor_diary_entries vs diary/<agent>/ 文件）
    try:
        diary_root = Path(__file__).resolve().parent.parent / "diary"
        files = sum(1 for d in diary_root.iterdir() if d.is_dir()
                    for f in d.glob("*.md") if not f.name.startswith("_"))
        db_diary = conn.execute("SELECT COUNT(*) FROM tutor_diary_entries").fetchone()[0]
        if files != db_diary:
            issues.append(f"日记不对齐: 文件 {files} vs 表 {db_diary}")
    except FileNotFoundError:
        issues.append("diary 目录不存在")

    # 5) 检索 P95
    retrieval_stats = {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    try:
        lat = [r[0] for r in conn.execute(
            "SELECT latency_ms FROM retrieval_log WHERE latency_ms>0 ORDER BY latency_ms"
        ).fetchall()]
        if lat:
            n = len(lat)
            retrieval_stats = {
                "count": n,
                "p50_ms": round(lat[int(n * 0.50)], 1),
                "p95_ms": round(lat[min(int(n * 0.95), n - 1)], 1),
                "max_ms": round(lat[-1], 1),
            }
    except sqlite3.Error:
        pass

    # 6) DB 大小
    db_size_kb = round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0

    conn.close()
    return {
        "table_row_counts": table_row_counts,
        "issues": issues,
        "healthy": len(issues) == 0,
        "retrieval_stats": retrieval_stats,
        "db_size_kb": db_size_kb,
    }


def main():
    parser = argparse.ArgumentParser(description="my_agents 数据库健康检查")
    parser.add_argument("--fix", action="store_true", help="自动修复可修复项（当前版本仅报告）")
    args = parser.parse_args()

    result = check()
    print(f"数据库: {DB_PATH}")
    print(f"大小: {result['db_size_kb']} KB | 检索: {result['retrieval_stats']}")
    print("\n表行数:")
    for t, n in result["table_row_counts"].items():
        print(f"  {t:<28} {n}")
    print(f"\n异常: {len(result['issues'])} 项")
    for i in result["issues"]:
        print(f"  ❌ {i}")
    print(f"\n结论: {'✅ 健康' if result['healthy'] else '⚠️ 需修复'}")
    if args.fix and result["issues"]:
        print("提示: 请用 scripts/import_v4_data.py 或手动 SQL 修复（--fix 仅报告）")
    sys.exit(0 if result["healthy"] else 1)


if __name__ == "__main__":
    main()
