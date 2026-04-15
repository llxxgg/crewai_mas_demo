"""
第26课：任务链与信息传递 — Manager 入口

教学对比（v3 vs v2）：
  v2：需要 run.py 编排器顺序调用 ManagerAssignCrew → PMExecuteCrew → ManagerReviewCrew
  v3：Manager 和 PM 各自独立启动，Agent 基于 workspace-local Skills 自主决策

运行方式：
  # Terminal 1：Manager 启动（新项目 + 分配任务）
  python main.py

  # Terminal 2：PM 启动（检查邮箱 + 完成任务）
  python start_pm.py

  # 再次运行 Manager（检查邮箱 + 验收）
  python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_M4L26_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _M4L26_DIR.parent
for _p in [str(_M4L26_DIR), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shared.digital_worker import DigitalWorkerCrew  # noqa: E402

WORKSPACE_DIR = _M4L26_DIR / "workspace" / "manager"
DEMO_INPUT    = _M4L26_DIR / "demo_input" / "project_requirement.md"
SANDBOX_PORT  = 8025
SESSION_ID    = "demo_m4l26_manager"


def main() -> None:
    if not DEMO_INPUT.exists():
        print(f"[ERROR] 演示输入文件不存在：{DEMO_INPUT}")
        return

    requirement = DEMO_INPUT.read_text(encoding="utf-8")
    user_request = (
        f"你是团队的 Manager。请根据以下项目需求完成任务分配：\n\n"
        f"{requirement}\n\n"
        f"按照你的工作规范（agent.md）完成整轮任务。"
    )

    worker = DigitalWorkerCrew(
        workspace_dir=WORKSPACE_DIR,
        sandbox_port=SANDBOX_PORT,
        session_id=SESSION_ID,
        model="glm-5.1",
        has_shared=True,
    )

    print(f"\n{'='*60}")
    print("第26课：任务链与信息传递 — Manager 启动")
    print(f"{'='*60}")
    print(f"Session ID : {SESSION_ID}")
    print(f"Workspace  : {WORKSPACE_DIR}")
    print(f"沙盒端口   : {SANDBOX_PORT}")
    print(f"{'─'*60}\n")

    result = worker.kickoff(user_request)

    print(f"\n{'─'*60}")
    print("Manager 输出：")
    print(result)
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
