#!/usr/bin/env python3
"""
my_agents — 教学指标分析报告（v4.0 db_metrics.py 适配：tutor_ 前缀 + agent_id）
=================================================================================
用法:
  python scripts/db_metrics.py            # 全量报告
  python scripts/db_metrics.py --agent alex
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "agents.db"


def main():
    import sqlite3

    parser = argparse.ArgumentParser(description="my_agents 教学指标分析")
    parser.add_argument("--agent", default="alex", help="agent_id（默认 alex）")
    args = parser.parse_args()
    agent = args.agent

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        print(f"=== 教学指标报告 (agent={agent}) ===\n")

        # 1) 总体
        total = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(turns_total),0) turns FROM tutor_teaching_metrics WHERE agent_id=?",
            (agent,),
        ).fetchone()
        print(f"课时总数: {total['n']} | 总回合数: {total['turns']}")

        # 2) 按科目
        print("\n按科目:")
        for r in conn.execute(
            "SELECT subject, COUNT(*) n, ROUND(AVG(independence_pct),1) avg_ind FROM tutor_teaching_metrics "
            "WHERE agent_id=? GROUP BY subject ORDER BY n DESC",
            (agent,),
        ).fetchall():
            print(f"  {r['subject']:<24} {r['n']} 课 | 平均独立度 {r['avg_ind']}%")

        # 3) 复习计划状态（v4.0 bug 修复：completed→mastered 枚举）
        print("\n复习计划状态:")
        for r in conn.execute(
            "SELECT status, COUNT(*) n FROM tutor_learning_progress WHERE agent_id=? GROUP BY status",
            (agent,),
        ).fetchall():
            print(f"  {r['status']:<16} {r['n']}")

        # 4) 错题状态
        print("\n错题状态:")
        for r in conn.execute(
            "SELECT status, COUNT(*) n FROM tutor_error_patterns WHERE agent_id=? GROUP BY status",
            (agent,),
        ).fetchall():
            print(f"  {r['status']:<22} {r['n']}")

        # 5) 记忆量
        facts = conn.execute(
            "SELECT COUNT(*) n FROM memory_facts WHERE agent_id=? AND status='active'", (agent,)
        ).fetchone()[0]
        episodes = conn.execute("SELECT COUNT(*) n FROM episodes WHERE agent_id=?", (agent,)).fetchone()[0]
        print(f"\n记忆量: {facts} 条语义事实 | {episodes} 条对话回合")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
