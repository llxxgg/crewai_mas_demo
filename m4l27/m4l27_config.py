"""
第27课·Human as 甲方
m4l27_config.py — 共享路径常量

所有 m4l27 相关脚本（m4l27_run.py / m4l27_sop_setup.py / m4l27_manager.py）
均从此处 import 路径常量，避免各自独立计算导致不一致。
"""

from __future__ import annotations

from pathlib import Path

# ── 基础路径 ──────────────────────────────────────────────────────────────────
M4L27_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT = M4L27_DIR.parent

# ── 工作区目录 ────────────────────────────────────────────────────────────────
WORKSPACE_DIR  = M4L27_DIR / "workspace"
MANAGER_DIR    = WORKSPACE_DIR / "manager"
PM_DIR         = WORKSPACE_DIR / "pm"
SHARED_DIR     = WORKSPACE_DIR / "shared"

# ── 共享工作区子目录 ──────────────────────────────────────────────────────────
MAILBOXES_DIR  = SHARED_DIR / "mailboxes"
NEEDS_DIR      = SHARED_DIR / "needs"
DESIGN_DIR     = SHARED_DIR / "design"
SOP_DIR        = SHARED_DIR / "sop"

# ── 关键文件路径 ──────────────────────────────────────────────────────────────
REQUIREMENTS_FILE  = NEEDS_DIR  / "requirements.md"
PRODUCT_SPEC_FILE  = DESIGN_DIR / "product_spec.md"
ACTIVE_SOP_FILE    = SOP_DIR    / "active_sop.md"
REVIEW_RESULT_FILE = MANAGER_DIR / "review_result.md"
