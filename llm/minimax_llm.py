"""
MiniMax LLM 实现（仅国内调用）

复用 AliyunLLM 的 OpenAI 兼容协议逻辑（重试、空内容重试、Function Calling、
多模态归一、回调、超时控制等），仅替换 endpoint 与 API Key 来源。

环境变量：
- MINIMAX_API_KEY：MiniMax API Key
"""
from __future__ import annotations

import os
from typing import Any

from llm.aliyun_llm import AliyunLLM


class MiniMaxLLM(AliyunLLM):
    """MiniMax LLM —— 走 OpenAI 兼容端点，仅支持国内地域。"""

    ENDPOINTS = {
        "cn": "https://api.minimaxi.com/v1/chat/completions",
    }

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float | None = None,
        timeout: int = 600,
        retry_count: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        初始化 MiniMax LLM。

        Args:
            model: 模型名称，如 "abab6.5s-chat"、"MiniMax-M1"、"MiniMax-Text-01"
            api_key: API Key，不提供则从环境变量 MINIMAX_API_KEY 读取
            temperature: 采样温度
            timeout: 请求超时（秒），默认 600
            retry_count: 请求失败时的重试次数，默认 2；可从环境变量 LLM_RETRY_COUNT 读取
        """
        api_key = api_key or os.getenv("MINIMAX_API_KEY")
        if not api_key:
            raise ValueError(
                "API Key 未提供。请通过 api_key 传入或设置环境变量 MINIMAX_API_KEY"
            )
        super().__init__(
            model=model,
            api_key=api_key,
            region="cn",
            temperature=temperature,
            timeout=timeout,
            retry_count=retry_count,
            **kwargs,
        )


if __name__ == "__main__":
    llm = MiniMaxLLM(model="abab6.5s-chat", temperature=0.7)
    print(llm.call("你好，请用一句话介绍你自己"))
