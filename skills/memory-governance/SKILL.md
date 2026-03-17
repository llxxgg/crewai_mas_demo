---
name: memory-governance
description: >
  Use this skill to audit and clean up workspace memory files and the skills
  directory. Activate when:
  - memory.md is approaching 150+ lines (Bootstrap limit is 200)
  - User requests a memory cleanup or audit
  - Skills directory has grown large and may contain duplicates or stale entries
  - memory-save reports that memory.md is near the limit

  Do NOT activate for: normal conversation, saving new memories (use
  memory-save), creating new skills (use skill-creator).
allowed-tools:
  - Read
  - Write
  - Bash
---

# memory-governance：记忆与 Skill 治理

## 概述

定期审计 workspace 记忆文件和 skills/ 目录，输出结构化分析报告，
用户确认后执行清理操作，防止记忆腐化和技能目录膨胀。

执行频率：每月一次，或 memory-save 检测到 memory.md 超过 180 行时主动触发。

**为什么需要治理：**
混乱的长记忆是整个应用的杀手。记忆腐化有两条路径：
1. **信息过时**：user.md 有旧偏好、memory.md 有死链（指向已删除文件）
2. **索引爆炸**：memory.md 不断追加接近 200 行、skills/ 有重复功能的 Skill

## 步骤

### 第一步：扫描，生成 JSON 分析报告

读取以下文件，进行结构化分析：
- `/workspace/memory.md`：检查行数、死链（索引条目对应文件不存在）
- `/workspace/*.md`：检查 topic 文件的最后修改时间
- `/mnt/skills/load_skills.yaml`：检查已注册 Skill 列表
- `/mnt/skills/*/SKILL.md`：检查 description 是否有重叠

生成内部 JSON 分析（精确，便于后续操作）：

```json
{
  "memory_issues": [
    {
      "type": "dead_link",
      "entry": "投资记录 → memory_invest.md",
      "reason": "文件不存在"
    },
    {
      "type": "near_limit",
      "current_lines": 178,
      "limit": 200,
      "action": "trigger_governance"
    }
  ],
  "topic_files": [
    {
      "file": "memory_2023_project.md",
      "last_modified": "2023-11-01",
      "days_since": 480,
      "action": "archive"
    }
  ],
  "skill_issues": [
    {
      "type": "duplicate",
      "skills": ["analyze-stock", "hk-stock-analysis"],
      "recommendation": "merge into analyze-hk-stock"
    }
  ]
}
```

### 第二步：生成 MD 治理报告（给用户审批）

将 JSON 分析转换为可读 Markdown，写入 `/workspace/memory_governance_report.md`：

```markdown
# 记忆治理报告 — <日期>

## memory.md 状态
- 当前行数：<n> 行（上限 200 行）
- 状态：<正常 / 警告 / 已超限>

## 发现的问题

### 死链（共 <n> 条）
| 条目 | 原因 | 建议操作 |
|------|------|---------|
| 投资记录 → memory_invest.md | 文件不存在 | 删除此条目 |

### 过期 Topic 文件（<n> 个）
| 文件 | 最后更新 | 建议操作 |
|------|---------|---------|
| memory_2023_project.md | 480 天前 | 归档或删除 |

### Skill 重叠（<n> 组）
| Skill 1 | Skill 2 | 建议 |
|---------|---------|------|
| analyze-stock | hk-stock-analysis | 合并为 analyze-hk-stock |

## 建议操作清单
- [ ] 删除 memory.md 中 <n> 条死链
- [ ] 归档 <n> 个过期 topic 文件到 /workspace/archive/
- [ ] 合并重叠 Skill
```

### 第三步：等待用户确认，再执行清理

**CRITICAL：不得在用户确认前执行任何删除或修改操作**
原因：治理报告可能误判（如文件确实存在但路径格式不同），用户确认是最后防线。
报告生成后，明确提示用户："请确认以上操作清单，回复'确认执行'后我将开始清理。"

用户确认后，按清单逐项执行：
1. 从 memory.md 删除死链条目
2. 将过期 topic 文件移动到 `/workspace/archive/`（不删除，保留历史）
3. 按用户指示合并或禁用重叠 Skill

**CRITICAL：执行后读取验证**
每项操作后读取对应文件，确认变更已落盘、无误删。
