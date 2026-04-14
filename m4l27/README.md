# 第27课示例代码：Human as 甲方——人工介入的三个工程节点

本课在第26课四步任务链基础上增加 **3个人工确认节点**，新增 **SOP 制定与选择流程**，并实现了三态状态机的完整运用。

---

## 核心教学点

| 概念 | 说明 |
|------|------|
| **单一接口原则** | `human.json` 只由运行脚本（以 manager 身份）写入，LLM Agent 不直接接触人类 |
| **编排器控制时机** | 何时打扰人由脚本决定，不由 LLM 自行判断 |
| **wait_for_human()** | FileLock 读 `human.json`，命令行 `input()` 等待用户确认，y/n 控制流程走向 |
| **HumanDecision** | `wait_for_human()` 的返回值，封装 `confirmed` + `feedback`，支持 `if decision:` 简洁写法 |
| **多轮迭代** | 需求澄清（最多 `MAX_CLARIFICATION_ROUNDS` 轮）和 SOP 制定（最多 `MAX_SOP_ROUNDS` 轮）均支持人工反馈驱动的多轮修订 |
| **两个时点解耦** | 时点A（SOP制定）与时点B（任务执行）完全独立，使用不同脚本 |
| **三态状态机** | agent 邮箱：`unread → in_progress → done`；Crew 成功后调用 `mark_done_all_in_progress` |
| **SOP 生命周期** | `sop_setup.py` 制定模板 → `run.py` 的 `SOPSelectorCrew` 选出最匹配的 → 写入 `active_sop.md` → 执行时依据 |

---

## 目录结构

```
m4l27/
├── m4l27_sop_setup.py        # 时点A：SOP 制定入口（人机协作设计 SOP 模板）
├── m4l27_run.py              # 时点B：任务执行入口（5步 + 3个确认节点）
├── m4l27_manager.py          # Manager 五个 Crew
├── m4l27_config.py           # 共享路径常量（所有脚本统一 import）
├── m4l27_pm.py               # PM Crew（读邮件 → 写产品文档 → 通知）
├── test_m4l27.py             # 单元测试（15个）+ 集成测试（5个，需 LLM）
├── conftest.py               # pytest fixtures（clean_crewai_hooks 等）
├── tools/
│   ├── __init__.py
│   └── mailbox_ops.py        # 三态状态机：send_mail / read_inbox / mark_done / reset_stale
├── sandbox-docker-compose.yaml
└── workspace/
    ├── manager/              # Manager 个人区（sessions/、review_result.md）
    ├── pm/                   # PM 个人区（sessions/）
    └── shared/               # 共享工作区
        ├── mailboxes/        # manager.json / pm.json / human.json
        ├── needs/            # requirements.md（需求澄清后写入）
        ├── design/           # product_spec.md（PM输出）
        └── sop/              # *.md（SOP 模板库）+ active_sop.md（本次选中的 SOP）
```

---

## 两个时点的执行顺序

```
时点A（首次使用前）：python m4l27/m4l27_sop_setup.py
      ↓ 制定 SOP 模板，写入 shared/sop/product_design_sop.md

时点B（每次提交任务）：python m4l27/m4l27_run.py
      ↓ SOPSelectorCrew 从 SOP 库选出最匹配的 SOP
```

**时点A 是前置条件**：`run.py` 在步骤2会调用 `SOPSelectorCrew` 从 SOP 库选 SOP。如果 SOP 库为空（仅有课程自带的示例 SOP 时可跳过），请先运行 `sop_setup.py`。

> 课程自带两个示例 SOP：`product_design_sop.md`（完整版）和 `product_design_lite_sop.md`（精简版），无需额外运行 `sop_setup.py` 即可直接演示 `run.py`。

---

## Manager 五个 Crew（m4l27_manager.py）

| Crew | 时点 | 说明 |
|------|------|------|
| `RequirementsDiscoveryCrew` | B（步骤1） | 用 requirements-discovery skill 四维发问，写 `requirements.md` |
| `SOPCreatorCrew` | A | 用 sop-creator skill 设计 SOP 四要素，写 `draft_{name}.md` |
| `SOPSelectorCrew` | B（步骤2） | 用 sop-selector skill 从 SOP 库选最匹配，写 `active_sop.md` |
| `ManagerAssignCrew` | B（步骤3） | 读 `active_sop.md` + 需求文档，向 PM 发 `task_assign` |
| `ManagerReviewCrew` | B（步骤5） | 读 PM 回邮，验收产品文档，写 `review_result.md` |

---

## 运行步骤

### 第一步：启动沙盒

```bash
cd /path/to/crewai_mas_demo/m4l27
docker compose -f sandbox-docker-compose.yaml up -d
```

| 角色 | 沙盒端口 | 个人区挂载 | 共享区挂载 |
|------|---------|-----------|-----------|
| Manager | 8027 | `workspace/manager` | `workspace/shared` |
| PM | 8028 | `workspace/pm` | `workspace/shared` |

### 第二步（可选）：制定 SOP 模板（时点A）

```bash
cd /path/to/crewai_mas_demo
python m4l27/m4l27_sop_setup.py
```

如需指定 SOP 名称或任务背景：
```bash
python m4l27/m4l27_sop_setup.py --name code_review_sop --task "代码评审流程设计"
```

制定完成后 SOP 模板写入 `workspace/shared/sop/{name}.md`。

### 第三步：运行任务演示（时点B）

```bash
cd /path/to/crewai_mas_demo
python m4l27/m4l27_run.py
```

启动后先提示输入需求，之后自动推进，**遇到确认节点时暂停等待 y/n 输入**。

### 可选：调整多轮迭代上限

```bash
MAX_CLARIFICATION_ROUNDS=5 python m4l27/m4l27_run.py
MAX_SOP_ROUNDS=3 python m4l27/m4l27_sop_setup.py
```

---

## 完整流程说明

### 时点A：SOP 制定流程（m4l27_sop_setup.py）

```
SOPCreatorCrew → 按 sop-creator skill 四要素框架设计草稿 → 写 draft_{name}.md
  ↓
⏸️ 确认节点  write human.json(sop_draft_confirm) → 终端等待 y/n
  → n：收集反馈 → 下一轮修订（最多 MAX_SOP_ROUNDS 轮）
  → y：draft_{name}.md 重命名为 {name}.md（正式 SOP 模板）
```

### 时点B：任务执行流程（m4l27_run.py）

```
[清理] 删除上次的 active_sop.md，确保本次重新选择

步骤1  Manager   需求澄清（RequirementsDiscoveryCrew）→ 写 requirements.md
  ↓
⏸️ 确认节点1  human.json(needs_confirm)
  → n：收集反馈 → 下一轮修订（最多 MAX_CLARIFICATION_ROUNDS 轮）
  → y：需求确认，继续
  ↓
步骤2  Manager   SOP 选择（SOPSelectorCrew）→ 写 active_sop.md
  ↓
⏸️ 确认节点2  human.json(sop_confirm)
  → n：SOP 未确认，终止（修改 SOP 库后重新运行）
  → y：SOP 确认，继续
  ↓
步骤3  Manager   读 active_sop.md → 向 PM 发 task_assign（ManagerAssignCrew）
  ↓
步骤4  PM        读邮件 → 写 product_spec.md → 发 task_done（PMExecuteCrew）
         + mark_done_all_in_progress("pm")  ← 三态确认：PM 消息已处理
  ↓
⏸️ 确认节点3  human.json(checkpoint_request)
  → n：终止
  → y：继续
  ↓
步骤5  Manager   读邮件 → 验收文档 → 写 review_result.md（ManagerReviewCrew）
         + mark_done_all_in_progress("manager")  ← 三态确认：Manager 消息已处理
```

---

## 三态状态机

agent 邮箱（manager / pm）使用三态状态机，对应 AWS SQS Visibility Timeout：

```
发送  → status: unread
取走  → status: in_progress + processing_since 时间戳
完成  → status: done（由编排器调用 mark_done 确认）
崩溃  → reset_stale() 将超时 in_progress 恢复为 unread
```

human 邮箱使用简化的 `read` 字段（同步确认，不需要三态）。

---

## 运行测试（不需要沙盒）

```bash
cd /path/to/crewai_mas_demo
python -m pytest m4l27/test_m4l27.py -v
```

仅跑单元测试（无需 LLM）：
```bash
python -m pytest m4l27/test_m4l27.py -v -k "not needs_llm"
```

### 测试用例一览

| ID | 类名 | 说明 | 需要LLM |
|----|------|------|---------|
| T_unit_1 | `TestHumanInboxEmpty` | human.json 为空/类型不匹配时返回空 | ✗ |
| T_unit_2 | `TestSinglePointOfContact` | PM/未知角色写 human.json → raise ValueError | ✗ |
| T_unit_3 | `TestSinglePointOfContact` | Manager 写 human.json 成功 | ✗ |
| T_unit_4 | `TestWaitForHuman` | 用户 y → 消息标记 read=True，returned confirmed=True | ✗ |
| T_unit_5 | `TestWaitForHuman` | 用户 n → 消息也标记 read=True + rejected=True | ✗ |
| T_unit_6 | `TestWaitForHuman` | allow_feedback=True 时拒绝并输入反馈 | ✗ |
| T_unit_7 | `TestBuildClarificationInputs` | 首轮 revision_context 为空字符串 | ✗ |
| T_unit_8 | `TestBuildClarificationInputs` | 后续轮 revision_context 含历史反馈 | ✗ |
| T_unit_9 | `TestBuildClarificationInputs` | 反馈中含 `{}` 时自动转义 | ✗ |
| T_unit_10 | `TestThreeStateMachine` | send_mail 写 agent 邮箱时 status=unread | ✗ |
| T_unit_11 | `TestThreeStateMachine` | read_inbox 后磁盘状态变为 in_progress | ✗ |
| T_unit_12 | `TestThreeStateMachine` | mark_done 将 in_progress 标记为 done | ✗ |
| T_unit_13 | `TestThreeStateMachine` | reset_stale 将超时 in_progress 恢复为 unread | ✗ |
| T_unit_14 | `TestCheckSopExists` | active_sop.md 不存在时 check_sop_exists 返回 False | ✗ |
| T_unit_15 | `TestCheckSopExists` | active_sop.md 存在时 check_sop_exists 返回 True | ✗ |
| T_int_1 | `TestIntegrationRequirements` | RequirementsDiscoveryCrew → requirements.md 存在 | ✅ |
| T_int_2 | `TestIntegrationTaskAssign` | ManagerAssignCrew → pm.json 有 task_assign | ✅ |
| T_int_3 | `TestIntegrationProductSpec` | PMExecuteCrew → product_spec.md 存在 | ✅ |
| T_int_4 | `TestIntegrationReviewResult` | ManagerReviewCrew → review_result.md 存在 | ✅ |
| T_int_5 | `TestIntegrationSOPCreator` | SOPCreatorCrew → draft_*.md 存在 | ✅ |

---

## 与第26课的对比

| 项目 | 第26课 | 第27课 |
|------|--------|--------|
| 步骤数 | 4步 | 5步（新增SOP选择步骤） |
| 人工节点 | 无 | 3个（需求确认 + SOP确认 + 设计确认） |
| 多轮迭代 | 无 | 需求澄清 + SOP制定均支持多轮 |
| Manager Crew 数量 | 2（分配+验收） | 5（需求+SOP制定+SOP选择+分配+验收） |
| human.json | 无 | 有（单一接口，只由脚本写） |
| 三态状态机 | 有（基础版） | 完整运用（+mark_done+reset_stale） |
| SOP | 静态文件 | 人机协作制定 + 智能选择 |
| 入口脚本 | 1个（run.py） | 2个（sop_setup.py + run.py） |

---

## 常见问题

**Q：运行到确认节点卡住不动？**
正常行为——程序在等 `input()`。终端会显示：
```
⏸️  [人工确认节点] 需求文档确认（第1轮）
  你的决定 (y/n)：
```
输入 `y` 回车继续，输入 `n` 进入反馈收集（步骤1）或终止（步骤3）。

**Q：没有 SOP 库怎么办？**
课程目录自带两个示例 SOP：
- `workspace/shared/sop/product_design_sop.md`（完整版）
- `workspace/shared/sop/product_design_lite_sop.md`（精简版）

可直接运行 `run.py` 演示，无需先运行 `sop_setup.py`。

**Q：想清除状态重新跑？**
```bash
echo "[]" > workspace/shared/mailboxes/manager.json
echo "[]" > workspace/shared/mailboxes/pm.json
echo "[]" > workspace/shared/mailboxes/human.json
rm -f workspace/shared/needs/requirements.md
rm -f workspace/shared/design/product_spec.md
rm -f workspace/shared/sop/active_sop.md
rm -f workspace/manager/review_result.md
rm -f workspace/manager/sessions/*.json workspace/manager/sessions/*.jsonl
rm -f workspace/pm/sessions/*.json workspace/pm/sessions/*.jsonl
```

**Q：报 `ModuleNotFoundError`？**
确认从 `crewai_mas_demo/` 目录运行：
```bash
cd /path/to/crewai_mas_demo
python m4l27/m4l27_run.py
```
