# 第30课：可观测性——Hook 骨架 + Langfuse 全链路追踪

本课构建 Hook 框架骨架，将前序课程的零散 Hook 统一到 5+2 事件体系，并接入 Langfuse 实现全链路追踪。

> **核心教学点**：5+2 事件类型（对齐 Agent Turn 周期）、两层 Hook 配置（全局+Workspace）、HookRegistry 分发机制、CrewAI 适配层映射、Langfuse Docker 自托管追踪、全局 Hook 自动传播到 Sub-Crew

---

## 环境搭建（重要，请按顺序完成）

### Step 1：启动 Langfuse（Docker 自托管，6 容器）

本课使用 Docker 自托管的 Langfuse v3。如果已经有运行中的 Langfuse 实例，跳到 Step 2。

```bash
# 克隆 Langfuse 官方仓库
git clone https://github.com/langfuse/langfuse.git
cd langfuse

# 生成必需的密钥（写入 .env）
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
echo "SALT=$(openssl rand -hex 32)" >> .env
echo "NEXTAUTH_SECRET=$(openssl rand -hex 32)" >> .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)" >> .env
echo "REDIS_AUTH=$(openssl rand -hex 16)" >> .env

# 启动所有容器（Web + Worker + Postgres + Redis + ClickHouse + MinIO）
docker compose up -d

# 等待 2-3 分钟，确认健康状态
curl http://localhost:3000/api/public/health
# 预期输出：{"status":"OK","version":"3.x.x"}
```

启动后访问 http://localhost:3000，首次登录需注册账号（自托管模式，注册即管理员）。

### Step 2：创建 Project 和 API Key

登录 Langfuse Dashboard 后：

1. **创建 Organization**（如 `my-org`）
2. **创建 Project**（如 `course-demo`）
3. 进入 Project → **Settings → API Keys → Create API Key**
4. 记录 `Public Key`（`pk-lf-...`）和 `Secret Key`（`sk-lf-...`）

> 课程演示使用的测试 Key：`pk-lf-course-demo` / `sk-lf-course-demo`，仅限本机使用。

### Step 3：启动 AIO-Sandbox（演示用沙盒）

```bash
cd /path/to/crewai_mas_demo/m5l30
docker compose -f sandbox-docker-compose.yaml up -d

# 等待健康检查通过
docker inspect m5l30-aio-sandbox-1 --format '{{.State.Health.Status}}'
# 预期输出：healthy
```

沙盒端口 `8030`，挂载：
- `workspace/demo_agent/skills → /mnt/skills:ro`（Skill 资源）
- `workspace/demo_agent/output → /workspace/output:rw`（产出物）

### Step 4：配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入真实值：

```bash
# === LLM 配置（阿里云 DashScope） ===
OPENAI_API_KEY=your-dashscope-api-key          # 替换为你的 DashScope API Key
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
AGENT_MODEL=qwen-plus

# === Langfuse（Docker 自托管） ===
LANGFUSE_PUBLIC_KEY=pk-lf-course-demo           # 替换为你的 Public Key
LANGFUSE_SECRET_KEY=sk-lf-course-demo           # 替换为你的 Secret Key
LANGFUSE_BASE_URL=http://localhost:3000          # ⚠️ 必须设置，否则 SDK 会发到 cloud.langfuse.com
```

**关键注意**：`LANGFUSE_BASE_URL` 必须显式设置为 `http://localhost:3000`。如果不设置，Langfuse Python SDK 默认连接 `https://cloud.langfuse.com`，trace 数据不会出现在你的本地实例中。

### Step 5：验证连接

```bash
# 验证 Langfuse API Key 有效
curl -s -u "pk-lf-course-demo:sk-lf-course-demo" \
     "http://localhost:3000/api/public/traces?limit=1"
# 预期输出：{"data":[],"meta":{"page":1,...}}（空列表表示连接正常）
```

---

## 目录结构

```
m5l30/
├── hook_framework/                     # Hook 框架核心
│   ├── __init__.py                     # 导出公共接口
│   ├── registry.py                     # F1-F2: EventType(5+2) + HookContext + HookRegistry
│   ├── loader.py                       # F3-F4: hooks.yaml 解析 + importlib 两层自动加载
│   └── crew_adapter.py                 # F5: CrewAI 4种机制 → HookRegistry 7种事件
├── shared_hooks/                       # 全局 Hook（所有 Agent 共享）
│   ├── hooks.yaml                      # 全局配置：事件 → handler 映射
│   ├── structured_log.py               # F6: 结构化 JSON 日志（stderr）
│   └── langfuse_trace.py              # F7: Langfuse 追踪（trace + generation + span）
├── workspace/                          # 演示 Workspace（25 课 Bootstrap 架构）
│   └── demo_agent/
│       ├── soul.md                     # 💡 Agent 身份
│       ├── agent.md                    # 💡 Agent 职责
│       ├── user.md                     # 💡 用户画像
│       ├── memory.md                   # 💡 记忆索引
│       ├── hooks/
│       │   ├── hooks.yaml              # Workspace 配置
│       │   └── task_audit.py           # F8: 任务审计日志
│       ├── skills/
│       │   ├── load_skills.yaml        # 💡 Skill 清单（task 型）
│       │   └── sop_design/SKILL.md     # 💡 技术设计 SOP（写入文件到沙盒）
│       └── output/                     # 沙盒产出物（设计文档写入此处）
├── sandbox-docker-compose.yaml         # AIO-Sandbox 配置（端口 8030）
├── demo.py                             # F10: Bootstrap + SkillLoader + Hook 全链路演示
├── .env.example                        # 环境变量模板
├── tests/
│   ├── test_registry.py                # T1-T5 + T_extra1: HookRegistry 单元测试
│   ├── test_loader.py                  # T6-T8 + T_extra3: HookLoader 单元测试
│   ├── test_handlers.py                # T9-T11: handler 输出测试
│   ├── test_adapter.py                 # T12-T14 + T_extra2/4: 适配层测试
│   ├── test_e2e_hooks.py               # T15-T16: 全链路端到端测试
│   └── conftest.py                     # pytest fixtures
└── README.md
```

---

## 演示架构（复用 25 课框架）

```
┌─────────────────────────────────────────────────────────────────────┐
│  demo.py                                                            │
│                                                                     │
│  1. build_bootstrap_prompt(workspace/)                              │
│     → 加载 soul.md + agent.md + user.md + memory.md → backstory    │
│                                                                     │
│  2. SkillLoaderTool(skills_dir=workspace/skills/)                   │
│     → 渐进式披露：YAML frontmatter 构建 XML description            │
│     → task 型 Skill：启动 Sub-Crew 在 AIO-Sandbox 中执行           │
│                                                                     │
│  3. Hook 框架（两层加载）                                            │
│     → shared_hooks/：结构化日志 + Langfuse 追踪                     │
│     → workspace/hooks/：任务审计                                    │
│                                                                     │
│  4. 💡 全局 Hook 自动传播到 Sub-Crew                                │
│     → @before_tool_call / @after_tool_call 捕获沙盒工具调用         │
│     → Langfuse trace 包含 Sub-Crew 的 sandbox 操作                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 核心设计：5+2 事件类型

对齐 Agent Turn 周期，将 CrewAI 的 4 种 Hook 机制统一映射到 7 种事件：

```
BEFORE_TURN ──→ BEFORE_LLM ──→ [LLM] ──→ BEFORE_TOOL_CALL ──→ [工具] ──→ AFTER_TOOL_CALL ──→ AFTER_TURN
                                           （无工具调用时直接 → AFTER_TURN）
```

| 事件 | CrewAI 实现机制 | 说明 |
|------|---------------|------|
| BEFORE_TURN | `@before_llm_call` + 轮次计数 | 每轮首次 LLM 调用时触发 |
| BEFORE_LLM | `@before_llm_call` | 每次 LLM 调用 |
| BEFORE_TOOL_CALL | `@before_tool_call` | 工具执行前 |
| AFTER_TOOL_CALL | `@after_tool_call` | 工具执行后 |
| AFTER_TURN | `step_callback` | 一步推理完成 |
| TASK_COMPLETE | `task_callback` | 任务完成 |
| SESSION_END | 手动调用 | 清理 + flush |

---

## 两层 Hook 架构

```
shared_hooks/                    ← 全局（基线可观测，所有 Agent 共享）
  hooks.yaml                     # 结构化日志 + Langfuse 追踪
  structured_log.py
  langfuse_trace.py

workspace/demo_agent/hooks/      ← Workspace（业务定制，仅本 Agent）
  hooks.yaml                     # 任务审计
  task_audit.py
```

- **全局层**：日志 + Langfuse，是每个 Agent 都应该有的基线保障
- **Workspace 层**：特定 Agent 的业务需求（如审计、告警）
- **加载顺序**：全局先加载 → Workspace 追加

---

## 快速开始

```bash
cd /path/to/crewai_mas_demo/m5l30

# 1. 完成上方「环境搭建」五步（Langfuse + Sandbox + .env）

# 2. 运行单元测试（无需 LLM/Langfuse/Sandbox）
python3 -m pytest tests/ -v --ignore=tests/test_e2e_hooks.py

# 3. 运行端到端测试（需 LLM API + Langfuse）
python3 -m pytest tests/ -v

# 4. 运行演示（需 LLM API + Langfuse + Sandbox）
python3 demo.py
python3 demo.py "为一个短链接服务产出技术设计文档"

# 5. 查看结果
#    - 终端 stderr：结构化 JSON 日志
#    - Langfuse Dashboard（http://localhost:3000）→ 选择 course-demo 项目 → Traces
#    - workspace/demo_agent/output/：Sub-Crew 在沙盒中产出的设计文档
#    - workspace/demo_agent/audit.log：任务审计条目
```

---

## 运行效果

```
🔗 Session: sess_20260423_110456
📦 HookRegistry: 12 handlers loaded
   [global] structured_log.before_turn_handler → before_turn
   [global] structured_log.before_llm_handler → before_llm
   [global] langfuse_trace.before_llm_handler → before_llm
   [global] structured_log.before_tool_handler → before_tool_call
   [global] langfuse_trace.before_tool_handler → before_tool_call
   ...
   [workspace] task_audit.write_audit_entry → task_complete
   [global] langfuse_trace.flush_and_close → session_end

🚀 Task: 为一个用户注册功能产出技术设计文档

📋 Bootstrap: 613 chars from workspace/demo_agent/
🔧 Skills: ['sop_design']

... (Sub-Crew 在沙盒中执行 SOP，写入设计文档)

📊 Result: # 用户注册功能技术设计文档 ...
🔗 Langfuse: http://localhost:3000
📄 Design doc: workspace/demo_agent/output/user_registration_design.md
📝 Audit log: workspace/demo_agent/audit.log
```

### Langfuse Trace（7 个 Observations）

| Type | Name | 说明 |
|------|------|------|
| TOOL | tool-sandbox_file_operations | Sub-Crew: 沙盒文件操作（list/write/read） |
| TOOL | tool-skill_loader | 主 Agent: 调用 sop_design（task 型） |
| GENERATION | turn-1 | 主 Agent: LLM 最终回复 |
| SPAN | task-complete | 主 Agent: 任务完成 |

> 💡 全局 Hook（`@before_tool_call` / `@after_tool_call`）自动捕获 Sub-Crew 的沙盒工具调用，无需额外配置。

---

## 测试（20 个用例）

```bash
# 单元测试（无需 LLM/Langfuse）
python3 -m pytest tests/ -v --ignore=tests/test_e2e_hooks.py

# 全部测试（需 LLM API + Langfuse）
python3 -m pytest tests/ -v
```

| 文件 | 编号 | 测试内容 |
|------|------|---------|
| test_registry.py | T1-T5 | 注册/分发/多handler/无handler/summary/count |
| test_registry.py | T_extra1 | handler 异常不中断后续 handler |
| test_loader.py | T6-T8 | yaml 加载/两层合并/缺 yaml |
| test_loader.py | T_extra3 | 不存在的模块跳过不报错 |
| test_handlers.py | T9-T11 | 日志 JSON schema/全事件覆盖/审计写文件 |
| test_adapter.py | T12-T14 | BEFORE_TURN 计数/step→AFTER_TURN/轮次重置 |
| test_adapter.py | T_extra2 | cleanup 清理全局 hooks |
| test_adapter.py | T_extra4 | tool call 事件映射 |
| test_e2e_hooks.py | T15 | **全链路**：真实 Crew → 7种事件×2层 hook 全部触发 |
| test_e2e_hooks.py | T16 | **Langfuse**：真实 Crew → trace 含 TOOL + GENERATION observations |
