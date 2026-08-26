# 记忆蒸馏模板（mem_distill 调用指引）

> v4.0 记忆层优化 · 主动蒸馏（semantic 语义记忆 + procedural 程序性记忆）
> 原则（Zep）：**显式供应**（session_id 显式传递）· **错误不吞**（每步 try/except + 返回 errors）· **降级不丢数据**（ADD-only + upsert）· **统一模板**（本文档）

---

## 一、何时调用

在以下时机调用 `mem_distill`（不要在每轮对话调用，只在信息密度足够时）：

| 时机 | 示例 |
|---|---|
| **话题结束 / 一个知识点讲完** | 「闭包已经讲完并验证学生掌握了」 |
| **发现稳定偏好 / 目标** | 「学生明确表示喜欢先讲概念再做题」「学生目标是秋招进大厂后端岗」 |
| **出现重复错误模式** | 「这已经是第三次犯空指针忘了判 null 的错误」 |
| **下课（tutor_end_session 内部自动触发）** | 把本次 session 的关键事实与摘要落库 |

调用频率控制：一次完整上课建议 **2~5 次**（话题切换时 + 下课时），不要逐句抽取。

---

## 二、参数结构

```jsonc
{
  "session_id": "uuid（来自 mem_start_session）",
  "facts": [
    {
      "subject": "Spring Boot",          // 科目（空串表示通用）
      "entity": "事务回滚",              // 实体/主题词：名词短语
      "fact": "学生已理解事务回滚需要 unchecked 异常才触发",  // 事实陈述：一句话
      "fact_type": "general",            // 可选: general|preference|mistake|strength|goal
      "importance": 0.8,                 // 可选 0~1，默认 0.5
      "confidence": 0.9,                 // 可选 0~1，默认 0.8
      "source_episode_id": null          // 可选：来源回合 id（mem_log_episode 返回）
    }
  ],
  "error_patterns": [                    // 可选：发现的重复错误模式
    {
      "pattern": "空指针未判 null",
      "category": "err-null-check",
      "root_cause": "对返回值可能为 null 缺少防御性检查",
      "subject": "Java",
      "confidence": 0.9,
      "remedy": "访问对象前先判 null，或用 Optional"
    }
  ]
}
```

### 事实抽取规范（quality gate）

一条好 fact 必须同时满足：

1. **一句话、可验证**：`学生已掌握闭包的三个特性` ✓ ／ `学生今天聊了闭包` ✗（太泛）
2. **稳定、跨会话有用**：偏好 / 目标 / 知识点掌握度 / 重复错误 —— 一次性的琐事不抽
3. **实体 + 事实分离**：entity 是名词（`闭包`、`学生`、`函数式`），fact 是谓词陈述
4. **重要度分级**：
   - `importance ≥ 0.8`：长期目标、人格锚点、反复确认的掌握点
   - `0.5~0.7`：一般偏好、单次确认的知识点
   - `< 0.4`：一次性观察（通常不抽）
5. **置信度分级**：`confidence ≥ 0.9` 学生明确说出／反复验证；`0.6~0.8` 合理推断；`< 0.6` 不抽或标低

---

## 三、冲突消解规则（系统自动处理，无需关心）

同 `(entity, fact)` 已存在时系统自动 **upsert（最新真值胜出）**：

- `last_confirmed_at` 更新为当前时间
- `importance = MAX(新, 旧)` —— 反复确认的事实重要性只升不降
- `confidence = MAX(新, 旧)`
- `version = 旧 + 1`（同一事实的确认次数）
- 不新增行、不删除旧行（ADD-only）

所以：**同一事实在不同话题再次确认时，直接再提交一次即可**，系统会自动升权。

---

## 四、错误模式规范

错误模式走 `error_patterns` 表（与既有 tutor_end_session 的 error_patterns 参数同通道、自动去重）：

- 只提交**重复出现 ≥2 次**或**后果严重**的错误
- `pattern` 用一句话概括现象，`root_cause` 写根本原因（不是现象本身）
- `category` 复用既有分类习惯（如 `err-null-check`、`err-forget-accessor`）
- 每个错误模式附带 `remedy` 纠正方法（procedural 记忆的价值所在）

---

## 五、与 tutor_end_session 的衔接

`tutor_end_session` 已内置自动蒸馏步骤（`session_distilled` / `session_closed`）：

- 若 `session_summary` 额外携带 `facts` 字段（list[dict]，结构同上）→ 自动调 `mem_distill`
- 若未携带但 `notes` 非空 → 将 notes 摘要作为一条 general 事实入库（降级通道）
- 同时回填 `sessions`：`ended_at / turn_count / summary / status='closed'`
- 蒸馏失败**不阻断下课**（进入 failed_steps，可补做）

因此：下课时尽量在 `session_summary.facts` 里给出结构化事实，蒸馏质量最高。
