"""共享 Hook：观测（YAML 加载）+ 可靠性策略（代码注册）。"""

from hook_framework.registry import EventType

from .cost_guard import CostGuard
from .loop_detector import LoopDetector
from .retry_tracker import RetryTracker


def install_reliability_hooks(
    registry,
    config: dict | None = None,
) -> dict:
    """在 HookRegistry 上注册所有可靠性策略。

    Returns:
        dict with "retry", "loop", "cost" keys -> strategy instances
    """
    config = config or {}

    retry = RetryTracker(max_retries=config.get("max_retries", 3))
    loop = LoopDetector(threshold=config.get("loop_threshold", 3))
    cost = CostGuard(
        budget_usd=config.get("budget_usd", 1.0),
        model=config.get("model", ""),
    )

    registry.register(
        EventType.AFTER_TOOL_CALL,
        retry.after_tool_handler,
        name="retry_tracker",
    )
    registry.register(
        EventType.AFTER_TOOL_CALL,
        loop.after_tool_handler,
        name="loop_detector.tool",
    )

    registry.register(
        EventType.AFTER_TURN,
        cost.after_turn_handler,
        name="cost_guard.accumulate",
    )
    registry.register(
        EventType.AFTER_TURN,
        loop.after_turn_handler,
        name="loop_detector.turn",
    )

    registry.register(
        EventType.BEFORE_TOOL_CALL,
        cost.before_tool_handler,
        name="cost_guard.gate",
    )

    return {"retry": retry, "loop": loop, "cost": cost}
