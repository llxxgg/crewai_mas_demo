"""
第27课演示：Human as 甲方 — 使用通用 DigitalWorkerCrew 框架。

5步任务链 + 3个人工确认节点（步骤1支持多轮需求澄清）：
  步骤1（Manager）：需求澄清 → requirements.md → 人工确认（支持多轮）
  步骤2（Manager）：从 SOP 库选 SOP → active_sop.md → 人工确认
  步骤3（Manager）：按 SOP 向 PM 发送 task_assign
  步骤4（PM）：撰写产品文档 → 通知 Manager
  步骤5（Manager）：验收产品文档 → 保存结论

核心教学点：
  - 单一接口原则：human.json 只由编排器（以 manager 身份）写入
  - 同一个 DigitalWorkerCrew 类，5步流程复用
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from filelock import FileLock

MAX_CLARIFICATION_ROUNDS = int(os.getenv("MAX_CLARIFICATION_ROUNDS", "3"))

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
from tools.mailbox_ops import send_mail, mark_done_all_in_progress  # noqa: E402
from m4l27_config import (  # noqa: E402
    MANAGER_DIR, PM_DIR, SHARED_DIR,
    MAILBOXES_DIR, DESIGN_DIR, SOP_DIR, ACTIVE_SOP_FILE,
)

MANAGER_PORT = 8027
PM_PORT = 8028


@dataclass
class HumanDecision:
    confirmed: bool
    feedback: Optional[str] = None

    def __bool__(self) -> bool:
        return self.confirmed


def wait_for_human(
    human_inbox: Path,
    expected_type: str,
    step_label: str,
    allow_feedback: bool = False,
) -> HumanDecision:
    lock_path = human_inbox.with_suffix(".lock")

    with FileLock(str(lock_path)):
        if not human_inbox.exists():
            human_inbox.write_text("[]", encoding="utf-8")
        messages = json.loads(human_inbox.read_text(encoding="utf-8"))

    target = next(
        (m for m in messages if m.get("type") == expected_type and not m.get("read", False)),
        None,
    )

    if target is None:
        print(f"\n[ERROR] human.json 中未找到未读的 '{expected_type}' 消息")
        raise RuntimeError(f"wait_for_human: 未找到类型为 '{expected_type}' 的未读消息。")

    print(f"\n{'='*60}")
    print(f"  [人工确认节点] {step_label}")
    print(f"  来自：{target.get('from', 'manager')}")
    print(f"  主题：{target.get('subject', '')}")
    print(f"  内容：{target.get('content', '')[:300]}")
    print(f"{'='*60}")

    decision = input("  你的决定 (y/n)：").strip().lower()
    confirmed = decision == "y"

    feedback: Optional[str] = None
    if not confirmed and allow_feedback:
        print("  请输入你的补充意见（直接回车跳过）：")
        raw_feedback = input("  补充意见：").strip()
        feedback = raw_feedback if raw_feedback else None

    with FileLock(str(lock_path)):
        messages = json.loads(human_inbox.read_text(encoding="utf-8"))
        for m in messages:
            if m.get("id") == target["id"]:
                m["read"] = True
                if not confirmed:
                    m["rejected"] = True
                if feedback:
                    m["human_feedback"] = feedback
                break
        human_inbox.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if confirmed:
        print(f"  ✅ 已确认：{step_label}\n")
    else:
        print(f"  ↩️  已拒绝：{step_label}\n")

    return HumanDecision(confirmed=confirmed, feedback=feedback)


def _build_revision_context(feedback_history: list[str], round_num: int) -> str:
    if round_num == 1 or not feedback_history:
        return ""
    safe_feedbacks = [fb.replace("{", "{{").replace("}", "}}") for fb in feedback_history]
    feedback_text = "\n".join(f"  第{i+1}轮反馈：{fb}" for i, fb in enumerate(safe_feedbacks))
    return (
        f"这是第 {round_num} 轮需求文档修订。\n"
        f"用户对上一版本不满意，反馈如下：\n{feedback_text}\n\n"
        f"请基于以上反馈修订需求文档，重点修改用户指出的问题。"
    )


def check_requirements_exists() -> bool:
    return (SHARED_DIR / "needs" / "requirements.md").exists()


def check_sop_exists() -> bool:
    return ACTIVE_SOP_FILE.exists()


def check_sop_library_nonempty() -> bool:
    if not SOP_DIR.exists():
        return False
    templates = [
        f for f in SOP_DIR.glob("*.md")
        if not f.name.startswith("draft_") and f.name != "active_sop.md"
    ]
    return len(templates) > 0


def check_pm_inbox_has_task_assign() -> bool:
    pm_inbox = MAILBOXES_DIR / "pm.json"
    if not pm_inbox.exists():
        return False
    messages = json.loads(pm_inbox.read_text(encoding="utf-8"))
    return any(m.get("type") == "task_assign" for m in messages)


def check_product_spec_exists() -> bool:
    return (DESIGN_DIR / "product_spec.md").exists()


def check_manager_inbox_has_task_done() -> bool:
    manager_inbox = MAILBOXES_DIR / "manager.json"
    if not manager_inbox.exists():
        return False
    messages = json.loads(manager_inbox.read_text(encoding="utf-8"))
    return any(m.get("type") == "task_done" for m in messages)


def run_demo(initial_request: str = "") -> None:
    session_id = str(uuid.uuid4())
    if not initial_request:
        initial_request = input("请告诉 Manager 你要做什么：").strip()

    print(f"\n{'='*60}")
    print(f"  第27课：Human as 甲方（通用数字员工框架）")
    print(f"  session: {session_id[:8]}...")
    print(f"{'='*60}\n")

    if not check_sop_library_nonempty():
        print("❌ SOP 库为空，请先运行 m4l27_sop_setup.py 制定 SOP")
        return

    if ACTIVE_SOP_FILE.exists():
        ACTIVE_SOP_FILE.unlink()
        print("  [清理] 已删除上次的 active_sop.md\n")

    # ── 步骤1：需求澄清（多轮） ─────────────────────────────────────────
    feedback_history: list[str] = []

    for round_num in range(1, MAX_CLARIFICATION_ROUNDS + 1):
        print(f"【步骤1】需求澄清 第{round_num}/{MAX_CLARIFICATION_ROUNDS}轮\n")
        clear_before_llm_call_hooks()

        revision = _build_revision_context(feedback_history, round_num)
        user_request = (
            f"请理解以下需求并整理成结构化需求文档，写入 /mnt/shared/needs/requirements.md。\n\n"
            f"用户需求：{initial_request}\n\n{revision}"
        )

        manager = DigitalWorkerCrew(
            workspace_dir=MANAGER_DIR,
            sandbox_port=MANAGER_PORT,
            session_id=f"l27_req_{session_id[:8]}",
            has_shared=True,
        )
        result1 = manager.kickoff(user_request)
        print(f"\n步骤1 输出（第{round_num}轮）：{str(result1)[:200]}...\n")

        if not check_requirements_exists():
            print("⚠️  需求文档未生成，终止")
            return

        send_mail(MAILBOXES_DIR, to="human", from_="manager",
                  type_="needs_confirm",
                  subject=f"需求文档（第{round_num}轮）待确认",
                  content=f"需求文档路径：shared/needs/requirements.md\n当前轮次：{round_num}/{MAX_CLARIFICATION_ROUNDS}")

        decision = wait_for_human(
            MAILBOXES_DIR / "human.json",
            expected_type="needs_confirm",
            step_label=f"需求文档确认（第{round_num}轮）",
            allow_feedback=True,
        )

        if decision.confirmed:
            print(f"✅ 需求文档已确认（共 {round_num} 轮）\n")
            break

        fb = decision.feedback or "用户对文档不满意，请重新审视"
        feedback_history.append(fb)

        if round_num == MAX_CLARIFICATION_ROUNDS:
            print(f"⚠️  已达最大轮次（{MAX_CLARIFICATION_ROUNDS}），终止")
            return

    # ── 步骤2：SOP 选择 ──────────────────────────────────────────────────
    print("【步骤2】SOP 选择\n")
    clear_before_llm_call_hooks()

    manager2 = DigitalWorkerCrew(
        workspace_dir=MANAGER_DIR,
        sandbox_port=MANAGER_PORT,
        session_id=f"l27_sop_{session_id[:8]}",
        has_shared=True,
    )
    result2 = manager2.kickoff(
        "请读取 /mnt/shared/needs/requirements.md，"
        "从 /mnt/shared/sop/ 目录选出最匹配的 SOP，"
        "将选中 SOP 的完整内容写入 /mnt/shared/sop/active_sop.md"
    )
    result2_text = str(result2)
    print(f"\n步骤2 输出：{result2_text[:300]}...\n")

    if not check_sop_exists():
        print("⚠️  active_sop.md 未生成，终止")
        return

    send_mail(MAILBOXES_DIR, to="human", from_="manager",
              type_="sop_confirm",
              subject="SOP 已选定，请确认",
              content=f"SOP 写入 shared/sop/active_sop.md\n结论：{result2_text[:200]}")

    if not wait_for_human(MAILBOXES_DIR / "human.json",
                          expected_type="sop_confirm",
                          step_label="SOP 选择确认"):
        print("  SOP 未确认，终止")
        return

    # ── 步骤3：分配任务 ──────────────────────────────────────────────────
    print("【步骤3】Manager 分配任务给 PM\n")
    clear_before_llm_call_hooks()

    manager3 = DigitalWorkerCrew(
        workspace_dir=MANAGER_DIR,
        sandbox_port=MANAGER_PORT,
        session_id=f"l27_assign_{session_id[:8]}",
        has_shared=True,
    )
    result3 = manager3.kickoff(
        "请读取需求文档和 active_sop.md，"
        "然后通过 mailbox-ops skill 向 PM 发送产品文档设计任务。"
    )
    print(f"\n步骤3 输出：{result3}\n")

    if not check_pm_inbox_has_task_assign():
        print("⚠️  PM 邮箱无 task_assign，终止")
        return
    print("✅ 步骤3完成\n")

    # ── 步骤4：PM 执行 ───────────────────────────────────────────────────
    print("【步骤4】PM 撰写产品文档\n")
    clear_before_llm_call_hooks()

    pm = DigitalWorkerCrew(
        workspace_dir=PM_DIR,
        sandbox_port=PM_PORT,
        session_id=f"l27_pm_{session_id[:8]}",
        has_shared=True,
    )
    result4 = pm.kickoff(
        "请先通过 mailbox-ops skill 读取你的邮箱，获取 Manager 分配的任务。"
        "然后读取需求文档，撰写产品规格文档写入 /mnt/shared/design/product_spec.md，"
        "最后通过 mailbox-ops skill 向 Manager 发送完成通知。"
    )
    print(f"\n步骤4 输出：{result4}\n")

    if not check_product_spec_exists():
        print("⚠️  产品文档未生成，终止")
        return
    if not check_manager_inbox_has_task_done():
        print("⚠️  Manager 邮箱无 task_done，终止")
        return
    mark_done_all_in_progress(MAILBOXES_DIR, "pm")
    print("✅ 步骤4完成\n")

    # ── 人工确认节点3 ────────────────────────────────────────────────────
    send_mail(MAILBOXES_DIR, to="human", from_="manager",
              type_="checkpoint_request",
              subject="产品文档已完成，请确认",
              content="产品文档路径：shared/design/product_spec.md")

    if not wait_for_human(MAILBOXES_DIR / "human.json",
                          expected_type="checkpoint_request",
                          step_label="设计文档 Checkpoint"):
        return

    # ── 步骤5：Manager 验收 ──────────────────────────────────────────────
    print("【步骤5】Manager 验收\n")
    clear_before_llm_call_hooks()

    manager5 = DigitalWorkerCrew(
        workspace_dir=MANAGER_DIR,
        sandbox_port=MANAGER_PORT,
        session_id=f"l27_review_{session_id[:8]}",
        has_shared=True,
    )
    result5 = manager5.kickoff(
        "请先通过 mailbox-ops skill 读取你的邮箱，获取 PM 发来的完成通知。"
        "然后读取 /mnt/shared/design/product_spec.md 验收产品文档，"
        "将验收结论保存到 /workspace/review_result.md。"
    )
    mark_done_all_in_progress(MAILBOXES_DIR, "manager")
    print(f"\n步骤5 输出：{result5}\n")

    print(f"\n{'='*60}")
    print("  ✅ 演示完成！")
    print(f"  产品文档：workspace/shared/design/product_spec.md")
    print(f"  验收结论：workspace/manager/review_result.md")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_demo()
