#!/usr/bin/env python3
"""
my_agents — 检索评测套件（v4.0 eval_retrieval.py 适配：core 引擎 + tutor 表）
==============================================================================
流程：临时库建 schema + 种子数据 → 跑查询集 → 输出 recall@k 等指标。
不触碰生产库。
用法:
  python scripts/eval/eval_retrieval.py --rebuild    # 重建评测库
  python scripts/eval/eval_retrieval.py --top-k-cutoffs 5,10,20
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.schema import CORE_SCHEMA_SQL  # noqa: E402

# 评测查询集：{查询词: 期望命中的关键词}
QUERIES = {
    "闭包": ["闭包"],
    "TCP": ["TCP"],
    "递归": ["递归"],
    "泛洪": ["泛洪"],  # tutor 专属：diary 摘要
}


def build_eval_db() -> str:
    """建临时评测库（core + tutor 扩展 + 种子）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="eval_retrieval_")
    import os

    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(CORE_SCHEMA_SQL)
    from core import registry
    from personas.tutor import schema_ext as tutor_ext

    registry.apply_persona_schema(tutor_ext, "tutor", conn)
    conn.execute("INSERT INTO agent_state (agent_id, active_persona) VALUES ('alex', 'tutor')")
    facts = [
        ("python", "闭包", "闭包能捕获外层变量", "knowledge", 0.9),
        ("python", "递归", "递归必须先写终止条件", "mistake", 0.8),
        ("network", "TCP", "TCP 三次握手 SYN/SYN-ACK/ACK", "knowledge", 0.7),
    ]
    conn.executemany(
        "INSERT INTO memory_facts (subject, entity, fact, fact_type, importance, agent_id) VALUES (?,?,?,?,?, 'alex')",
        facts,
    )
    conn.execute(
        "INSERT INTO tutor_diary_entries (agent_id, date, filepath, excerpt) VALUES ('alex', '2026-08-20', 'diary/alex/2026-08-20.md', '今天复习了 ISIS 泛洪原理')"
    )
    conn.commit()
    conn.close()
    return path


def evaluate(db_path: str, cutoffs: list[int]) -> dict:
    from core.engine.retrieval import retrieve
    from personas.tutor.hooks import _tutor_retrieve

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    results = {}
    for q, expected in QUERIES.items():
        if q == "泛洪":
            # tutor 专属查询：走钩子检索（diary/knowledge FTS + LIKE）
            hits = _tutor_retrieve(conn, "alex", q)
            texts = " ".join(h.get("title", "") + " " + h.get("excerpt", "") for h in hits)
        else:
            hits = retrieve(q, scope="all", limit=max(cutoffs), db=conn, agent_id="alex")
            texts = " ".join(h.get("title", "") + " " + h.get("excerpt", "") for h in hits)
        hit_count = sum(1 for kw in expected if kw in texts)
        results[q] = {
            "expected": expected,
            "hit": hit_count,
            "recall_at_full": hit_count / len(expected),
            "hits_total": len(hits),
        }
    conn.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="my_agents 检索评测")
    parser.add_argument("--rebuild", action="store_true", help="重建评测库")
    parser.add_argument("--top-k-cutoffs", default="5,10,20")
    args = parser.parse_args()

    cutoffs = [int(x) for x in args.top_k_cutoffs.split(",")]
    db_path = build_eval_db()
    results = evaluate(db_path, cutoffs)

    print("=== 检索评测结果 ===")
    for q, r in results.items():
        mark = "✅" if r["hit"] == len(r["expected"]) else "❌"
        print(f"  {mark} '{q}': 召回 {r['hit']}/{len(r['expected'])}（共 {r['hits_total']} 条命中）")
    all_pass = all(r["hit"] == len(r["expected"]) for r in results.values())
    print(f"\n结论: {'全部通过 ✅' if all_pass else '存在失败项'}")


if __name__ == "__main__":
    main()
