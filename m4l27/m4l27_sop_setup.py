"""
课程：27｜Human as 甲方
示例文件：m4l27_sop_setup.py

时点A：人机协作设计 SOP 模板（独立于任务执行，通常首次使用前运行一次）

演示：SOP 制定流程（支持多轮迭代）
  步骤1（Manager）：按 sop-creator skill 设计 SOP 草稿，写 draft_{sop_name}.md
  [人工确认节点] run.py 以 manager 身份写 human.json:sop_draft_confirm → 等待用户确认
                 用户可输入修改意见触发下一轮迭代，直到满意为止
  确认后：去掉 draft_ 前缀，正式写入 shared/sop/{sop_name}.md

使用方法：
  python m4l27/m4l27_sop_setup.py
  python m4l27/m4l27_sop_setup.py --name code_review_sop

核心教学点（对应第27课）：
  - SOP 不是程序员写死的静态文档，而是人机协作的产物
  - Checkpoint 在 SOP 设计阶段确定，执行时严格遵循
  - 时点A（SOP 制定）与时点B（任务执行）完全解耦
  - 使用通用 DigitalWorkerCrew 框架，Manager 身份由 workspace 决定
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

MAX_SOP_ROUNDS = int(os.getenv("MAX_SOP_ROUNDS", "5"))

_M4L27_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _M4L27_DIR.parent
for _p in [str(_M4L27_DIR), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
if sys.path.index(str(_M4L27_DIR)) > sys.path.index(str(_PROJECT_ROOT)):
    sys.path.remove(str(_M4L27_DIR))
    sys.path.insert(0, str(_M4L27_DIR))

from crewai.hooks import clear_before_llm_call_hooks  # noqa: E402
from shared.digital_worker import DigitalWorkerCrew  # noqa: E402
from tools.mailbox_ops import send_mail  # noqa: E402
from m4l27_config import MANAGER_DIR, MAILBOXES_DIR, SOP_DIR  # noqa: E402
from run_demo import wait_for_human  # noqa: E402

MANAGER_PORT = 8027


def _build_revision_context(feedback_history: list[str], round_num: int) -> str:
    if round_num == 1 or not feedback_history:
        return ""
    safe_feedbacks = [fb.replace("{", "{{").replace("}", "}}") for fb in feedback_history]
    feedback_text = "\n".join(f"  第{i+1}轮反馈：{fb}" for i, fb in enumerate(safe_feedbacks))
    return (
        f"这是第 {round_num} 轮 SOP 草稿修订。\n"
        f"用户对上一版本不满意，反馈如下：\n{feedback_text}\n\n"
        f"请基于以上反馈修订 SOP 草稿，重点修改用户指出的问题，未被质疑的部分保持不变。"
    )


def _finalize_sop(sop_name: str) -> Path:
    draft_file = SOP_DIR / f"draft_{sop_name}.md"
    final_file = SOP_DIR / f"{sop_name}.md"

    if not draft_file.exists():
        print(f"\n⚠️  草稿文件不存在：{draft_file}")
        return final_file

    if final_file.exists():
        backup = SOP_DIR / f"{sop_name}.md.bak"
        final_file.rename(backup)
        print(f"  已备份旧版 SOP：{backup.name}")

    draft_file.rename(final_file)
    print(f"  草稿已确认：{draft_file.name} → {final_file.name}")
    return final_file


def run_sop_setup(
    task_description: str = "",
    sop_name: str = "product_design_sop",
) -> None:
    session_id = str(uuid.uuid4())

    if not task_description:
        task_description = input("请描述需要制定 SOP 的任务背景：").strip()
    if not task_description:
        print("⚠️  任务背景不能为空，退出")
        return

    print(f"\n{'='*60}")
    print(f"  M4L27 SOP 制定流程  |  session: {session_id[:8]}...")
    print(f"  SOP 名称：{sop_name}")
    print(f"  写入路径：shared/sop/{sop_name}.md（确认后）")
    print(f"{'='*60}\n")

    SOP_DIR.mkdir(parents=True, exist_ok=True)

    feedback_history: list[str] = []

    for round_num in range(1, MAX_SOP_ROUNDS + 1):
        print(f"【SOP设计】第{round_num}/{MAX_SOP_ROUNDS}轮\n")
        clear_before_llm_call_hooks()

        revision = _build_revision_context(feedback_history, round_num)
        user_request = (
            f"任务背景：{task_description}\n"
            f"SOP名称：{sop_name}\n"
            f"请按 sop-creator 框架设计一份完整 SOP，写入 /mnt/shared/sop/draft_{sop_name}.md\n\n"
            f"{revision}"
        )

        manager = DigitalWorkerCrew(
            workspace_dir=MANAGER_DIR,
            sandbox_port=MANAGER_PORT,
            session_id=f"l27_sop_{session_id[:8]}",
            has_shared=True,
        )
        result = manager.kickoff(user_request)
        print(f"\nSOP草稿输出（第{round_num}轮）：{str(result)[:300]}...\n")

        send_mail(
            MAILBOXES_DIR,
            to="human",
            from_="manager",
            type_="sop_draft_confirm",
            subject=f"SOP草稿（{sop_name}，第{round_num}轮）待确认",
            content=(
                f"草稿路径：shared/sop/draft_{sop_name}.md\n"
                f"当前轮次：{round_num}/{MAX_SOP_ROUNDS}\n"
                f"确认后将正式写入：shared/sop/{sop_name}.md"
            ),
        )

        decision = wait_for_human(
            MAILBOXES_DIR / "human.json",
            expected_type="sop_draft_confirm",
            step_label=f"SOP草稿确认（第{round_num}轮）",
            allow_feedback=True,
        )

        if decision.confirmed:
            print(f"✅ 用户已确认 SOP 草稿（共 {round_num} 轮）\n")
            final_file = _finalize_sop(sop_name)
            print(f"\n{'='*60}")
            print(f"  ✅ SOP 制定完成！")
            print(f"  SOP 文件：{final_file}")
            print(f"{'='*60}\n")
            return

        fb = decision.feedback or "用户对 SOP 不满意，请重新审视设计"
        feedback_history.append(fb)

        if round_num == MAX_SOP_ROUNDS:
            print(f"⚠️  已达最大轮次（{MAX_SOP_ROUNDS}），退出")
            return


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="M4L27 SOP 制定工具（时点A）")
    parser.add_argument("--name", default="product_design_sop")
    parser.add_argument("--task", default="")
    args = parser.parse_args()

    run_sop_setup(task_description=args.task, sop_name=args.name)
