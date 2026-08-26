#!/usr/bin/env python3
"""
personas.tutor.tools.diary — 日记落盘组合（v4.0 tool_write_diary 完整平移）
==========================================================================
适配：落盘 diary/<agent_id>/YYYY-MM-DD.md；tutor_diary_entries 按 agent_id。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.api import MemoryAPI

# 项目根（diary/<agent>/ 的父目录）
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
CST = timezone(timedelta(hours=8))


def tool_write_diary(api: MemoryAPI, p: dict) -> dict:
    """写日记组合入口（落盘 + excerpt 自动 + DB 同步）。

    params:
      date        日期 YYYY-MM-DD（默认今天）
      content     日记全文（人设化自然书写）
      has_romance 是否含浪漫信号
      mood        心情（可选，空则正则提取）
      agent_id    实例标识（决定落盘目录 diary/<agent>/）
    """
    db = api.conn
    agent_id = p.get("agent_id", "alex")
    date = p.get("date") or datetime.now(CST).strftime("%Y-%m-%d")
    content = p.get("content", "")
    has_romance = bool(p.get("has_romance", False))
    mood = p.get("mood", "") or ""

    if not content:
        return {"success": False, "error": "content 不能为空"}

    # ① 落盘 diary/<agent_id>/YYYY-MM-DD.md
    diary_dir = BASE_DIR / "diary" / agent_id
    diary_dir.mkdir(parents=True, exist_ok=True)
    path = diary_dir / f"{date}.md"
    path.write_text(content, encoding="utf-8")

    # ② excerpt：旧模板「今日事实」节优先，否则跳过标题/引用行取正文开头
    excerpt = _extract_diary_excerpt(content)

    # ③ mood_summary：传入值优先，否则正则提取（兼容旧格式）
    mood_summary = mood.strip()
    if not mood_summary:
        m = re.search(r"(?:心情|mood|情绪)[:：]\s*(.+)", content[:500])
        if m:
            mood_summary = m.group(1).strip()

    # ④ 同步 DB（UNIQUE(agent_id, date)，幂等）
    db.execute(
        """
        INSERT INTO tutor_diary_entries (agent_id, date, filepath, excerpt, has_romance, mood_summary)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(agent_id, date) DO UPDATE SET
            filepath=excluded.filepath,
            excerpt=excluded.excerpt,
            has_romance=excluded.has_romance,
            mood_summary=excluded.mood_summary
        """,
        (
            agent_id,
            date,
            str(path.relative_to(BASE_DIR)).replace("\\", "/"),
            excerpt,
            1 if has_romance else 0,
            mood_summary,
        ),
    )
    db.commit()

    return {
        "success": True,
        "filepath": str(path),
        "excerpt": excerpt,
        "excerpt_chars": len(excerpt),
        "db_synced": True,
    }


def _extract_diary_excerpt(content: str, limit: int = 200) -> str:
    """从日记内容提取 excerpt（v4.0 完整算法）。

    旧模板兼容：存在「## 今日事实」节 → 优先取该节。
    新写法：跳过日期标题与心情速写引用行，取正文开头——信息锚点在开头。
    """
    marker = "## 今日事实"
    pos = content.find(marker)
    if pos != -1:
        segment = content[pos + len(marker):]
        nxt = segment.find("\n## ", 1)
        if nxt != -1:
            segment = segment[:nxt]
        return segment.strip().replace("\n", " ")[:limit]
    body = []
    for ln in content.split("\n"):
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith(">"):
            continue
        body.append(s)
    return " ".join(body)[:limit]
