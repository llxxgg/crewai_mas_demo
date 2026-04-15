# 第27课示例代码：Human as 甲方——人工介入的三个工程节点

本课在第26课四步任务链基础上增加 **3个人工确认节点**，新增 **SOP 制定与选择流程**，并实现了三态状态机的完整运用。

**使用通用 DigitalWorkerCrew 框架**：所有角色（Manager、PM）共用同一个类，角色身份由 workspace 文件决定。

---

## 核心教学点

| 概念 | 说明 |
|------|------|
| **单一接口原则** | `human.json` 只由编排器（以 manager 身份）写入，LLM Agent 不直接接触人类 |
| **编排器控制时机** | 何时打扰人由脚本决定，不由 LLM 自行判断 |
| **通用框架** | `DigitalWorkerCrew` × N 实例（同一个类），角色身份来自 workspace |
| **wait_for_human()** | FileLock 读 `human.json`，命令行 `input()` 等待用户确认 |
| **多轮迭代** | 需求澄清和 SOP 制定均支持人工反馈驱动的多轮修订 |
| **两个时点解耦** | 时点A（SOP制定）与时点B（任务执行）完全独立 |
| **三态状态机** | agent 邮箱：`unread → in_progress → done` |

---

## 目录结构

```
m4l27/
├── run_demo.py               # 【新版】时点B：5步任务链 + 3个确认节点（DigitalWorkerCrew）
├── m4l27_sop_setup.py        # 【新版】时点A：SOP 制定入口（DigitalWorkerCrew）
├── m4l27_config.py           # 共享路径常量
├── m4l27_run.py              # [旧版] 任务执行入口（5个特异性 Crew，对比用）
├── m4l27_manager.py          # [旧版] Manager 五个 Crew（对比用）
├── m4l27_pm.py               # [旧版] PM Crew（对比用）
├── test_m4l27.py             # 单元测试（24个）+ 集成测试（7个，需 LLM）
├── conftest.py               # pytest fixtures
├── tools/
│   └── mailbox_ops.py        # 三态状态机（send_mail / read_inbox / mark_done / reset_stale）
├── sandbox-docker-compose.yaml
└── workspace/
    ├── manager/              # Manager workspace（soul/agent/user/memory）
    ├── pm/                   # PM workspace
    └── shared/               # 共享工作区
        ├── mailboxes/        # manager.json / pm.json / human.json
        ├── needs/            # requirements.md
        ├── design/           # product_spec.md
        └── sop/              # SOP 模板库 + active_sop.md
```

---

## 新旧对比

| 维度 | 旧版（m4l27_run.py + m4l27_manager.py） | 新版（run_demo.py） |
|------|------|------|
| 类 | RequirementsDiscoveryCrew + SOPSelectorCrew + ManagerAssignCrew + ManagerReviewCrew + SOPCreatorCrew（5个特异类） | DigitalWorkerCrew × 6 实例（同一个类） |
| role/goal | 硬编码角色名和目标 | 通用"数字员工"，身份来自 workspace |
| 通信 | CrewAI 工具包装 | mailbox-ops Skill（CLI + sandbox） |
| 编排 | 硬编码 Crew 名称 | 通用 DigitalWorkerCrew，kickoff(user_request) |
| Session | _SessionMixin 手动管理 | DigitalWorkerCrew 内置 |

---

## 运行步骤

### 第一步：启动沙盒

```bash
cd /path/to/crewai_mas_demo/m4l27
docker compose -f sandbox-docker-compose.yaml up -d

# 验证
curl -s http://localhost:8027/mcp | head -1   # Manager
curl -s http://localhost:8028/mcp | head -1   # PM
```

| 角色 | 沙盒端口 | 个人区挂载 | 共享区挂载 |
|------|---------|-----------|-----------|
| Manager | 8027 | `workspace/manager` | `workspace/shared` |
| PM | 8028 | `workspace/pm` | `workspace/shared` |

### 第二步（可选）：制定 SOP 模板（时点A）

```bash
cd /path/to/crewai_mas_demo
python3 m4l27/m4l27_sop_setup.py
python3 m4l27/m4l27_sop_setup.py --name code_review_sop --task "代码评审流程设计"
```

> 课程自带示例 SOP，可跳过此步直接运行时点B。

### 第三步：运行任务演示（时点B）

```bash
cd /path/to/crewai_mas_demo
python3 m4l27/run_demo.py
```

启动后先提示输入需求，之后自动推进，**遇到确认节点时暂停等待 y/n 输入**。

### 可选：调整多轮迭代上限

```bash
MAX_CLARIFICATION_ROUNDS=5 python3 m4l27/run_demo.py
MAX_SOP_ROUNDS=3 python3 m4l27/m4l27_sop_setup.py
```

---

## 完整流程说明

### 时点A：SOP 制定（m4l27_sop_setup.py）

```
DigitalWorkerCrew(manager) → 按 sop-creator skill 设计草稿 → draft_{name}.md
  ↓
⏸️ 确认节点  human.json(sop_draft_confirm) → y/n
  → n：收集反馈 → 下一轮修订
  → y：重命名为 {name}.md（正式 SOP 模板）
```

### 时点B：任务执行（run_demo.py）

```
步骤1  DigitalWorkerCrew(manager)  需求澄清 → requirements.md
  ↓ ⏸️ 确认节点1  human.json(needs_confirm)
步骤2  DigitalWorkerCrew(manager)  SOP 选择 → active_sop.md
  ↓ ⏸️ 确认节点2  human.json(sop_confirm)
步骤3  DigitalWorkerCrew(manager)  向 PM 发 task_assign
  ↓
步骤4  DigitalWorkerCrew(pm)       写 product_spec.md → 发 task_done
  ↓ ⏸️ 确认节点3  human.json(checkpoint_request)
步骤5  DigitalWorkerCrew(manager)  验收 → review_result.md
```

---

## 清理环境（支持重跑）

```bash
cd /path/to/crewai_mas_demo/m4l27

# 清空邮箱
echo "[]" > workspace/shared/mailboxes/manager.json
echo "[]" > workspace/shared/mailboxes/pm.json
echo "[]" > workspace/shared/mailboxes/human.json

# 清理产出
rm -f workspace/shared/needs/requirements.md
rm -f workspace/shared/design/product_spec.md
rm -f workspace/shared/sop/active_sop.md
rm -f workspace/manager/review_result.md

# 清理 session 历史
rm -rf workspace/manager/sessions workspace/pm/sessions
```

---

## 运行测试

```bash
cd /path/to/crewai_mas_demo

# 单元测试（24个，不需要沙盒/API）
python3 -m pytest m4l27/test_m4l27.py::TestHumanInboxEmpty -v
python3 -m pytest m4l27/test_m4l27.py::TestSinglePointOfContact -v
python3 -m pytest m4l27/test_m4l27.py::TestWaitForHuman -v
python3 -m pytest m4l27/test_m4l27.py::TestBuildClarificationInputs -v
python3 -m pytest m4l27/test_m4l27.py::TestThreeStateMachine -v
python3 -m pytest m4l27/test_m4l27.py::TestCheckSopExists -v
python3 -m pytest m4l27/test_m4l27.py::TestGenericFramework -v

# 集成测试（需要沙盒 + LLM API）
python3 -m pytest m4l27/test_m4l27.py -v -k "needs_llm" -s
```

### 测试用例一览

| ID | 类名 | 说明 | 需要LLM |
|----|------|------|---------|
| T_unit_1~2 | `TestHumanInboxEmpty` | human.json 为空/类型不匹配 | ✗ |
| T_unit_2~3 | `TestSinglePointOfContact` | PM 不可写 human.json / Manager 可以 | ✗ |
| T_unit_4~6 | `TestWaitForHuman` | 确认/拒绝/反馈收集 | ✗ |
| T_unit_7~9 | `TestBuildClarificationInputs` | 多轮澄清输入构造 + 花括号转义 | ✗ |
| T_unit_10~13 | `TestThreeStateMachine` | 三态状态机：send/read/mark_done/reset_stale | ✗ |
| T_unit_14~15 | `TestCheckSopExists` | active_sop.md 存在检查 | ✗ |
| T_unit_16~24 | `TestGenericFramework` | DigitalWorkerCrew 导入/常量/backstory/端口/模板/run_demo兼容 | ✗ |
| T_int_1~4 | 旧版集成测试 | RequirementsDiscoveryCrew 等 5 个 Crew | ✅ |
| T_int_g1~g3 | 新版集成测试 | DigitalWorkerCrew(manager/pm) 需求/分配/执行 | ✅ |

---

## 三态状态机

```
发送  → status: unread
取走  → status: in_progress + processing_since 时间戳
完成  → status: done（编排器调用 mark_done）
崩溃  → reset_stale() 恢复为 unread
```

human 邮箱使用简化的 `read` 字段（同步确认，不需要三态）。

---

## 常见问题

**Q：运行到确认节点卡住不动？**
正常行为——程序在等 `input()`。输入 `y` 继续，`n` 拒绝。

**Q：没有 SOP 库怎么办？**
课程目录自带示例 SOP，可直接运行 `run_demo.py`。

**Q：报 `ModuleNotFoundError`？**
确认从 `crewai_mas_demo/` 目录运行：
```bash
cd /path/to/crewai_mas_demo
python3 m4l27/run_demo.py
```

**Q：停止沙盒？**
```bash
docker compose -f sandbox-docker-compose.yaml down
```
