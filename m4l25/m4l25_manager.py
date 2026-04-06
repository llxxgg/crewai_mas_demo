"""
课程：25｜团队角色体系——分工设计与行为规范
示例文件：m4l25_manager.py

演示：Manager（项目经理）角色的独立运行
  - 接收项目需求（demo_input/project_requirement.md）
  - 加载 workspace/manager/ 下的身份 + 团队名册
  - 调用 sop_manager（reference skill）了解拆解流程
  - 输出结构化任务清单（task_breakdown.md）

与 m3l20 的复用关系：
  - build_bootstrap_prompt()：完全复用，zero change
  - SkillLoaderTool：完全复用，传入 m4l25 的沙盒挂载描述
  - prune_tool_results / maybe_compress：完全复用

本课不实现角色间通信（第26课）。Manager 和 Dev 各自独立运行，
任务清单由人工传递。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from crewai import Agent, Crew, Task
from crewai.hooks import LLMCallHookContext, before_llm_call
from crewai.project import CrewBase, agent, crew, task

# ── 路径设置：复用 crewai_mas_demo 共享模块 ───────────────────────────────────
_M4L25_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _M4L25_DIR.parent
for _p in [str(_M4L25_DIR), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from llm import aliyun_llm                           # noqa: E402
from tools.skill_loader_tool import SkillLoaderTool  # noqa: E402

# ── 直接复用 m3l20 的纯函数（bootstrap / 剪枝 / 压缩），一行不改 ──────────────
from m3l20.m3l20_file_memory import (                # noqa: E402
    build_bootstrap_prompt,
    load_session_ctx,
    save_session_ctx,
    append_session_raw,
    prune_tool_results,
    maybe_compress,
    PRUNE_KEEP_TURNS,
    COMPRESS_THRESHOLD,
    FRESH_KEEP_TURNS,
    CHUNK_TOKENS,
    MODEL_CTX_LIMIT,
)


# ─────────────────────────────────────────────────────────────────────────────
# 路径常量
# ─────────────────────────────────────────────────────────────────────────────

WORKSPACE_DIR = _M4L25_DIR / "workspace" / "manager"
SESSIONS_DIR  = WORKSPACE_DIR / "sessions"
DEMO_INPUT    = _M4L25_DIR / "demo_input" / "project_requirement.md"


# ─────────────────────────────────────────────────────────────────────────────
# 沙盒挂载描述（Manager workspace，可写）
# ─────────────────────────────────────────────────────────────────────────────

M4L25_MANAGER_SANDBOX_MOUNT_DESC = (
    "1. 所有的操作必须在沙盒中执行，不得操作本地文件系统。\n"
    "   当前已挂载的目录：\n"
    "   - ./workspace/manager:/workspace:rw（Manager workspace，可读写）\n"
    "   - ../skills:/mnt/skills:ro（共享 skills 目录，只读）\n\n"
    "2. 记忆文件读写规范：\n"
    "   - 读取：用沙盒绝对路径 /workspace/<filename>（如 /workspace/task_breakdown.md）\n"
    "   - 写入：同上，写前必须先 read 目标文件，确认无重复内容\n\n"
    "3. 参考型 Skill（type: reference）：内容直接注入上下文，无需沙盒\n\n"
    "4. 如遇依赖缺失，先在沙盒中安装再继续"
)


# ─────────────────────────────────────────────────────────────────────────────
# Manager Crew
# ─────────────────────────────────────────────────────────────────────────────

@CrewBase
class ManagerCrew:
    """
    Manager 角色（项目经理）

    核心教学点（对应第25课 P4）：
    - soul.md 中 NEVER 清单定义了 Manager 的信息权威边界
    - agent.md 中的团队成员名册让 Manager 知道「谁负责什么」
    - 通过 sop_manager（reference skill）注入任务拆解流程
    - 输出 task_breakdown.md，体现协调者持有全局视图
    """

    def __init__(self, session_id: str, user_message: str) -> None:
        self.session_id      = session_id
        self.user_message    = user_message
        self._session_loaded = False
        self._last_msgs: list[dict] = []
        self._history_len    = 0

    @agent
    def manager_agent(self) -> Agent:
        # 💡 核心点：build_bootstrap_prompt 注入 soul + user + agent（含团队名册）+ memory
        backstory = build_bootstrap_prompt(WORKSPACE_DIR)
        return Agent(
            role      = "项目经理（Manager）",
            goal      = "将业务需求拆解为可分配给团队执行的结构化任务清单，每个任务有明确负责人和验收标准",
            backstory = backstory,
            llm       = aliyun_llm.AliyunLLM(
                model       = "qwen-plus",
                temperature = 0.3,
            ),
            tools = [
                SkillLoaderTool(sandbox_mount_desc=M4L25_MANAGER_SANDBOX_MOUNT_DESC),
            ],
            verbose  = True,
            max_iter = 20,
        )

    @task
    def manager_task(self) -> Task:
        return Task(
            description     = "{user_request}",
            expected_output = (
                "一份结构化任务清单（task_breakdown.md），包含：\n"
                "- 分工模式说明（流水线/协调者-工作者/并行扇出）\n"
                "- 每个任务的负责角色、输入、输出、验收标准\n"
                "- 已保存至 /workspace/task_breakdown.md"
            ),
            agent = self.manager_agent(),
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents  = self.agents,
            tasks   = self.tasks,
            verbose = True,
        )

    # ── Pre-LLM Hook：session 恢复 + 剪枝 + 压缩（完全复用 m3l20）────────────

    @before_llm_call
    def before_llm_hook(self, context: LLMCallHookContext) -> bool | None:
        if not self._session_loaded:
            self._restore_session(context)
            self._session_loaded = True

        self._last_msgs = context.messages
        prune_tool_results(context.messages)
        maybe_compress(context.messages, context)
        return None

    def _restore_session(self, context: LLMCallHookContext) -> None:
        history = load_session_ctx(self.session_id, SESSIONS_DIR)
        self._history_len = len(history)
        if not history:
            return
        current_user_msg = next(
            (m for m in reversed(context.messages) if m.get("role") == "user"),
            {},
        )
        context.messages.clear()
        context.messages.extend(history)
        if current_user_msg:
            context.messages.append(current_user_msg)


# ─────────────────────────────────────────────────────────────────────────────
# 演示入口
# ─────────────────────────────────────────────────────────────────────────────

SESSION_ID = "demo_m4l25_manager"


def main() -> None:
    # 读取演示输入（项目需求文档）
    if not DEMO_INPUT.exists():
        print(f"[ERROR] 演示输入文件不存在：{DEMO_INPUT}")
        return

    requirement = DEMO_INPUT.read_text(encoding="utf-8")
    message = (
        f"请根据以下项目需求，使用 sop_manager skill 进行任务拆解，"
        f"输出 task_breakdown.md 并保存至 workspace。\n\n{requirement}"
    )

    print(f"\n{'='*60}")
    print("第25课：团队角色体系 — Manager 演示")
    print(f"{'='*60}")
    print(f"Session ID : {SESSION_ID}")
    print(f"Workspace  : {WORKSPACE_DIR}")
    saved = load_session_ctx(SESSION_ID, SESSIONS_DIR)
    if saved:
        print(f"历史消息   : {len(saved)} 条（将恢复上下文）")
    else:
        print("历史消息   : 无（全新 session）")
    print(f"\n{'─'*60}")
    print("输入需求：")
    print(requirement[:300] + "..." if len(requirement) > 300 else requirement)
    print(f"{'─'*60}\n")

    crew_instance = ManagerCrew(SESSION_ID, message)
    result = crew_instance.crew().kickoff(
        inputs={"user_request": message}
    )

    # 保存 session 上下文
    if crew_instance._last_msgs:
        new_msgs = list(crew_instance._last_msgs)[crew_instance._history_len:]
        append_session_raw(SESSION_ID, new_msgs, SESSIONS_DIR)
        save_session_ctx(SESSION_ID, list(crew_instance._last_msgs), SESSIONS_DIR)

    print(f"\n{'─'*60}")
    print("Manager 输出：")
    print(result.raw)
    print(f"\n{'='*60}")
    print("Session 文件：")
    print(f"  ctx  → {SESSIONS_DIR / f'{SESSION_ID}_ctx.json'}")
    print(f"  raw  → {SESSIONS_DIR / f'{SESSION_ID}_raw.jsonl'}")
    print(f"  输出 → {WORKSPACE_DIR / 'task_breakdown.md'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
