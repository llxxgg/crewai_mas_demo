"""
第27课·Human as 甲方
tools/mailbox_ops.py

在第26课三态状态机基础上新增：
  - human.json 邮箱支持（human 只能作为收件人）
  - 单一接口约束：to=human 时 from_ 必须是 manager，否则 raise ValueError

两套状态语义（有意为之，原因见下）：
  ┌─ agent 邮箱（manager / pm）─────────────────────────────────────────┐
  │  status 字段：unread → in_progress → done                           │
  │  - unread:      消息写入，等待 Agent 取走                            │
  │  - in_progress: 已取走正在处理（read_inbox 原子完成）                │
  │  - done:        编排器在 Crew 成功后调用 mark_done 确认               │
  │  为什么三态？Agent 取走消息后可能崩溃——先标 in_progress，           │
  │  崩溃后 watchdog 可通过 reset_stale 把超时消息恢复为 unread。        │
  │  这与 AWS SQS Visibility Timeout 思路完全相同。                     │
  └─────────────────────────────────────────────────────────────────────┘
  ┌─ human 邮箱（human）────────────────────────────────────────────────┐
  │  read 字段：False → True（+ 可选 rejected=True）                    │
  │  - 由 wait_for_human() 在用户输入后直接标记，不需要 in_progress。    │
  │  为什么不用三态？human 的确认是同步阻塞的（wait_for_human 会等待     │
  │  用户输入再返回），不存在「取走后崩溃」的场景，无需 in_progress 保护。│
  └─────────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

# ── 三态常量（agent 邮箱专用）────────────────────────────────────────────────
STATUS_UNREAD      = "unread"       # 新写入，等待被取
STATUS_IN_PROGRESS = "in_progress"  # 已取走，正在处理
STATUS_DONE        = "done"         # 处理完成

# ── 角色分类 ──────────────────────────────────────────────────────────────────
# agent 邮箱：使用三态 status 字段
_AGENT_ROLES = {"manager", "pm"}
# human 邮箱：使用 read/rejected 字段（同步确认，不需要三态）
_HUMAN_ROLE  = "human"

# 允许的收件角色（to 字段）
_VALID_TO_ROLES   = _AGENT_ROLES | {_HUMAN_ROLE}
# 允许的发件角色（human 不作为发件人）
_VALID_FROM_ROLES = _AGENT_ROLES


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _inbox_path(mailbox_dir: Path, role: str) -> Path:
    if role not in _VALID_TO_ROLES:
        raise ValueError(f"未知收件角色 '{role}'，允许值：{_VALID_TO_ROLES}")
    return mailbox_dir / f"{role}.json"


def _lock_path(inbox: Path) -> Path:
    return inbox.with_suffix(".lock")


def _read_inbox_file(inbox: Path) -> list[dict]:
    inbox.parent.mkdir(parents=True, exist_ok=True)
    if not inbox.exists():
        inbox.write_text("[]", encoding="utf-8")
        return []
    return json.loads(inbox.read_text(encoding="utf-8"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 核心操作 ──────────────────────────────────────────────────────────────────

def send_mail(
    mailbox_dir: Path,
    to: str,
    from_: str,
    type_: str,
    subject: str,
    content: str,
) -> str:
    """
    发送消息到目标角色的邮箱。

    单一接口约束：
      to=human 时，from_ 必须是 manager。
      PM / Dev 等执行层不得直接写 human.json。

    状态初始化：
      agent 邮箱（manager/pm）：写入 status=unread + processing_since=None
      human 邮箱：写入 read=False（同步确认语义）

    Args:
        mailbox_dir: mailboxes/ 目录路径
        to:          收件人角色（"manager" | "pm" | "human"）
        from_:       发件人角色
        type_:       消息类型（"task_assign" | "task_done" | "needs_confirm" |
                               "sop_confirm" | "checkpoint_request" | "broadcast"）
        subject:     标题
        content:     正文内容

    Returns:
        新消息的唯一 ID
    """
    if from_ not in _VALID_FROM_ROLES:
        raise ValueError(f"未知发件角色 '{from_}'，允许值：{_VALID_FROM_ROLES}")

    if to == _HUMAN_ROLE and from_ != "manager":
        raise ValueError(
            f"单一接口约束：to=human 时 from_ 必须是 'manager'，"
            f"当前 from_='{from_}'。"
            f"执行层（PM/Dev等）只能发给 manager，由 Manager 决定是否上报给人类。"
        )

    inbox  = _inbox_path(mailbox_dir, to)
    lock   = _lock_path(inbox)
    msg_id = str(uuid.uuid4())

    # ── 按收件角色类型构造消息体 ──────────────────────────────────────────────
    if to in _AGENT_ROLES:
        # agent 邮箱：三态状态机
        message: dict = {
            "id":               msg_id,
            "from":             from_,
            "to":               to,
            "type":             type_,
            "subject":          subject,
            "content":          content,
            "timestamp":        _now_iso(),
            "status":           STATUS_UNREAD,   # ← 三态起点
            "processing_since": None,
        }
    else:
        # human 邮箱：简化 read 字段
        message = {
            "id":        msg_id,
            "from":      from_,
            "to":        to,
            "type":      type_,
            "subject":   subject,
            "content":   content,
            "timestamp": _now_iso(),
            "read":      False,
        }

    with FileLock(str(lock)):
        messages = _read_inbox_file(inbox)
        messages.append(message)
        inbox.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

    return msg_id


def read_inbox(mailbox_dir: Path, role: str) -> list[dict]:
    """
    取走指定角色的未处理消息。

    agent 邮箱（manager/pm）：
      原子标记 unread → in_progress，记录 processing_since。
      不直接标 done——Agent 可能取走消息后崩溃，先标 in_progress，
      成功后由编排器调用 mark_done 确认。对应 AWS SQS Visibility Timeout。

    human 邮箱：
      取走 read=False 的消息并标记 read=True（同步确认，直接完成）。

    Args:
        mailbox_dir: mailboxes/ 目录路径
        role:        目标角色（"manager" | "pm" | "human"）

    Returns:
        待处理消息的快照列表（状态已更新）
    """
    inbox = _inbox_path(mailbox_dir, role)
    lock  = _lock_path(inbox)

    with FileLock(str(lock)):
        messages = _read_inbox_file(inbox)

        if role in _AGENT_ROLES:
            # 三态：取走 unread 消息，原子标记为 in_progress，返回更新后的副本
            now = _now_iso()
            updated: list[dict] = []
            for m in messages:
                if m.get("status") == STATUS_UNREAD:
                    m["status"]           = STATUS_IN_PROGRESS
                    m["processing_since"] = now
                    updated.append(dict(m))   # 快照包含更新后的状态
        else:
            # human：取走 read=False 消息，标 read=True
            updated = [dict(m) for m in messages if not m.get("read", False)]
            for m in messages:
                if not m.get("read", False):
                    m["read"] = True

        inbox.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

    return updated


def mark_done(
    mailbox_dir: Path,
    role: str,
    msg_ids: list[str],
) -> int:
    """
    将指定 agent 邮箱中的消息标记为 done（处理完成确认）。

    调用时机：编排器在 Crew.kickoff() 成功返回后调用，
    确认这批消息已被可靠处理——对应 SQS 的 DeleteMessage。

    仅适用于 agent 邮箱（manager / pm），human 邮箱不支持。

    Args:
        mailbox_dir: mailboxes/ 目录路径
        role:        角色名（"manager" | "pm"）
        msg_ids:     需要确认完成的消息 ID 列表

    Returns:
        实际标记为 done 的消息数量
    """
    if role not in _AGENT_ROLES:
        raise ValueError(f"mark_done 仅适用于 agent 邮箱，不支持角色：'{role}'")

    inbox  = _inbox_path(mailbox_dir, role)
    lock   = _lock_path(inbox)
    id_set = set(msg_ids)
    count  = 0

    with FileLock(str(lock)):
        messages = _read_inbox_file(inbox)
        for m in messages:
            if m.get("id") in id_set and m.get("status") == STATUS_IN_PROGRESS:
                m["status"]           = STATUS_DONE
                m["processing_since"] = None
                count += 1
        inbox.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

    return count


def mark_done_all_in_progress(
    mailbox_dir: Path,
    role: str,
) -> int:
    """
    将 agent 邮箱中所有 in_progress 消息标记为 done。

    便捷版 mark_done，供顺序演示场景使用：
    当编排器确认某角色的 Crew 已成功完成，直接全量确认，
    无需跟踪具体 msg_id。

    仅适用于 agent 邮箱（manager / pm）。

    Returns:
        实际标记为 done 的消息数量
    """
    if role not in _AGENT_ROLES:
        raise ValueError(f"mark_done_all_in_progress 仅适用于 agent 邮箱，不支持角色：'{role}'")

    inbox = _inbox_path(mailbox_dir, role)
    lock  = _lock_path(inbox)
    count = 0

    with FileLock(str(lock)):
        messages = _read_inbox_file(inbox)
        for m in messages:
            if m.get("status") == STATUS_IN_PROGRESS:
                m["status"]           = STATUS_DONE
                m["processing_since"] = None
                count += 1
        inbox.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

    return count


def reset_stale(
    mailbox_dir: Path,
    role: str,
    timeout_seconds: int = 900,
) -> int:
    """
    将超时未完成的 in_progress 消息恢复为 unread（崩溃恢复）。

    场景：后台 Watchdog 定期巡检，发现某条消息在 in_progress 状态停留
    超过 timeout_seconds 秒，说明处理该消息的 Agent 已崩溃，
    将消息重置为可重新处理的 unread。

    对应 AWS SQS Visibility Timeout 到期后消息重新可见的机制。

    仅适用于 agent 邮箱（manager / pm）。

    Args:
        mailbox_dir:     mailboxes/ 目录路径
        role:            角色名（"manager" | "pm"）
        timeout_seconds: 超时阈值（默认 900 秒 = 15 分钟）

    Returns:
        实际重置的消息数量
    """
    if role not in _AGENT_ROLES:
        raise ValueError(f"reset_stale 仅适用于 agent 邮箱，不支持角色：'{role}'")

    inbox = _inbox_path(mailbox_dir, role)
    lock  = _lock_path(inbox)
    count = 0
    now   = datetime.now(timezone.utc)

    with FileLock(str(lock)):
        messages = _read_inbox_file(inbox)
        for m in messages:
            if m.get("status") != STATUS_IN_PROGRESS:
                continue
            since_str = m.get("processing_since")
            if not since_str:
                # processing_since 未记录，保守处理：直接重置
                m["status"]           = STATUS_UNREAD
                m["processing_since"] = None
                count += 1
                continue
            since = datetime.fromisoformat(since_str)
            if (now - since).total_seconds() >= timeout_seconds:
                m["status"]           = STATUS_UNREAD
                m["processing_since"] = None
                count += 1
        inbox.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")

    return count
