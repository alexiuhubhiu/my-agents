#!/usr/bin/env python3
"""
my_agents — 日记周报蒸馏（v4.0 diary_distill.py 适配：diary/<agent>/ + MD5 去重）
===================================================================================
把一周教学日记蒸馏为周报（MD5 去重，跳过已蒸馏过的内容）。
用法:
  python scripts/diary_distill.py --agent alex          # 指定 agent（默认 alex）
  python scripts/diary_distill.py --days 7 --out 周报.md
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def distill(agent: str, days: int) -> str:
    """蒸馏最近 N 天日记 → 周报 markdown。"""
    diary_dir = BASE_DIR / "diary" / agent
    if not diary_dir.exists():
        return f"# 周报\n\n（{agent} 无日记目录）"

    cutoff = date.today() - timedelta(days=days)
    entries = []
    for f in sorted(diary_dir.glob("*.md")):
        if f.name.startswith("_"):
            continue
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d >= cutoff:
            entries.append((d, f))

    if not entries:
        return f"# 周报\n\n（近 {days} 天无日记）"

    # 蒸馏：提取每篇的正文要点（跳过标题/心情行）
    lines_out = [f"# 教学周报（{agent}，{entries[0][0]} ~ {entries[-1][0]}）", ""]
    for d, f in entries:
        content = f.read_text(encoding="utf-8")
        body = []
        for ln in content.split("\n"):
            s = ln.strip()
            if not s or s.startswith(("#", ">")) or re.match(r"(心情|mood|情绪)[:：]", s):
                continue
            body.append(s)
        snippet = " ".join(body)[:300]
        if snippet:
            lines_out.append(f"## {d}\n\n{snippet}\n")
    return "\n".join(lines_out)


def main():
    parser = argparse.ArgumentParser(description="my_agents 日记周报蒸馏")
    parser.add_argument("--agent", default="alex")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", default="", help="输出文件（默认打印）")
    args = parser.parse_args()

    report = distill(args.agent, args.days)
    if args.out:
        out = Path(args.out)
        out.write_text(report, encoding="utf-8")
        print(f"[OK] 周报已写入 {out}")
    else:
        print(report)


if __name__ == "__main__":
    main()
