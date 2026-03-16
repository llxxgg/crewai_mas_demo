"""
第19课 演示代码：上下文的生命周期——Bootstrap、剪枝与压缩

演示内容：
  1. Bootstrap：从 workspace 文件加载 soul/user/agent/memory 注入 backstory
  2. @before_llm_call Hook：
       - 首次调用：从 _ctx.json 恢复历史 context，追加新 user 消息
       - 每次调用：剪枝超长 Tool Result + 超阈值时压缩
  3. @after_llm_call Hook：
       - 未压缩完整历史 → {session_id}_raw.jsonl（追加每次 LLM 回复）
       - 压缩 context 快照 → {session_id}_ctx.json（覆盖写）

运行方式：
  # 第一轮
  python m3l19_context_mgmt.py --session_id demo --message "帮我搜索 CrewAI 最新动态"
  # 第二轮（自动续接上下文）
  python m3l19_context_mgmt.py --session_id demo --message "把结果保存到文件"

依赖：
  pip install crewai duckduckgo-search requests beautifulsoup4
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
from typing import Any

from crewai import Agent, Crew, LLM, Task
from crewai.hooks import LLMCallHookContext, after_llm_call, before_llm_call
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import BaseTool
from crewai_tools import FileReadTool, FileWriterTool
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# 1. 路径与常量配置
# ─────────────────────────────────────────────────────────────────────────────

WORKSPACE_DIR = Path(__file__).parent / "workspace"
SESSIONS_DIR  = WORKSPACE_DIR / "sessions"

COMPRESS_THRESHOLD = 0.35   # 💡 上下文使用率超过 35% 触发压缩（比 80% 激进，主动保持干净）
FRESH_TAIL        = 10      # 压缩时保留最近 N 轮原文（约 20 条消息）
MODEL_CTX_LIMIT   = 32000   # fallback：qwen3-max context window


# ─────────────────────────────────────────────────────────────────────────────
# 2. Bootstrap：加载 workspace 文件，构建结构化 backstory
# ─────────────────────────────────────────────────────────────────────────────

def build_bootstrap_prompt(workspace_dir: Path) -> str:
    """
    💡 核心点：只加载"导航骨架"，不把所有文件塞进去
    soul（身份）+ user_profile（用户画像）+ agent_rules（行为规范）
    + memory_index（200 行硬上限，防膨胀）
    """
    parts: list[str] = []

    for fname, tag in [
        ("soul.md",  "soul"),
        ("user.md",  "user_profile"),
        ("agent.md", "agent_rules"),
    ]:
        path = workspace_dir / fname
        if path.exists():
            parts.append(f"<{tag}>\n{path.read_text(encoding='utf-8').strip()}\n</{tag}>")

    memory_path = workspace_dir / "memory" / "MEMORY.md"
    if memory_path.exists():
        lines = memory_path.read_text(encoding='utf-8').splitlines()[:200]  # 💡 200 行硬上限
        parts.append(f"<memory_index>\n{chr(10).join(lines)}\n</memory_index>")

    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Session 持久化（两份文件）
# ─────────────────────────────────────────────────────────────────────────────

def _ctx_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}_ctx.json"

def _raw_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}_raw.jsonl"


def load_session_ctx(session_id: str) -> list[dict]:
    """读取压缩 context 快照（用于 session 恢复）"""
    p = _ctx_path(session_id)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding='utf-8'))


def save_session_ctx(session_id: str, messages: list[dict]) -> None:
    """覆盖写入当前压缩 context（每次 LLM 调用后）"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _ctx_path(session_id).write_text(
        json.dumps(messages, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )


def append_session_raw(session_id: str, role: str, content: str) -> None:
    """追加一条记录到未压缩完整历史（append-only，保留所有中间过程）"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "role":    role,
        "content": content,
        "ts":      datetime.datetime.now().isoformat(),
    }
    with open(_raw_path(session_id), "a", encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# 4. 工具定义（有意返回大量文本，用于演示剪枝效果）
# ─────────────────────────────────────────────────────────────────────────────

class _SaveInput(BaseModel):
    content:  str = Field(description="要保存的内容")
    filename: str = Field(description="文件名（不含路径），例如 summary.md")

class SaveIntermediateResultTool(BaseTool):
    name:        str = "save_intermediate_result"
    description: str = (
        "将中间产物或分析结果保存到 workspace 文件。"
        "适合保存搜索摘要、分析报告等，避免重要内容留在上下文里占空间。"
    )
    args_schema: type[BaseModel] = _SaveInput

    def _run(self, content: str, filename: str) -> str:  # type: ignore[override]
        out = WORKSPACE_DIR / filename
        out.write_text(content, encoding='utf-8')
        return f"✅ 已保存到 workspace/{filename}（{len(content)} 字符）"


class _SearchInput(BaseModel):
    query: str = Field(description="搜索关键词（建议用英文效果更好）")

class WebSearchTool(BaseTool):
    name:        str = "web_search"
    description: str = (
        "搜索互联网获取最新信息，返回多条结果。"
        "结果可能很长，使用后建议用 save_intermediate_result 保存重要内容。"
    )
    args_schema: type[BaseModel] = _SearchInput

    def _run(self, query: str) -> str:  # type: ignore[override]
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
            if not results:
                return "未找到相关结果"
            parts = []
            for i, r in enumerate(results, 1):
                parts.append(
                    f"### 结果{i}: {r.get('title', '')}\n"
                    f"{r.get('body', '')}\n"
                    f"来源: {r.get('href', '')}"
                )
            return "\n\n".join(parts)
        except ImportError:
            # 未安装 duckduckgo-search 时返回模拟数据（同样触发剪枝演示）
            return (
                f"[模拟搜索] 关于 '{query}' 的结果：\n\n"
                + "这是模拟搜索数据。" * 300  # 💡 故意很长，演示剪枝
            )


class _FetchInput(BaseModel):
    url: str = Field(description="要抓取的网页 URL")

class FetchWebpageTool(BaseTool):
    name:        str = "fetch_webpage"
    description: str = (
        "抓取指定网页的文本内容。返回页面正文，内容通常很长，"
        "使用后建议保存关键摘要。"
    )
    args_schema: type[BaseModel] = _FetchInput

    def _run(self, url: str) -> str:  # type: ignore[override]
        try:
            import requests
            from bs4 import BeautifulSoup
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)[:8000]
        except Exception as e:
            return f"抓取失败：{e}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. 剪枝逻辑
# ─────────────────────────────────────────────────────────────────────────────

def _prune_tool_results(messages: list[dict]) -> None:
    """
    💡 核心点：in-place 修改，Tool Result 是最大的上下文膨胀体
    分级处理：< 500 不动 / 500-2000 保留 / > 2000 截断头尾
    """
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        content = str(msg.get("content", ""))
        if len(content) <= 2000:
            continue
        # 💡 直接修改 content 字段，不替换整个 dict（保留 tool_call_id 等字段引用）
        messages[i]["content"] = (
            content[:500]
            + f"\n\n...[内容过长，已截断 {len(content) - 700} 字符]...\n\n"
            + content[-200:]
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. 压缩逻辑（含 lossless flush）
# ─────────────────────────────────────────────────────────────────────────────

_SUMMARY_PROMPT = """\
将以下对话历史压缩为结构化摘要，保留四类关键信息：
1. Session Intent：用户这次想完成什么目标
2. 关键标识符：文件路径、变量名、ID 等精确信息
3. 操作记录：已执行的操作和结果
4. 待办事项：尚未完成的任务

禁止包含：中间过程、失败尝试、重复内容。

对话历史：
{history}
"""


def _find_safe_split(non_system: list[dict], fresh_count: int) -> int:
    """
    💡 确保 split 点不破坏 tool message pair（assistant tool_call + tool result 必须成对）
    策略：从目标 split 点向前扫描，找到最近的 user 消息边界
    """
    target = max(0, len(non_system) - fresh_count)
    # 从 target 往前找最近的 user 消息（最干净的分割边界）
    for i in range(target, 0, -1):
        if non_system[i].get("role") == "user":
            return i
    return 0  # 找不到安全边界则不压缩


def _flush_lossless(messages: list[dict], workspace_dir: Path) -> None:
    """
    💡 核心点：压缩前先写磁盘（lossless 策略）
    写入完整内容，不截断——压缩节省上下文空间，磁盘保留完整记录
    生产环境需配套日志轮转，防止单文件无限增长
    """
    today    = datetime.date.today().isoformat()
    log_path = workspace_dir / "memory" / f"{today}.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding='utf-8') as f:
        f.write(f"\n## {datetime.datetime.now().strftime('%H:%M')} 压缩前记录\n")
        for msg in messages:
            role    = msg.get("role", "")
            content = str(msg.get("content", ""))   # 💡 写入完整内容，保证 lossless
            f.write(f"**{role}**: {content}\n\n")


def _summarize(messages: list[dict]) -> str:
    """用轻量模型生成结构化摘要（💡 小模型做摘要，节省成本）"""
    summary_llm = LLM(model="qwen3-turbo")
    # 摘要输入适当截断：不需要完整内容，节省 tokens
    history = "\n".join(
        f"{m.get('role', '')}: {str(m.get('content', ''))[:200]}"
        for m in messages
    )
    return summary_llm.call([
        {"role": "user", "content": _SUMMARY_PROMPT.format(history=history)}
    ])


def _maybe_compress(messages: list[dict], context: LLMCallHookContext) -> None:
    """
    💡 核心点：in-place 修改 messages
    策略：system 保留 → 旧消息摘要（system 角色注入）→ 最近 N 轮原文
    """
    # 动态读取 LLM context window，fallback 到常量
    model_limit  = getattr(context.llm, "context_window_size", MODEL_CTX_LIMIT)
    approx_tokens = sum(len(str(m.get("content", ""))) // 2 for m in messages)
    # 💡 中文 1 字 ≈ 1 token，英文 4 字 ≈ 1 token，取保守值 //2
    if approx_tokens / model_limit < COMPRESS_THRESHOLD:
        return  # 未到阈值，不压缩

    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system  = [m for m in messages if m.get("role") != "system"]

    split = _find_safe_split(non_system, FRESH_TAIL * 2)
    old   = non_system[:split]
    fresh = non_system[split:]

    if not old:
        return  # 没有可压缩内容

    _flush_lossless(old, WORKSPACE_DIR)     # 💡 压缩前先持久化

    summary_text = _summarize(old)
    summary_msg = {
        "role":    "system",                # 💡 system 角色：语义上是"背景信息"
        "content": f"<context_summary>\n{summary_text}\n</context_summary>",
    }

    # in-place 替换：保留原 system + 摘要 + 新鲜内容
    messages.clear()
    messages.extend(system_msgs + [summary_msg] + fresh)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Crew 定义
# ─────────────────────────────────────────────────────────────────────────────

@CrewBase
class XiaoPawCrew:
    """
    XiaoPaw 个人助手 Crew（第19课简化版）
    演示：Bootstrap + @before_llm_call 剪枝压缩 + @after_llm_call Session 持久化
    """

    def __init__(self, session_id: str, user_message: str) -> None:
        self.session_id    = session_id
        self.user_message  = user_message
        self._session_loaded   = False  # 💡 flag：session 恢复只做一次（首次 LLM 调用前）
        self._current_user_msg: dict[str, Any] = {}

    @agent
    def assistant_agent(self) -> Agent:
        return Agent(
            role      = "XiaoPaw 个人助手",
            goal      = "帮助用户高效完成工作和生活中的各类任务，主动用工具获取信息并保存成果",
            backstory = build_bootstrap_prompt(WORKSPACE_DIR),   # 💡 Bootstrap 在这里
            llm       = LLM(model="qwen3-max"),
            tools     = [
                # 💡 核心点：FileReadTool + FileWriterTool 是 crewai-tools 自带工具
                # Agent 读取记忆文件后修改，再用 FileWriterTool 覆盖写回（overwrite=True）
                # workspace 目录作为根路径，Agent 在 agent.md 的规范约束下决定写哪个文件
                FileReadTool(),
                FileWriterTool(),
                SaveIntermediateResultTool(),
                WebSearchTool(),
                FetchWebpageTool(),
            ],
            verbose   = True,
        )

    @task
    def assistant_task(self) -> Task:
        return Task(
            description     = self.user_message,
            expected_output = "针对用户请求的完整回复",
            agent           = self.assistant_agent,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents  = self.agents,
            tasks   = self.tasks,
            verbose = True,
        )

    # ── Pre-Model Hook：首次恢复 session + 每次剪枝压缩 ──────────────────────

    @before_llm_call
    def before_llm_hook(self, context: LLMCallHookContext) -> bool | None:
        """
        💡 核心点：在每次 LLM 调用前拦截 messages，必须 in-place 修改
        首次：读 _ctx.json → 替换 context → 追加新 user 消息
        每次：剪枝超长 Tool Result → 超阈值时压缩
        """
        if not self._session_loaded:
            self._restore_session(context)
            self._session_loaded = True

        _prune_tool_results(context.messages)   # ① 剪枝
        _maybe_compress(context.messages, context)  # ② 压缩
        return None  # 返回 None 继续调用，返回 False 则阻止

    # ── Post-Model Hook：保存两份 session 文件 ──────────────────────────────

    @after_llm_call
    def after_llm_hook(self, context: LLMCallHookContext) -> str | None:
        """
        💡 核心点：after hook 时 context.messages 不含本轮 assistant 回复
        本轮回复在 context.response，必须手动拼入 snapshot 再保存
        不能 append 到 context.messages（框架 _append_message 之后会再追加一次，导致重复）
        """
        response = context.response or ""

        # ① 未压缩完整历史：追加每次 LLM 回复（含中间工具调用决策）
        append_session_raw(self.session_id, "assistant", response)

        # ② 压缩 context 快照：current messages + 本轮 assistant 回复
        snapshot = list(context.messages) + [{"role": "assistant", "content": response}]
        save_session_ctx(self.session_id, snapshot)

        return None  # 不修改回复内容

    # ── Session 恢复（首次调用时执行）────────────────────────────────────────

    def _restore_session(self, context: LLMCallHookContext) -> None:
        """
        💡 核心点：
        1. 取出 task-wrapped user 消息（CrewAI 渲染为 "\nCurrent Task: ..."）
        2. 写入 raw log（user 消息只记录一次）
        3. 用历史 ctx 替换 context.messages，追加新 user 消息
           → Agent 看到的是连续的上下文，感知不到 session 中断
        """
        # 取出当前 user 消息（CrewAI task 渲染后注入的，位于 messages 末尾）
        self._current_user_msg = next(
            (m for m in reversed(context.messages) if m.get("role") == "user"),
            {},
        )
        if self._current_user_msg:
            append_session_raw(
                self.session_id, "user",
                str(self._current_user_msg.get("content", "")),
            )

        # 读取历史 context 快照
        history = load_session_ctx(self.session_id)
        if not history:
            return  # 第一次对话，无历史，直接用 CrewAI 初始化的 messages

        # 💡 替换：历史 messages + 新 user 消息 → Agent 看到连续上下文
        context.messages.clear()
        context.messages.extend(history)
        if self._current_user_msg:
            context.messages.append(self._current_user_msg)


# ─────────────────────────────────────────────────────────────────────────────
# 8. 入口
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="XiaoPaw 个人助手（第19课演示：上下文生命周期管理）"
    )
    parser.add_argument("--session_id", required=True,
                        help="会话 ID（相同 ID 可续接上下文，不同 ID 全新开始）")
    parser.add_argument("--message",    required=True,
                        help="用户消息")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"Session : {args.session_id}")
    print(f"Message : {args.message}")
    ctx_file = _ctx_path(args.session_id)
    if ctx_file.exists():
        saved = json.loads(ctx_file.read_text())
        print(f"历史消息: {len(saved)} 条（将恢复上下文）")
    else:
        print("历史消息: 无（全新 session）")
    print(f"{'='*60}\n")

    result = XiaoPawCrew(
        session_id   = args.session_id,
        user_message = args.message,
    ).crew().kickoff(inputs={"user_message": args.message})

    print(f"\n{'='*60}")
    print(f"回复：\n{result.raw}")
    print(f"{'='*60}")
    print(f"\nSession 文件：")
    print(f"  ctx  → {_ctx_path(args.session_id)}")
    print(f"  raw  → {_raw_path(args.session_id)}")


if __name__ == "__main__":
    main()
