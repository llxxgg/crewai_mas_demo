"""
LLM 模块

提供自定义 LLM 实现，支持阿里云通义千问、MiniMax 等国内大模型接口。

主要组件：
- AliyunLLM：阿里云通义千问 LLM 实现
- MiniMaxLLM：MiniMax LLM 实现（OpenAI 兼容协议，国内端点）
"""
from . import aliyun_llm, minimax_llm
from .aliyun_llm import AliyunLLM
from .minimax_llm import MiniMaxLLM

__all__ = ['AliyunLLM', 'aliyun_llm', 'MiniMaxLLM', 'minimax_llm']

