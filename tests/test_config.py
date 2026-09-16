"""模块 1：配置校验与 registry 解析测试。"""

from __future__ import annotations

import pytest

from app.config import ConfigError, load_config, parse_config, resolve_api_key
from app.registry import Registry, UnknownModelError

YAML_TEMPLATE = """\
server:
  port: 4200
providers:
  local-vllm:
    base_url: http://localhost:8200/v1
    api_key: EMPTY
models:
  qwen3-1.7b: { provider: local-vllm, upstream: qwen3-1.7b }
aliases:
  default: qwen3-1.7b
"""


# ------------------------------------------------------------ parse_config

def test_valid_config_parses(config_dict):
    cfg = parse_config(config_dict)
    assert cfg.server.port == 4100
    assert set(cfg.providers) == {"local-vllm", "deepseek"}
    assert cfg.models["qwen3-1.7b"].provider == "local-vllm"
    assert cfg.aliases["default"] == "qwen3-1.7b"
    assert cfg.fallbacks["qwen3-1.7b"] == ["deepseek-chat"]
    assert cfg.injection["speclens/scan"]["max_tokens"] == 4096
    assert cfg.sampling.interval_seconds == 5


def test_defaults_applied(config_dict):
    config_dict.pop("server")
    config_dict.pop("sampling")
    cfg = parse_config(config_dict)
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.port == 4100
    assert cfg.server.upstream_timeout_seconds == 300
    assert cfg.server.auth.enabled is False
    assert cfg.sampling.interval_seconds == 5


def test_injection_nested_structure_kept(config_dict):
    config_dict["injection"]["default"]["extra"] = {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    cfg = parse_config(config_dict)
    assert (
        cfg.injection["default"]["extra"]["chat_template_kwargs"]["enable_thinking"]
        is False
    )


def test_model_unknown_provider_raises(config_dict):
    config_dict["models"]["qwen3-1.7b"]["provider"] = "nope"
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    message = str(excinfo.value)
    assert "nope" in message
    assert "provider" in message


def test_alias_unknown_target_raises(config_dict):
    config_dict["aliases"]["default"] = "ghost"
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "ghost" in str(excinfo.value)


def test_alias_conflicts_with_model_raises(config_dict):
    config_dict["aliases"]["qwen3-1.7b"] = "deepseek-chat"
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "重名" in str(excinfo.value)


def test_fallback_unknown_main_model_raises(config_dict):
    config_dict["fallbacks"] = {"ghost": ["deepseek-chat"]}
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "ghost" in str(excinfo.value)


def test_fallback_unknown_target_raises(config_dict):
    config_dict["fallbacks"]["qwen3-1.7b"] = ["ghost"]
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "ghost" in str(excinfo.value)


def test_fallback_tag_key_is_valid(config_dict):
    config_dict["fallbacks"] = {"qwen3-1.7b@scan": ["deepseek-chat"]}
    cfg = parse_config(config_dict)
    assert cfg.fallbacks["qwen3-1.7b@scan"] == ["deepseek-chat"]


def test_fallback_empty_chain_raises(config_dict):
    config_dict["fallbacks"] = {"qwen3-1.7b": []}
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "候选链为空" in str(excinfo.value)


def test_unknown_top_level_key_raises(config_dict):
    config_dict["routes"] = {}
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "routes" in str(excinfo.value)


def test_unknown_provider_field_raises(config_dict):
    config_dict["providers"]["local-vllm"]["metric_url"] = "typo"
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "metric_url" in str(excinfo.value)


def test_empty_providers_raises(config_dict):
    config_dict["providers"] = {}
    config_dict["models"] = {}
    config_dict["aliases"] = {}
    config_dict["fallbacks"] = {}
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    assert "至少" in str(excinfo.value)


def test_multiple_errors_reported_together(config_dict):
    config_dict["models"]["qwen3-1.7b"]["provider"] = "nope"
    config_dict["aliases"]["default"] = "ghost"
    with pytest.raises(ConfigError) as excinfo:
        parse_config(config_dict)
    message = str(excinfo.value)
    assert "nope" in message
    assert "ghost" in message


# ------------------------------------------------------------ load_config

def test_load_config_from_file(tmp_path):
    path = tmp_path / "gateway.yaml"
    path.write_text(YAML_TEMPLATE, encoding="utf-8")
    cfg = load_config(path)
    assert cfg.server.port == 4200
    assert cfg.models["qwen3-1.7b"].upstream == "qwen3-1.7b"


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path / "missing.yaml")
    assert "不存在" in str(excinfo.value)


def test_load_config_invalid_yaml_raises(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("providers: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    assert "YAML" in str(excinfo.value)


def test_load_config_uses_env_var(tmp_path, monkeypatch):
    path = tmp_path / "gateway-env.yaml"
    path.write_text(YAML_TEMPLATE, encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG", str(path))
    cfg = load_config()
    assert cfg.server.port == 4200


def test_load_config_error_includes_file_path(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "providers:\n"
        "  local-vllm:\n"
        "    base_url: http://x/v1\n"
        "models:\n"
        "  m1: { provider: ghost, upstream: m1 }\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)
    message = str(excinfo.value)
    assert "ghost" in message
    assert str(path) in message


# ------------------------------------------------------------ api key 解析

def test_resolve_api_key_literal(config_dict):
    cfg = parse_config(config_dict)
    assert resolve_api_key(cfg.providers["local-vllm"]) == "EMPTY"


def test_resolve_api_key_from_env(config_dict, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    cfg = parse_config(config_dict)
    assert resolve_api_key(cfg.providers["deepseek"]) == "sk-test-123"


def test_resolve_api_key_env_missing(config_dict, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = parse_config(config_dict)
    assert resolve_api_key(cfg.providers["deepseek"]) is None


# ------------------------------------------------------------ registry

@pytest.fixture()
def registry(config_dict):
    return Registry(parse_config(config_dict))


def test_resolve_alias(registry):
    resolved = registry.resolve("default")
    assert resolved.name == "qwen3-1.7b"
    assert resolved.provider == "local-vllm"
    assert resolved.upstream == "qwen3-1.7b"


def test_resolve_direct_model(registry):
    resolved = registry.resolve("deepseek-chat")
    assert resolved.provider == "deepseek"
    assert resolved.upstream == "deepseek-chat"


def test_resolve_unknown_model_lists_available(registry):
    with pytest.raises(UnknownModelError) as excinfo:
        registry.resolve("gpt-4")
    message = str(excinfo.value)
    assert "gpt-4" in message
    assert "qwen3-1.7b" in message
    assert "default" in message


def test_candidates_default_chain(registry):
    chain = registry.candidates("default")
    assert [c.name for c in chain] == ["qwen3-1.7b", "deepseek-chat"]


def test_candidates_without_fallbacks(registry):
    chain = registry.candidates("deepseek-chat")
    assert [c.name for c in chain] == ["deepseek-chat"]


def test_candidates_tag_override(config_dict):
    config_dict["models"]["qwen-plus"] = {
        "provider": "deepseek",
        "upstream": "qwen-plus",
    }
    config_dict["fallbacks"] = {
        "qwen3-1.7b": ["deepseek-chat"],
        "qwen3-1.7b@scan": ["qwen-plus"],
    }
    reg = Registry(parse_config(config_dict))
    plain = reg.candidates("qwen3-1.7b")
    tagged = reg.candidates("qwen3-1.7b", tag="scan")
    assert [c.name for c in plain] == ["qwen3-1.7b", "deepseek-chat"]
    assert [c.name for c in tagged] == ["qwen3-1.7b", "qwen-plus"]


def test_candidates_tag_falls_back_to_plain_key(registry):
    chain = registry.candidates("qwen3-1.7b", tag="no-such-tag")
    assert [c.name for c in chain] == ["qwen3-1.7b", "deepseek-chat"]


def test_candidates_dedupe(config_dict):
    config_dict["fallbacks"]["qwen3-1.7b"] = ["qwen3-1.7b", "deepseek-chat"]
    reg = Registry(parse_config(config_dict))
    chain = reg.candidates("qwen3-1.7b")
    assert [c.name for c in chain] == ["qwen3-1.7b", "deepseek-chat"]


def test_model_list_contains_models_and_aliases(registry):
    entries = {item["id"]: item for item in registry.model_list()}
    assert set(entries) == {"qwen3-1.7b", "deepseek-chat", "default"}
    assert entries["qwen3-1.7b"]["owned_by"] == "local-vllm"
    assert entries["default"]["owned_by"] == "alias"
    assert all(item["object"] == "model" for item in entries.values())