"""
第25课 集成测试 - test_m4l25.py

测试策略：
  - T1-T2：结构完整性测试（无 API，验证 workspace/skills 文件正确）
  - T3-T4：Bootstrap 加载测试（无 API，验证 build_bootstrap_prompt 正确注入）
  - T5-T6：边界规则测试（无 API，验证 soul.md 中 NEVER 清单存在且完整）

  T7（Manager 真实执行）、T8（Dev 真实执行）需真实 API + 沙盒，
  在注释中保留用例说明，供课程演示时手动验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── 路径设置 ──────────────────────────────────────────────────────────────────
_M4L25_DIR    = Path(__file__).resolve().parent
_PROJECT_ROOT = _M4L25_DIR.parent
for _p in [str(_M4L25_DIR), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from m3l20.m3l20_file_memory import build_bootstrap_prompt  # noqa: E402

WORKSPACE_MANAGER = _M4L25_DIR / "workspace" / "manager"
WORKSPACE_DEV     = _M4L25_DIR / "workspace" / "dev"
SKILLS_DIR        = _PROJECT_ROOT / "skills"


# ─────────────────────────────────────────────────────────────────────────────
# T1 | 结构完整性 - Manager workspace 四件套齐全
# ─────────────────────────────────────────────────────────────────────────────

class TestT1ManagerWorkspaceStructure:
    """T1：Manager workspace 四件套（soul/user/agent/memory）全部存在且非空"""

    @pytest.mark.parametrize("filename", ["soul.md", "user.md", "agent.md", "memory.md"])
    def test_workspace_files_exist(self, filename: str) -> None:
        path = WORKSPACE_MANAGER / filename
        assert path.exists(), f"Manager workspace 缺少 {filename}"

    def test_soul_md_not_empty(self) -> None:
        content = (WORKSPACE_MANAGER / "soul.md").read_text(encoding="utf-8")
        assert len(content.strip()) > 100, "soul.md 内容过少，可能未正确填写"

    def test_agent_md_contains_team_roster(self) -> None:
        """Manager 的 agent.md 必须包含团队成员名册（核心教学点 P4）"""
        content = (WORKSPACE_MANAGER / "agent.md").read_text(encoding="utf-8")
        assert "PM" in content, "团队名册缺少 PM 角色"
        assert "Dev" in content, "团队名册缺少 Dev 角色"
        assert "QA" in content, "团队名册缺少 QA 角色"


# ─────────────────────────────────────────────────────────────────────────────
# T2 | 结构完整性 - Dev workspace 四件套齐全
# ─────────────────────────────────────────────────────────────────────────────

class TestT2DevWorkspaceStructure:
    """T2：Dev workspace 四件套全部存在，agent.md 包含职责边界"""

    @pytest.mark.parametrize("filename", ["soul.md", "user.md", "agent.md", "memory.md"])
    def test_workspace_files_exist(self, filename: str) -> None:
        path = WORKSPACE_DEV / filename
        assert path.exists(), f"Dev workspace 缺少 {filename}"

    def test_agent_md_contains_boundary_table(self) -> None:
        """Dev 的 agent.md 必须包含职责边界（我负责 vs 我不负责）"""
        content = (WORKSPACE_DEV / "agent.md").read_text(encoding="utf-8")
        assert "我负责" in content or "负责" in content, "Dev agent.md 缺少职责边界"
        assert "Manager" in content, "Dev agent.md 缺少汇报对象（Manager）"

    def test_agent_md_team_position(self) -> None:
        """Dev 的 agent.md 包含上下游角色（PM上游 / QA下游）"""
        content = (WORKSPACE_DEV / "agent.md").read_text(encoding="utf-8")
        assert "PM" in content, "Dev agent.md 未说明上游角色 PM"
        assert "QA" in content, "Dev agent.md 未说明下游角色 QA"


# ─────────────────────────────────────────────────────────────────────────────
# T3 | Bootstrap 加载 - Manager build_bootstrap_prompt 正确包含四段
# ─────────────────────────────────────────────────────────────────────────────

class TestT3ManagerBootstrap:
    """T3：Manager bootstrap prompt 正确包含 soul/user_profile/agent_rules/memory_index"""

    def setup_method(self) -> None:
        self.prompt = build_bootstrap_prompt(WORKSPACE_MANAGER)

    def test_contains_soul_tag(self) -> None:
        assert "<soul>" in self.prompt, "bootstrap prompt 缺少 <soul> 段"

    def test_contains_user_profile_tag(self) -> None:
        assert "<user_profile>" in self.prompt, "bootstrap prompt 缺少 <user_profile> 段"

    def test_contains_agent_rules_tag(self) -> None:
        assert "<agent_rules>" in self.prompt, "bootstrap prompt 缺少 <agent_rules> 段"

    def test_contains_memory_index_tag(self) -> None:
        assert "<memory_index>" in self.prompt, "bootstrap prompt 缺少 <memory_index> 段"

    def test_team_roster_in_prompt(self) -> None:
        """团队名册（核心教学点）必须出现在 backstory 中"""
        assert "PM" in self.prompt and "Dev" in self.prompt and "QA" in self.prompt, \
            "bootstrap prompt 中缺少团队名册内容"


# ─────────────────────────────────────────────────────────────────────────────
# T4 | Bootstrap 加载 - Dev build_bootstrap_prompt 正确包含四段
# ─────────────────────────────────────────────────────────────────────────────

class TestT4DevBootstrap:
    """T4：Dev bootstrap prompt 正确注入身份 + 职责边界"""

    def setup_method(self) -> None:
        self.prompt = build_bootstrap_prompt(WORKSPACE_DEV)

    def test_contains_soul_tag(self) -> None:
        assert "<soul>" in self.prompt, "bootstrap prompt 缺少 <soul> 段"

    def test_soul_contains_dev_identity(self) -> None:
        assert "Dev" in self.prompt or "开发工程师" in self.prompt, \
            "bootstrap prompt 缺少 Dev 身份标识"

    def test_contains_boundary_content(self) -> None:
        assert "Manager" in self.prompt, "Dev 的 bootstrap 缺少汇报对象信息"


# ─────────────────────────────────────────────────────────────────────────────
# T5 | NEVER 规则 - Manager soul.md 包含关键边界限制
# ─────────────────────────────────────────────────────────────────────────────

class TestT5ManagerNeverRules:
    """T5：Manager soul.md 的 NEVER 清单包含信息权威边界（核心教学点 P3）"""

    def setup_method(self) -> None:
        self.soul = (WORKSPACE_MANAGER / "soul.md").read_text(encoding="utf-8")

    def test_never_section_exists(self) -> None:
        assert "NEVER" in self.soul or "禁止" in self.soul, \
            "Manager soul.md 缺少 NEVER 章节"

    def test_never_write_code(self) -> None:
        """Manager 绝不亲自写代码"""
        assert "代码" in self.soul, "Manager soul.md 未说明「不写代码」边界"

    def test_never_modify_requirement(self) -> None:
        """Manager 绝不修改需求"""
        assert "需求" in self.soul, "Manager soul.md 未说明「不改需求」边界"

    def test_deliverable_format_defined(self) -> None:
        """Manager 的交付物格式有明确定义"""
        assert "task_breakdown" in self.soul, \
            "Manager soul.md 未定义交付物 task_breakdown.md"


# ─────────────────────────────────────────────────────────────────────────────
# T6 | NEVER 规则 - Dev soul.md 包含关键边界限制
# ─────────────────────────────────────────────────────────────────────────────

class TestT6DevNeverRules:
    """T6：Dev soul.md 的 NEVER 清单包含信息权威边界"""

    def setup_method(self) -> None:
        self.soul = (WORKSPACE_DEV / "soul.md").read_text(encoding="utf-8")

    def test_never_section_exists(self) -> None:
        assert "NEVER" in self.soul or "禁止" in self.soul, \
            "Dev soul.md 缺少 NEVER 章节"

    def test_never_modify_requirement(self) -> None:
        """Dev 绝不修改需求"""
        assert "需求" in self.soul, "Dev soul.md 未说明「不改需求」边界"

    def test_never_skip_design(self) -> None:
        """Dev 绝不跳过技术设计"""
        assert "技术设计" in self.soul or "tech_design" in self.soul, \
            "Dev soul.md 未说明「不跳过技术设计」边界"

    def test_deliverable_format_defined(self) -> None:
        """Dev 的交付物格式有明确定义"""
        assert "tech_design" in self.soul, \
            "Dev soul.md 未定义交付物 tech_design.md"


# ─────────────────────────────────────────────────────────────────────────────
# T7 | SOP Skills 完整性 - sop_manager / sop_dev 文件存在且包含 SOP 步骤
# ─────────────────────────────────────────────────────────────────────────────

class TestT7SopSkillsIntegrity:
    """T7：两个 SOP Skill 文件结构完整，frontmatter 和 SOP 步骤齐全"""

    def test_sop_manager_exists(self) -> None:
        assert (SKILLS_DIR / "sop_manager" / "SKILL.md").exists(), \
            "sop_manager/SKILL.md 不存在"

    def test_sop_dev_exists(self) -> None:
        assert (SKILLS_DIR / "sop_dev" / "SKILL.md").exists(), \
            "sop_dev/SKILL.md 不存在"

    def test_sop_manager_has_steps(self) -> None:
        content = (SKILLS_DIR / "sop_manager" / "SKILL.md").read_text(encoding="utf-8")
        assert "步骤" in content or "Step" in content, \
            "sop_manager/SKILL.md 缺少步骤说明"
        assert "task_breakdown" in content, \
            "sop_manager/SKILL.md 未提及输出格式 task_breakdown.md"

    def test_sop_dev_has_steps(self) -> None:
        content = (SKILLS_DIR / "sop_dev" / "SKILL.md").read_text(encoding="utf-8")
        assert "步骤" in content or "Step" in content, \
            "sop_dev/SKILL.md 缺少步骤说明"
        assert "tech_design" in content, \
            "sop_dev/SKILL.md 未提及输出格式 tech_design.md"

    def test_load_skills_yaml_registered(self) -> None:
        """sop_manager 和 sop_dev 已注册到 load_skills.yaml"""
        yaml_content = (SKILLS_DIR / "load_skills.yaml").read_text(encoding="utf-8")
        assert "sop_manager" in yaml_content, "sop_manager 未注册到 load_skills.yaml"
        assert "sop_dev" in yaml_content, "sop_dev 未注册到 load_skills.yaml"
        # 验证是 reference 类型
        assert "reference" in yaml_content, "load_skills.yaml 中缺少 reference 类型条目"

    def test_sop_manager_is_reference_type(self) -> None:
        """load_skills.yaml 中 sop_manager 的 type 必须是 reference"""
        yaml_content = (SKILLS_DIR / "load_skills.yaml").read_text(encoding="utf-8")
        lines = yaml_content.split("\n")
        # 找到 sop_manager 的 type 行
        in_sop_manager = False
        for line in lines:
            if "name: sop_manager" in line:
                in_sop_manager = True
            if in_sop_manager and "type:" in line:
                assert "reference" in line, \
                    f"sop_manager 的 type 不是 reference：{line}"
                break


# ─────────────────────────────────────────────────────────────────────────────
# T8 | Demo 输入文件存在且包含验收标准
# ─────────────────────────────────────────────────────────────────────────────

class TestT8DemoInputFiles:
    """T8：演示输入文件存在，且包含验收标准（否则 Agent 会触发澄清而非执行）"""

    DEMO_DIR = _M4L25_DIR / "demo_input"

    def test_project_requirement_exists(self) -> None:
        assert (self.DEMO_DIR / "project_requirement.md").exists()

    def test_feature_requirement_exists(self) -> None:
        assert (self.DEMO_DIR / "feature_requirement.md").exists()

    def test_project_requirement_has_dod(self) -> None:
        """Manager 演示输入必须有验收标准，否则 Manager 会输出澄清问题而非任务清单"""
        content = (self.DEMO_DIR / "project_requirement.md").read_text(encoding="utf-8")
        assert "验收标准" in content or "DoD" in content, \
            "project_requirement.md 缺少验收标准，Manager 将触发澄清流程"

    def test_feature_requirement_has_dod(self) -> None:
        """Dev 演示输入必须有验收标准，否则 Dev 会拒绝执行"""
        content = (self.DEMO_DIR / "feature_requirement.md").read_text(encoding="utf-8")
        assert "验收标准" in content or "DoD" in content, \
            "feature_requirement.md 缺少验收标准，Dev 将退回 Manager"


# ─────────────────────────────────────────────────────────────────────────────
# 真实执行测试（需 API + 沙盒，课程演示时手动运行）
#
# T_E2E_1：Manager 真实执行
#   输入：demo_input/project_requirement.md
#   期望：生成 workspace/manager/task_breakdown.md，包含 ≥3 个任务
#         每个任务有：任务ID、负责角色、输入、输出、验收标准
#
# T_E2E_2：Dev 真实执行
#   输入：demo_input/feature_requirement.md
#   期望：生成 workspace/dev/tech_design.md，包含4个标准章节
#         （架构说明 / 接口定义 / 实现要点 / 单元测试用例）
#
# 运行方式：
#   cd crewai_mas_demo/m4l25
#   docker compose -f sandbox-docker-compose.yaml --profile manager up -d
#   python m4l25_manager.py
#   docker compose -f sandbox-docker-compose.yaml --profile dev up -d
#   python m4l25_dev.py
# ─────────────────────────────────────────────────────────────────────────────
