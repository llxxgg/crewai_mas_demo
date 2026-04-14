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
  - Manager 负责问问题、整理框架，人类负责拍板决定
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

# 每轮最多修订次数，可通过环境变量覆盖
MAX_SOP_ROUNDS = int(os.getenv("MAX_SOP_ROUNDS", "5"))

# ── 路径设置 ──────────────────────────────────────────────────────────────────
_M4L27_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _M4L27_DIR.parent
for _p in [str(_M4L27_DIR), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
# 确保 _M4L27_DIR 始终排在 _PROJECT_ROOT 前面（优先解析 m4l27/tools/）
if sys.path.index(str(_M4L27_DIR)) > sys.path.index(str(_PROJECT_ROOT)):
    sys.path.remove(str(_M4L27_DIR))
    sys.path.insert(0, str(_M4L27_DIR))

from crewai.hooks import clear_before_llm_call_hooks  # noqa: E402
from tools.mailbox_ops import send_mail               # noqa: E402
from m4l27_config import MAILBOXES_DIR, SOP_DIR       # noqa: E402
from m4l27_run import wait_for_human                  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _build_sop_inputs(
    task_description: str,
    sop_name: str,
    feedback_history: list[str],
    round_num: int,
) -> dict:
    """
    构造 SOPCreatorCrew.kickoff() 的 inputs 字典。

    - 第1轮：只传任务描述，revision_context 为空
    - 后续轮：revision_context 包含历轮用户反馈，引导 LLM 针对性修订

    Args:
        task_description: 任务背景描述
        sop_name:         SOP 文件名（不含 draft_ 前缀和 .md 后缀）
        feedback_history: 历轮反馈列表（首轮为空）
        round_num:        当前轮次（从1开始）

    Returns:
        可直接传入 crew.kickoff(inputs=...) 的字典
    """
    base_request = (
        f"任务背景：{task_description}\n"
        f"SOP名称：{sop_name}\n"
        f"请按 sop-creator 框架设计一份完整 SOP，写入 draft_{sop_name}.md"
    )

    if round_num == 1 or not feedback_history:
        return {"user_request": base_request, "revision_context": ""}

    # 对用户反馈转义花括号，防止 CrewAI 的 str.format_map() 出错
    safe_feedbacks = [fb.replace("{", "{{").replace("}", "}}") for fb in feedback_history]
    feedback_text = "\n".join(
        f"  第{i+1}轮反馈：{fb}" for i, fb in enumerate(safe_feedbacks)
    )
    revision_context = (
        f"这是第 {round_num} 轮 SOP 草稿修订。\n"
        f"用户对上一版本不满意，反馈如下：\n{feedback_text}\n\n"
        f"请基于以上反馈修订 SOP 草稿，重点修改用户指出的问题，未被质疑的部分保持不变。"
    )
    return {"user_request": base_request, "revision_context": revision_context}


def _finalize_sop(sop_name: str) -> Path:
    """
    将草稿文件 draft_{sop_name}.md 重命名为 {sop_name}.md（去掉 draft_ 前缀）。

    Agent 通过沙盒写入 /mnt/shared/sop/draft_{sop_name}.md，
    对应本地文件系统的 SOP_DIR/draft_{sop_name}.md。

    Args:
        sop_name: SOP 文件名（不含 draft_ 前缀和 .md 后缀）

    Returns:
        最终 SOP 文件路径（无论是否成功重命名）
    """
    draft_file = SOP_DIR / f"draft_{sop_name}.md"
    final_file = SOP_DIR / f"{sop_name}.md"

    if not draft_file.exists():
        print(f"\n⚠️  草稿文件不存在：{draft_file}")
        print("  提示：Agent 可能未成功写入草稿，请检查沙盒日志")
        return final_file

    # 如果目标文件已存在，先备份旧版本
    if final_file.exists():
        backup = SOP_DIR / f"{sop_name}.md.bak"
        final_file.rename(backup)
        print(f"  已备份旧版 SOP：{backup.name}")

    draft_file.rename(final_file)
    print(f"  草稿已确认：{draft_file.name} → {final_file.name}")
    return final_file


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────

def run_sop_setup(
    task_description: str = "",
    sop_name: str = "product_design_sop",
) -> None:
    """
    时点A：人机协作设计 SOP 模板。

    与 run.py（时点B）完全解耦：
      - 可独立运行，不影响已有 SOP 模板
      - 适合在开始新类型任务之前，先制定对应的 SOP

    Args:
        task_description: 任务背景描述（空时从命令行读取）
        sop_name:         SOP 文件名前缀（默认 product_design_sop），
                          最终写入 shared/sop/{sop_name}.md
    """
    from m4l27_manager import SOPCreatorCrew, save_session as manager_save  # 延迟导入

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

    # 确保 SOP 目录存在
    SOP_DIR.mkdir(parents=True, exist_ok=True)

    feedback_history: list[str] = []

    for round_num in range(1, MAX_SOP_ROUNDS + 1):
        print(f"【SOP设计】第{round_num}/{MAX_SOP_ROUNDS}轮...（SOPCreatorCrew）\n")
        # ⚠️ clear 必须在 SOPCreatorCrew().__init__ 之前
        clear_before_llm_call_hooks()

        inputs = _build_sop_inputs(
            task_description=task_description,
            sop_name=sop_name,
            feedback_history=feedback_history,
            round_num=round_num,
        )

        sop_crew = SOPCreatorCrew(session_id=session_id, sop_name=sop_name)
        result = sop_crew.crew().kickoff(inputs=inputs)
        manager_save(sop_crew, session_id)
        result_text = getattr(result, "raw", str(result))
        print(f"\nSOP草稿输出（第{round_num}轮）：{result_text[:300]}...\n")

        # 通知人类确认草稿（单一接口原则：由 run 脚本写 human.json）
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
            allow_feedback=True,    # 开启反馈收集，支持多轮修订
        )

        if decision.confirmed:
            print(f"✅ 用户已确认 SOP 草稿（共 {round_num} 轮）\n")
            final_file = _finalize_sop(sop_name)
            print(f"\n{'='*60}")
            print(f"  ✅ SOP 制定完成！")
            print(f"  SOP 文件：{final_file}")
            print(f"  运行任务时（m4l27_run.py）Manager 将自动选择此 SOP")
            print(f"{'='*60}\n")
            return

        # 用户拒绝：收集反馈准备下一轮
        fb = decision.feedback or "用户对 SOP 不满意，请重新审视设计"
        feedback_history.append(fb)
        print(f"  已记录反馈，准备第 {round_num + 1} 轮修订...\n")

        if round_num == MAX_SOP_ROUNDS:
            print(f"⚠️  已达最大轮次（{MAX_SOP_ROUNDS}），用户仍未确认，退出")
            print(f"  草稿保留在：shared/sop/draft_{sop_name}.md")
            print("  提示：可通过 MAX_SOP_ROUNDS 环境变量增加最大轮次")
            return


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="M4L27 SOP 制定工具（时点A）")
    parser.add_argument(
        "--name",
        default="product_design_sop",
        help="SOP 文件名前缀（默认：product_design_sop）",
    )
    parser.add_argument(
        "--task",
        default="",
        help="任务背景描述（不传则命令行交互输入）",
    )
    args = parser.parse_args()

    run_sop_setup(task_description=args.task, sop_name=args.name)
