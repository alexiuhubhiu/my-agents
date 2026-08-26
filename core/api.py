#!/usr/bin/env python3
"""
core.api — MemoryAPI：记忆底层对工作人设层暴露的稳定接口（唯一门面）
====================================================================
设计原则：
1. 工作人设层只 import core.api.MemoryAPI，不触碰 db/schema/engine 内部。
2. 所有方法签名与领域无关（persona/agent_id 是通用维度，不是领域字段）。
3. 人设专属逻辑通过「钩子」扩展（get_context 的 context_hook、evolution 的
   自定义能力），而非在 core 内硬编码分支。
4. 返回结构全部为 dict（天然 JSON 化，MCP 工具直接透传）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from dataclasses import dataclass

from .db import get_db

# ────────────────────────────────────────────────────────────
# 数据类（引擎返回结构，to_dict 兼容旧调用方）
# ────────────────────────────────────────────────────────────


@dataclass
class RetrievalHit:
    entity: str
    fact: str
    fact_type: str
    importance: float
    confidence: float
    source: str = "memory_facts"     # memory_facts | episodes | persona_ext

    def to_dict(self) -> dict:
        return {
            "entity": self.entity,
            "fact": self.fact,
            "fact_type": self.fact_type,
            "importance": self.importance,
            "confidence": self.confidence,
            "source": self.source,
        }


# ────────────────────────────────────────────────────────────
# MemoryAPI — 记忆底层门面
# ────────────────────────────────────────────────────────────


class MemoryAPI:
    """记忆底层稳定接口。

    分组：
    - 会话生命周期：start_session / end_session
    - 情节记忆      ：log_episode / recall_episodes
    - 语义记忆      ：distill_facts / retrieve
    - 核心记忆      ：get_core_blocks / set_core_block
    - 工作状态      ：get_state / update_state
    - 进化          ：evolve / revert_evolution
    - 上下文聚合    ：get_context（core 检索 + persona context_hook 注入）
    - 运维          ：health
    """

    def __init__(self, db_path=None):
        self._db_path = db_path

    # ── 连接 ──
    @property
    def conn(self):
        return get_db(self._db_path)

    # ══════════════ 会话生命周期 ══════════════

    def start_session(
        self,
        agent_id: str,
        persona: str,
        subject: str = "",
        topic: str = "",
    ) -> dict:
        """创建（或复用）active 会话，返回 session_id。

        幂等复用规则（v4.0 语义）：查最近 active 会话，
        若 (未指定科目) 或 (已有科目相同) 或 (已有会话无科目) → 复用（带科目时顺手 UPDATE）；
        否则新建。
        """
        conn = self.conn
        row = conn.execute(
            """SELECT id, subject FROM sessions
               WHERE agent_id=? AND persona=? AND status='active'
               ORDER BY started_at DESC LIMIT 1""",
            (agent_id, persona),
        ).fetchone()
        if row:
            existing_subject = row["subject"] or ""
            if not subject or existing_subject == subject or not existing_subject:
                # 复用（带科目/主题时顺手更新该会话）
                if subject or topic:
                    conn.execute(
                        """UPDATE sessions SET subject=COALESCE(NULLIF(?, ''), subject),
                               topic=COALESCE(NULLIF(?, ''), topic) WHERE id=?""",
                        (subject, topic, row["id"]),
                    )
                    conn.commit()
                return {"session_id": row["id"], "status": "active", "reused": True}

        sid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO sessions (id, agent_id, persona, subject, topic)
               VALUES (?, ?, ?, ?, ?)""",
            (sid, agent_id, persona, subject, topic),
        )
        conn.commit()
        return {"session_id": sid, "status": "active", "reused": False}

    def end_session(
        self,
        session_id: str,
        summary: str = "",
        turn_count: int = 0,
        status: str = "completed",
    ) -> dict:
        """关闭会话（回填 summary/turn_count/ended_at）。

        注：人设专属收尾（错题入库/复习计划/日记）由人设端 end_session
        组合工具负责，本方法只做通用收尾。
        """
        conn = self.conn
        cur = conn.execute(
            """UPDATE sessions
               SET summary=?, turn_count=?, status=?, ended_at=datetime('now')
               WHERE id=?""",
            (summary, turn_count, status, session_id),
        )
        conn.commit()
        return {"success": cur.rowcount > 0, "session_id": session_id}

    # ══════════════ 情节记忆 ══════════════

    def log_episode(
        self,
        session_id: str,
        role: str,
        content: str,
        agent_id: str = "",
        topic: str = "",
        tokens_est: int = 0,
    ) -> dict:
        """追加一条对话回合（自动计算 turn_no）。"""
        conn = self.conn
        cur = conn.execute(
            "SELECT COALESCE(MAX(turn_no), 0) + 1 FROM episodes WHERE session_id=?",
            (session_id,),
        )
        turn_no = cur.fetchone()[0]
        cur = conn.execute(
            """INSERT INTO episodes (session_id, agent_id, turn_no, role, content, topic, tokens_est)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, agent_id, turn_no, role, content, topic, tokens_est),
        )
        conn.execute(
            "UPDATE sessions SET turn_count = turn_count + 1 WHERE id=?",
            (session_id,),
        )
        conn.commit()
        return {"id": cur.lastrowid, "turn_no": turn_no, "session_id": session_id}

    def recall_episodes(
        self,
        session_id: str = "",
        agent_id: str = "",
        last_n: int = 1,
        scope: str = "current_session",
    ) -> dict:
        """回忆历史对话回合。

        scope=current_session: 指定/最近会话完整回合
        scope=all           : 最近 N 个会话（按时间倒序）
        """
        conn = self.conn
        if scope == "all":
            rows = conn.execute(
                """SELECT id, subject, topic, started_at, ended_at, turn_count, summary, status
                   FROM sessions WHERE agent_id=? ORDER BY started_at DESC LIMIT ?""",
                (agent_id, last_n),
            ).fetchall()
            sessions = [dict(r) for r in rows]
            episodes = []
            for s in sessions:
                eps = conn.execute(
                    """SELECT turn_no, role, content, topic, created_at
                       FROM episodes WHERE session_id=? ORDER BY turn_no ASC""",
                    (s["id"],),
                ).fetchall()
                episodes.extend([dict(e) | {"session_id": s["id"]} for e in eps])
            return {"sessions": sessions, "episodes": episodes, "count": len(episodes)}

        # current_session：指定或最近
        if not session_id:
            row = conn.execute(
                """SELECT id FROM sessions WHERE agent_id=?
                   ORDER BY (status='active') DESC, started_at DESC LIMIT 1""",
                (agent_id,),
            ).fetchone()
            if row:
                session_id = row["id"]
        if not session_id:
            return {"sessions": [], "episodes": [], "count": 0, "degraded": True}

        sess = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        eps = conn.execute(
            "SELECT * FROM episodes WHERE session_id=? ORDER BY turn_no ASC",
            (session_id,),
        ).fetchall()
        return {
            "sessions": [dict(sess)] if sess else [],
            "episodes": [dict(e) for e in eps],
            "count": len(eps),
        }

    # ══════════════ 语义记忆 ══════════════

    def distill_facts(
        self,
        agent_id: str,
        facts: list[dict],
        persona: str = "",
    ) -> dict:
        """蒸馏语义事实（ADD-only + upsert 冲突消解，importance/confidence 取 MAX）。"""
        conn = self.conn
        applied, upserted, skipped = [], [], []
        for f in facts:
            entity = (f.get("entity") or "").strip()
            fact = (f.get("fact") or "").strip()
            if not entity or not fact:
                skipped.append({"reason": "entity/fact 为空", **f})
                continue
            imp = max(0.0, min(1.0, float(f.get("importance", 0.5))))
            conf = max(0.0, min(1.0, float(f.get("confidence", 0.8))))
            row = conn.execute(
                """SELECT id, importance, confidence, version FROM memory_facts
                   WHERE agent_id=? AND entity=? AND fact=? AND status='active'""",
                (agent_id, entity, fact),
            ).fetchone()
            if row:
                # upsert：升权
                conn.execute(
                    """UPDATE memory_facts SET
                           importance=MAX(importance, ?), confidence=MAX(confidence, ?),
                           last_confirmed_at=datetime('now'), version=version+1
                       WHERE id=?""",
                    (imp, conf, row["id"]),
                )
                upserted.append({"entity": entity, "fact": fact, "id": row["id"]})
            else:
                cur = conn.execute(
                    """INSERT INTO memory_facts
                           (agent_id, persona, entity, fact, fact_type, importance, confidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        agent_id,
                        persona,
                        entity,
                        fact,
                        f.get("fact_type", "general"),
                        imp,
                        conf,
                    ),
                )
                applied.append({"entity": entity, "fact": fact, "id": cur.lastrowid})
        conn.commit()
        return {
            "applied": applied,
            "upserted": upserted,
            "skipped": skipped,
            "message": f"新增 {len(applied)} / 升权 {len(upserted)} / 跳过 {len(skipped)}",
        }

    def retrieve(
        self,
        query: str,
        agent_id: str,
        persona: str = "",
        scope: str = "all",
        limit: int = 10,
        trace: bool = True,
        subject: str | None = None,
    ) -> list[dict]:
        """三信号检索（完整引擎，见 core.engine.retrieval）。

        信号链：结构化过滤 → FTS trigram → LIKE 兜底 → 实体关系 → 重排 → 摘要降级。
        返回 dict 列表（source/id/title/excerpt/date/importance/score）。
        """
        from .engine.retrieval import retrieve as engine_retrieve

        return engine_retrieve(
            query=query,
            subject=subject,
            scope=scope,
            limit=limit,
            db=self.conn,
            agent_id=agent_id,
            trace=trace,
            persona=persona,
        )

    # ══════════════ 核心记忆 ══════════════

    def get_core_blocks(self, agent_id: str) -> dict:
        conn = self.conn
        rows = conn.execute(
            "SELECT block_key, block_value, priority FROM core_memory WHERE agent_id=?",
            (agent_id,),
        ).fetchall()
        return {r["block_key"]: {"value": r["block_value"], "priority": r["priority"]} for r in rows}

    def set_core_block(self, agent_id: str, block_key: str, block_value: str, priority: int = 5) -> dict:
        conn = self.conn
        conn.execute(
            """INSERT INTO core_memory (agent_id, block_key, block_value, priority, version)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(agent_id, block_key) DO UPDATE SET
                   block_value=excluded.block_value,
                   priority=excluded.priority,
                   updated_at=datetime('now'),
                   version=version+1""",
            (agent_id, block_key, block_value, priority),
        )
        conn.commit()
        return {"agent_id": agent_id, "block_key": block_key, "updated": True}

    # ══════════════ 工作状态 ══════════════

    def get_state(self, agent_id: str) -> dict:
        conn = self.conn
        row = conn.execute("SELECT * FROM agent_state WHERE agent_id=?", (agent_id,)).fetchone()
        if not row:
            return {"agent_id": agent_id, "exists": False, "state": {}}
        d = dict(row)
        d["state_json"] = json.loads(d.get("state_json") or "{}")
        return {"agent_id": agent_id, "exists": True, "state": d}

    def update_state(self, agent_id: str, updates: dict, expected_version: int | None = None) -> dict:
        """原子化状态更新（PATCH 语义 + 乐观锁）。

        路由规则（动态列校验）：
        - agent_state 真实存在的列（core 列 + registry 应用过的人设扩展列 tutor_*）→ 直接写列
        - 其余键 → 合并进 state_json
        """
        conn = self.conn
        row = conn.execute(
            "SELECT version FROM agent_state WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO agent_state (agent_id) VALUES (?)", (agent_id,)
            )
            version = 1
        else:
            version = row["version"]
        if expected_version is not None and expected_version != version:
            return {"success": False, "reason": f"乐观锁冲突: 期望 {expected_version}, 实际 {version}"}

        # 动态取 agent_state 列集合（含人设扩展列），只路由真实存在的列
        real_cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_state)").fetchall()}
        col_updates, json_updates = {}, {}
        for k, v in updates.items():
            if k in real_cols:
                col_updates[k] = v
            else:
                json_updates[k] = v

        sql = "UPDATE agent_state SET updated_at=datetime('now'), version=version+1"
        params: list = []
        for k, v in col_updates.items():
            sql += f", {k}=?"
            params.append(v)
        if json_updates:
            cur_json = conn.execute(
                "SELECT state_json FROM agent_state WHERE agent_id=?", (agent_id,)
            ).fetchone()
            merged = json.loads(cur_json["state_json"] or "{}")
            merged.update(json_updates)
            sql += ", state_json=?"
            params.append(json.dumps(merged))
        sql += " WHERE agent_id=?"
        params.append(agent_id)
        conn.execute(sql, params)
        conn.commit()
        return {"success": True, "version": version + 1, "columns": list(col_updates), "json_keys": list(json_updates)}

    # ══════════════ 进化 ══════════════

    def evolve(
        self,
        capabilities: list[str] | None = None,
        dry_run: bool = False,
        agent_id: str = "",
        persona: str = "",
    ) -> dict:
        """进化调度（委托 core.engine.evolution）。

        - 能力从 registry 已加载人设的 evolution_caps 挂载（personas/<name>/evolution.py）
        - 未注册能力 → warnings；全部变更落 evolution_events 不可变日志
        - _EVO_LOCK 串行化防并发
        """
        from .engine.evolution import run_evolution as engine_run

        return engine_run(
            capabilities=capabilities,
            dry_run=dry_run,
            agent_id=agent_id,
            persona=persona,
        )

    def revert_evolution(self, event_id: int, agent_id: str = "") -> dict:
        """按 change_before 回滚进化事件（追加 revert 记录）。"""
        conn = self.conn
        row = conn.execute(
            "SELECT * FROM evolution_events WHERE id=? AND applied=1 AND reverted=0",
            (event_id,),
        ).fetchone()
        if not row:
            return {"success": False, "reason": "事件不存在或不可回滚"}
        before = json.loads(row["change_before"] or "{}")
        target_table, target_id = row["target_table"], row["target_id"]
        if target_table and target_id is not None and before:
            cols = ", ".join(f"{k}=?" for k in before)
            conn.execute(f"UPDATE {target_table} SET {cols} WHERE id=?", (*before.values(), target_id))
        conn.execute(
            """UPDATE evolution_events SET reverted=1 WHERE id=?""", (event_id,)
        )
        conn.execute(
            """INSERT INTO evolution_events
                   (event_type, capability, target_table, target_id, confidence, reason, applied, session_id)
               VALUES ('revert', ?, ?, ?, 1.0, 'manual revert', 0, '')""",
            (row["capability"], target_table, target_id),
        )
        conn.commit()
        return {"success": True, "reverted_event": event_id}

    # ══════════════ 上下文聚合（核心数据流出口） ══════════════

    # hot/cold token 预算（v4.0 对齐）
    TOKEN_BUDGETS = {"hot": 600, "cold": 2000}

    def get_context(
        self,
        agent_id: str,
        persona: str = "",
        freshness_level: str = "hot",
        focus_subject: str = "",
        session_id: str = "",
        limit: int = 8,
    ) -> dict:
        """聚合上下文：通用层检索 + 人设层 context_hook 注入（v4.0 get_context 平移）。

        数据流（读路径）：
          LLM → get_context
              → core: agent_state + active_persona + core_memory + 最近会话指针
              → core: 三信号检索（focus_subject 时按科目过滤）
              → persona hook(ctx) → 注入专属字段（student_state/复习计划/错题预警/...）
              → 合并返回
        """
        from . import registry

        # freshness 归一化（v4.0：warm → hot）
        if freshness_level == "warm":
            freshness_level = "hot"
        budget = self.TOKEN_BUDGETS.get(freshness_level, 2000)

        persona = persona or registry.active_persona(agent_id)
        bundle = {
            "agent_id": agent_id,
            "persona": persona,
            "focus_subject": focus_subject,
            "freshness_level": freshness_level,
            "generated_at": datetime.now().astimezone().isoformat(),
            "token_budget_limit": budget,
            "state": self.get_state(agent_id),
            "core_memory": self.get_core_blocks(agent_id),
            "last_session": self._last_session_pointer(agent_id, session_id),
            "memory_hits": self.retrieve(
                query=focus_subject or "",
                agent_id=agent_id,
                persona=persona,
                scope="all",
                limit=limit,
                subject=focus_subject or None,
            ),
            "persona_ext": {},          # ← 人设钩子填充
        }
        # token 估算（v4.0：len(json)//4）
        bundle["token_budget_used"] = len(json.dumps(bundle, ensure_ascii=False)) // 4

        # 指令文案（v4.0 _instruction）
        bundle["_instruction"] = (
            "以下是当前教学/工作上下文。基于 state/core_memory/memory_hits 与 persona_ext 组织本次会话。"
            if freshness_level == "cold"
            else "保持最近会话连续性，关注 persona_ext 中的最新状态。"
        )

        # 人设扩展钩子
        ctx = registry._loaded.get(persona)
        if ctx and ctx.context_hook:
            bundle["persona_ext"] = ctx.context_hook(
                bundle, agent_id=agent_id, freshness_level=freshness_level
            ) or {}
        return bundle

    def _last_session_pointer(self, agent_id: str, exclude_session_id: str = "") -> dict:
        """最近一次已结束会话指针（v4.0 last_session 语义）。"""
        conn = self.conn
        try:
            sql = """SELECT id, subject, topic, summary, started_at, ended_at
                     FROM sessions
                     WHERE agent_id=? AND status IN ('completed', 'closed')"""
            args: list = [agent_id]
            if exclude_session_id:
                sql += " AND id != ?"
                args.append(exclude_session_id)
            sql += " ORDER BY COALESCE(ended_at, started_at) DESC LIMIT 1"
            row = conn.execute(sql, args).fetchone()
            return dict(row) if row else None
        except Exception:  # noqa: BLE001
            return None

    # ══════════════ 运维 ══════════════

    def health(self) -> dict:
        conn = self.conn
        from .schema import CORE_TABLES

        rows = {}
        for t in CORE_TABLES + ["retrieval_log"]:
            try:
                rows[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            except Exception as e:  # noqa: BLE001
                rows[t] = f"ERR:{e}"

        # 检索性能统计（v4.0 health_check 平移：p50/p95/max，表缺失静默降级）
        retrieval_stats = {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
        try:
            lat = [
                r["latency_ms"]
                for r in conn.execute(
                    "SELECT latency_ms FROM retrieval_log WHERE latency_ms>0 ORDER BY latency_ms"
                ).fetchall()
            ]
            if lat:
                n = len(lat)
                retrieval_stats = {
                    "count": n,
                    "p50_ms": lat[int(n * 0.50)],
                    "p95_ms": lat[min(int(n * 0.95), n - 1)],
                    "max_ms": lat[-1],
                }
        except Exception:  # noqa: BLE001
            pass

        return {
            "core_tables": rows,
            "retrieval_stats": retrieval_stats,
            "healthy": all(isinstance(v, int) for v in rows.values()),
            "version": "core-1.0.0",
        }
