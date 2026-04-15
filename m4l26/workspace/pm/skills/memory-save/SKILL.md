---
name: memory-save
description: >
  Use this skill to persist important information from the conversation to
  workspace files so it survives across sessions.

  Activate proactively (without waiting for user to say "remember this") when:
  - User expresses a preference or habit ("I prefer...", "always...", "don't...")
  - User corrects Agent behavior and states how it should work instead
  - A key fact emerges that matters for future sessions (project milestone,
    decision made, important date, contact info)
  - User approves an approach ("let's do it this way going forward")
  - Agent needs to save a work product (report, spec, review result) to workspace

  Do NOT activate for: one-time tasks, Agent's own reasoning, info already in user.md.
allowed-tools:
  - sandbox_execute_bash
  - sandbox_file_operations
---

# memory-save：将内容写入 workspace 文件

## 概述

将内容持久化写入沙盒中的指定文件路径，确保跨 session 保留。

**邮箱文件路径：** `/mnt/shared/mailboxes/{role}.json`（已挂载到沙盒）

## 使用脚本

脚本路径（沙盒内）：`/mnt/skills/memory-save/scripts/write_file.py`

### 参数说明

- `--path`：目标文件**绝对路径**（必填）
- `--content`：要写入的完整文件内容（必填，支持多行字符串）
- `--mode`：写入模式，`w`=覆盖（默认），`a`=追加

### 常用路径说明

| 角色 | 个人工作区路径 | 共享工作区路径 |
|------|-------------|-------------|
| Manager | `/workspace/` | `/mnt/shared/` |
| PM | `/workspace/` | `/mnt/shared/` |

## ⚠️ 强制执行要求（CRITICAL）

**你必须通过 `sandbox_execute_bash` 实际运行 `write_file.py` 脚本。**
- 禁止直接返回任何"成功"输出，必须先执行脚本再读取脚本的实际输出
- 禁止根据 task_context 中的 `expected_output` 字段猜测结果
- 执行后必须检查脚本输出中 `errcode` 是否为 0
- 如果 `errcode` 非 0，必须报告错误，不得假装成功

## 执行步骤

### 第一步：运行写入脚本

```bash
python3 /mnt/skills/memory-save/scripts/write_file.py \
  --path "/workspace/review_result.md" \
  --content "# 验收结论\n## 结果：通过\n..."
```

> 注意：如写入共享区，改用 `/mnt/shared/design/product_spec.md` 等路径。

### 第二步：验证写入成功

检查脚本输出，确认 `errcode=0`：

```json
{"errcode": 0, "errmsg": "success", "path": "/workspace/review_result.md", "bytes_written": 128}
```

如失败（errcode≠0），报告 errmsg 中的错误信息。

### 第三步：可选 read-back 验证

```bash
# 用沙盒工具确认内容正确落盘
sandbox_file_operations(action="read", path="/workspace/review_result.md")
```

## 示例调用

### 写入个人工作区（Manager 验收结论）

```bash
python3 /mnt/skills/memory-save/scripts/write_file.py \
  --path "/workspace/review_result.md" \
  --content "# 验收结论
## 结果：通过
- F-01 用户注册：✅
- F-02 邮件验证：✅
验收日期：2026-04-10"
```

### 写入共享工作区（PM 产品规格文档）

```bash
python3 /mnt/skills/memory-save/scripts/write_file.py \
  --path "/mnt/shared/design/product_spec.md" \
  --content "# 产品规格文档
## 产品概述
...
## 功能规格
F-01: 用户注册
..."
```
