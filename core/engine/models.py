#!/usr/bin/env python3
"""core.engine.models — 引擎返回结构（@dataclass，to_dict 兼容）。"""
from ..api import RetrievalHit, RetrievalHit as _H  # noqa: F401  # re-export 兼容


# EvolutionEvent / HealthReport 结构（v4.0 平移，接口不变）
class EvolutionEvent(dict):
    """进化事件（dict 子类，保持 JSON 直出）。"""

    @classmethod
    def from_row(cls, row: dict) -> "EvolutionEvent":
        return cls(row)
