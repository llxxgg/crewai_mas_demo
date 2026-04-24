# 第32课：安全层——沙箱守卫、权限网关与凭证注入

本课在可观测性（L30）和可靠性（L31）基础上叠加安全层：SandboxGuard 输入消毒、PermissionGate 工具权限控制、SecureToolWrapper 凭证注入、SecurityAuditLogger 审计日志，形成三层堆叠的完整 Hook 体系。

> **核心教学点**：确定性输入消毒（零 LLM 依赖）、Deny > Ask > Allow 权限模型、运行时凭证注入（LLM 不可见）、安全审计链、`dispatch_gate` vs `dispatch`、三层堆叠（可观测性+可靠性+安全）

---

## 目录结构

```
m5l32/
├── demo.py                        # 端到端演示（含攻击模拟）
├── agents.yaml                    # Agent 定义
├── tasks.yaml                     # Task 定义
├── .env.example                   # 环境变量模板
├── hook_framework/                # Hook 框架核心
│   ├── __init__.py
│   ├── registry.py                # EventType + GuardrailDeny + HookRegistry
│   ├── loader.py                  # YAML 驱动加载器（hooks + strategies + deps）
│   └── crew_adapter.py            # CrewAI 机制 → HookRegistry 事件映射
├── shared_hooks/                  # 全局 Hook（所有 Agent 共享）
│   ├── hooks.yaml                 # 完整配置：可观测性+可靠性+安全策略
│   ├── structured_log.py          # JSON 结构化日志
│   ├── langfuse_trace.py          # Langfuse v4 追踪
│   ├── sandbox_guard.py           # SandboxGuard：确定性输入消毒
│   ├── permission_gate.py         # PermissionGate：Deny > Ask > Allow
│   ├── credential_inject.py       # SecureToolWrapper：运行时凭证注入
│   ├── audit_logger.py            # SecurityAuditLogger：JSONL 审计日志
│   ├── cost_guard.py              # CostGuard：预算执行
│   ├── loop_detector.py           # LoopDetector：循环检测
│   └── retry_tracker.py           # RetryTracker：重试追踪
├── workspace/demo_agent/
│   ├── security.yaml              # 权限策略（per-tool Deny/Ask/Allow）
│   ├── audit.log                  # 审计日志输出
│   └── hooks/
│       ├── hooks.yaml             # 工作空间级 Hook
│       └── task_audit.py          # 任务完成审计
└── tests/                         # 18 个测试文件，82 个测试用例
    ├── test_registry.py
    ├── test_loader.py
    ├── test_adapter.py
    ├── test_dispatch_gate.py
    ├── test_sandbox_guard.py
    ├── test_permission_gate.py
    ├── test_credential_inject.py
    ├── test_audit_logger.py
    ├── test_cost_guard.py
    ├── test_loop_detector.py
    ├── test_retry_tracker.py
    ├── test_install_hooks.py
    ├── test_install_security.py
    ├── test_e2e_hooks.py
    ├── test_e2e_reliability.py
    ├── test_e2e_security.py
    └── test_e2e_security_llm.py
```

---

## 快速开始

```bash
cd /path/to/crewai_mas_demo

# 正常执行
python3 m5l32/demo.py

# 攻击模拟：路径穿越注入
python3 m5l32/demo.py --attack inject

# 攻击模拟：权限提升
python3 m5l32/demo.py --attack privilege

# 极低预算测试
python3 m5l32/demo.py --budget 0.001

# 运行测试
python3 -m pytest m5l32/tests/ -v
```

---

## 课堂代码演示学习指南

### 整体架构一览

```
Agent 工具调用
     │
     ▼
dispatch_gate(BEFORE_TOOL_CALL)
     │
     ├─ 1. SandboxGuard（确定性消毒）
     │     ├─ 路径穿越：../../ → 拦截
     │     ├─ 危险命令：rm -rf / sudo → 拦截
     │     ├─ Shell 注入：; & | $() → 拦截
     │     └─ 环境变量：$HOME → 告警
     │     违规 → GuardrailDeny → 链停止
     │
     ├─ 2. PermissionGate（权限检查）
     │     ├─ DENY → GuardrailDeny
     │     ├─ ASK → 日志告警，放行
     │     └─ ALLOW → 静默放行
     │
     ├─ 3. CostGuard（预算检查）
     │     └─ 超预算 → GuardrailDeny
     │
     ▼
Tool 执行（SecureToolWrapper 注入凭证）
     │
     ▼
dispatch_gate(AFTER_TOOL_CALL)
     │
     ├─ RetryTracker（失败计数）
     ├─ LoopDetector（状态哈希去重）
     └─ SecurityAuditLogger（审计记录）
```

### 学习路线

---

#### 第一步：看确定性输入消毒

**阅读文件**：`shared_hooks/sandbox_guard.py`

| 检查项 | 正则模式 | 示例 |
|--------|---------|------|
| 路径穿越 | `\.\./` | `../../etc/passwd` |
| 危险命令 | `rm\s+-rf`, `sudo`, `chmod\s+777` | `rm -rf /`, `sudo cat` |
| Shell 注入 | `;`, `&`, `\|`, `` ` ``, `$(` | `; cat /etc/shadow` |
| 环境变量 | `\$\w+`, `\$\{` | `$HOME`, `${SECRET}` |

**理解要点**：核心原则——"Prompt is advice, Hook is law"。安全规则用正则表达式硬编码，零 LLM 依赖。无论 prompt 怎么写，`../../etc/passwd` 都会被拦截。灵感来源：Claude Code 的 `cyberRiskInstruction.ts`。

---

#### 第二步：看权限网关

**阅读文件**：`shared_hooks/permission_gate.py` + `workspace/demo_agent/security.yaml`

```yaml
# security.yaml 示例
tools:
  knowledge_search: allow
  shell_executor: deny
default: ask
```

| 级别 | 行为 | 适用场景 |
|------|------|---------|
| DENY | 抛出 `GuardrailDeny` | 高危工具（shell、删除） |
| ASK | 日志告警，允许执行 | 未知/新工具（人工审核） |
| ALLOW | 静默放行 | 已验证的安全工具 |

**理解要点**：Deny > Ask > Allow 是优先级——如果 security.yaml 中没有配置某个工具，使用 `default` 级别。灵感来源：Claude Code 的 `permissions.ts`。

---

#### 第三步：看凭证注入

**阅读文件**：`shared_hooks/credential_inject.py`

```python
SecureToolWrapper.wrap(tool, {"api_key": "ENV_VAR_NAME"})
```

| 设计决策 | 原因 |
|---------|------|
| Monkeypatch `_run` | 在工具执行层注入，不修改 schema |
| 从环境变量读取 | 凭证不出现在代码或配置中 |
| LLM 不可见 | 工具 description 和 schema 不变，LLM 看不到密钥 |

**理解要点**：传统做法是把 API Key 写在工具的 description 或 Agent 的 backstory 中——这意味着 LLM 能"看到"密钥，存在泄露风险。`SecureToolWrapper` 在执行层注入，LLM 的上下文中完全没有密钥。

---

#### 第四步：看审计日志

**阅读文件**：`shared_hooks/audit_logger.py`

**理解要点**：`SecurityAuditLogger` 是所有安全组件的"汇聚点"——SandboxGuard 和 PermissionGate 通过 `deps` 注入拿到同一个 Logger 实例，所有安全事件（拦截、告警、放行）写入同一个 JSONL 文件，支持事后审计取证。

---

#### 第五步：看 dispatch_gate vs dispatch

**阅读文件**：`hook_framework/registry.py`（搜索 `dispatch_gate`）

| 方法 | 异常处理 | 适用层 |
|------|---------|--------|
| `dispatch()` | 吞掉所有异常 | 可观测性（日志、追踪不能中断 Agent） |
| `dispatch_gate()` | 传播 `GuardrailDeny`，吞掉其他 | 安全+可靠性（必须能阻断操作） |

**理解要点**：这是"双轨调度"设计——观测性 Hook（structured_log、langfuse_trace）用 `dispatch`（绝不干扰 Agent），安全/可靠性 Hook（sandbox_guard、permission_gate、cost_guard）用 `dispatch_gate`（必须能拦截危险操作）。

---

#### 第六步：看 hooks.yaml 中的策略顺序与依赖注入

**阅读文件**：`shared_hooks/hooks.yaml`（strategies 部分）

```yaml
strategies:
  - class: audit_logger.SecurityAuditLogger    # 1️⃣ 最先创建（被依赖）
  - class: sandbox_guard.SandboxGuard          # 2️⃣ 输入消毒
    deps: { audit: SecurityAuditLogger }       #    依赖审计
  - class: permission_gate.PermissionGate      # 3️⃣ 权限检查
    deps: { audit: SecurityAuditLogger }       #    依赖审计
  - class: retry_tracker.RetryTracker          # 4️⃣ 重试追踪
  - class: cost_guard.CostGuard                # 5️⃣ 预算执行
  - class: loop_detector.LoopDetector          # 6️⃣ 循环检测
```

**理解要点**：YAML 中的顺序 = 注册顺序 = 执行顺序。在 `BEFORE_TOOL_CALL` 事件上：SandboxGuard 最先执行，如果它 Deny 了，PermissionGate 和 CostGuard 都不会执行。`deps` 机制实现了跨策略的依赖注入——多个策略共享同一个审计 Logger 实例。

---

#### 第七步：看攻击模拟

**阅读文件**：`demo.py`

| 模式 | 命令 | 模拟攻击 |
|------|------|---------|
| 正常 | `python3 demo.py` | 安全工具正常执行 |
| 注入 | `--attack inject` | 路径穿越 `../../etc/passwd` → SandboxGuard 拦截 |
| 提权 | `--attack privilege` | 赋予 `shell_executor` → PermissionGate 拦截 |
| 预算 | `--budget 0.001` | 极低预算 → CostGuard 拦截 |

**理解要点**：三种攻击分别测试三个安全组件。运行后观察日志和 `audit.log`，看每个组件如何独立发挥作用。

---

#### 第八步：理解三层堆叠架构

```
┌─────────────────────────────┐
│  第一层：可观测性（L30）       │
│  structured_log + langfuse   │
│  dispatch()（不阻断）         │
├─────────────────────────────┤
│  第二层：可靠性（L31）         │
│  cost_guard + loop_detector  │
│  + retry_tracker             │
│  dispatch_gate()（可阻断）    │
├─────────────────────────────┤
│  第三层：安全（L32）           │
│  sandbox_guard + permission  │
│  + credential + audit        │
│  dispatch_gate()（可阻断）    │
└─────────────────────────────┘
```

**理解要点**：三层独立但可组合——关掉安全层，可靠性和可观测性仍然工作。每层的 Handler 都是普通 Python 函数/类，通过 YAML 声明式组装，无需改代码。

---

#### 第九步：运行测试

```bash
cd /path/to/crewai_mas_demo
python3 -m pytest m5l32/tests/ -v
```

82 个测试覆盖：注册表（6）、加载器（3+）、适配器（5+）、dispatch_gate（5）、sandbox_guard（6+）、permission_gate（6+）、credential_inject（4）、audit_logger（3）、cost_guard（6+）、loop_detector（4+）、retry_tracker（4+）、安装验证（3+）、E2E（6+）。

---

### 学习检查清单

- [ ] "Prompt is advice, Hook is law" 什么意思？（安全规则用确定性代码执行，不靠 LLM 理解 prompt）
- [ ] Deny > Ask > Allow 的优先级如何体现？（DENY 直接阻断，ASK 告警放行，ALLOW 静默放行）
- [ ] 凭证注入为什么不能写在 backstory 中？（LLM 能"看到"密钥，存在通过对话泄露的风险）
- [ ] `dispatch_gate` 和 `dispatch` 的区别？（前者传播 GuardrailDeny 可以阻断，后者吞掉所有异常不阻断）
- [ ] hooks.yaml 中策略的顺序为什么重要？（决定执行顺序——SandboxGuard Deny 后 PermissionGate 不再执行）
- [ ] Agent 注入和 Chatbot 注入的区别？（Agent 有真实副作用——文件删除、数据外泄——不能只靠 prompt 防御）
