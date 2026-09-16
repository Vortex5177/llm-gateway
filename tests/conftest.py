"""pytest 共享 fixture。"""

from __future__ import annotations

import pytest


@pytest.fixture()
def config_dict() -> dict:
    """最小可用的网关配置（供 parse_config / Registry 测试直接使用）。"""
    return {
        "server": {"host": "127.0.0.1", "port": 4100},
        "providers": {
            "local-vllm": {
                "base_url": "http://localhost:8200/v1",
                "api_key": "EMPTY",
                "metrics_url": "http://localhost:8200/metrics",
            },
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key_env": "DEEPSEEK_API_KEY",
            },
        },
        "models": {
            "qwen3-1.7b": {"provider": "local-vllm", "upstream": "qwen3-1.7b"},
            "deepseek-chat": {"provider": "deepseek", "upstream": "deepseek-chat"},
        },
        "aliases": {"default": "qwen3-1.7b"},
        "fallbacks": {"qwen3-1.7b": ["deepseek-chat"]},
        "injection": {
            "default": {"max_tokens": 2048},
            "speclens/scan": {"max_tokens": 4096, "repetition_penalty": 1.05},
        },
        "sampling": {"interval_seconds": 5},
    }