"""gateway.yaml 的加载与校验；.env 密钥解析。

设计要点：
- pydantic 严格校验（extra="forbid"），配置写错立刻报错且信息清晰；
- 交叉引用检查（models->provider、aliases->model、fallbacks->model）在
  parse 阶段一次性列出全部问题，而不是遇到第一个就退出；
- 密钥两类来源：providers.<name>.api_key（字面量，如本地 vLLM 的 EMPTY）
  或 api_key_env 指向的环境变量（.env 由 python-dotenv 载入）。
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "gateway.yaml"
ENV_FILE = PROJECT_ROOT / ".env"


class ConfigError(Exception):
    """配置加载/校验失败（启动时直接抛出，信息面向人读）。"""


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    key_env: str = "GW_API_KEY"


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = 4100
    upstream_timeout_seconds: float = 300.0
    auth: AuthConfig = Field(default_factory=AuthConfig)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    api_key: str | None = None  # 字面量密钥（本地 vLLM 用 "EMPTY"）
    api_key_env: str | None = None  # 从环境变量读取的密钥名
    metrics_url: str | None = None  # 可空 = 不采集该 provider 的引擎指标
    type: Literal["local", "cloud"] | None = None  # 缺省按 base_url 推断（见 provider_kind）


class ModelRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    upstream: str


class SamplingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: float = 5.0
    gpu_source: Literal["auto", "nvml", "wsl"] = "auto"  # GPU 采样源
    wsl_distro: str = "Ubuntu-24.04"  # gpu_source=wsl 时使用的发行版


class GatewayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: dict[str, ProviderConfig]
    models: dict[str, ModelRef] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    fallbacks: dict[str, list[str]] = Field(default_factory=dict)
    injection: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)


def resolve_api_key(provider: ProviderConfig) -> str | None:
    """字面量 api_key 优先；否则读 api_key_env 指向的环境变量。"""
    if provider.api_key:
        return provider.api_key
    if provider.api_key_env:
        return os.environ.get(provider.api_key_env) or None
    return None


def provider_kind(provider: ProviderConfig) -> Literal["local", "cloud"]:
    """本地/云端判定：显式 type 优先；否则按 base_url 主机名推断。

    主机名为 localhost / *.local / host.docker.internal，或解析为回环/内网
    IP（127.x、::1、10.x、192.168.x、172.16-31.x 等）时视为本地，其余云端。
    """
    if provider.type is not None:
        return provider.type
    host = (urlparse(provider.base_url).hostname or "").lower()
    if host in ("localhost", "host.docker.internal") or host.endswith(".local"):
        return "local"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "cloud"
    return "local" if ip.is_loopback or ip.is_private else "cloud"


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["配置格式错误："]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "(根)"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def _collect_reference_errors(cfg: GatewayConfig) -> list[str]:
    """交叉引用检查；收集全部问题一次性返回。"""
    errors: list[str] = []
    if not cfg.providers:
        errors.append("providers: 至少需要定义一个 provider")
    known_providers = "、".join(sorted(cfg.providers)) or "（无）"
    known_models = "、".join(sorted(cfg.models)) or "（无）"
    for name, ref in cfg.models.items():
        if ref.provider not in cfg.providers:
            errors.append(
                f"models.{name}.provider 引用了不存在的 provider '{ref.provider}'"
                f"（已定义: {known_providers}）"
            )
    for alias, target in cfg.aliases.items():
        if alias in cfg.models:
            errors.append(f"aliases.{alias}: 别名与模型重名，会造成解析歧义")
        if target not in cfg.models:
            errors.append(
                f"aliases.{alias} 指向不存在的模型 '{target}'（已定义: {known_models}）"
            )
    for key, chain in cfg.fallbacks.items():
        base = key.split("@", 1)[0]
        if base not in cfg.models:
            errors.append(
                f"fallbacks.{key}: 主模型 '{base}' 不存在（已定义: {known_models}）"
            )
        if not chain:
            errors.append(f"fallbacks.{key}: 候选链为空，请删除该键或填入模型名")
        for target in chain:
            if target not in cfg.models:
                errors.append(
                    f"fallbacks.{key}: 候选模型 '{target}' 不存在（已定义: {known_models}）"
                )
    return errors


def parse_config(raw: dict[str, Any]) -> GatewayConfig:
    """校验原始 dict 并完成交叉引用检查；有错则一次性列全。"""
    try:
        cfg = GatewayConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc
    errors = _collect_reference_errors(cfg)
    if errors:
        raise ConfigError("配置校验失败：\n" + "\n".join(f"  - {e}" for e in errors))
    return cfg


def _load_dotenv_once() -> None:
    # override=False：已存在的环境变量优先（便于临时覆盖）
    load_dotenv(ENV_FILE, override=False)


def load_config(path: str | os.PathLike[str] | None = None) -> GatewayConfig:
    """加载并校验配置。

    path 优先级：显式参数 > 环境变量 GATEWAY_CONFIG > 项目根 gateway.yaml；
    相对路径按项目根解析。
    """
    _load_dotenv_once()
    if path is None:
        path = os.environ.get("GATEWAY_CONFIG") or DEFAULT_CONFIG_PATH
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    if not resolved.is_file():
        raise ConfigError(f"配置文件不存在: {resolved}")
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 YAML 解析失败: {resolved}\n  {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件内容必须是 YAML 映射（dict）: {resolved}")
    try:
        return parse_config(raw)
    except ConfigError as exc:
        raise ConfigError(f"{exc}\n（配置文件: {resolved}）") from exc


_config_cache: GatewayConfig | None = None


def get_config() -> GatewayConfig:
    """进程级单例；测试通过 reset_config_cache() 清理。"""
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config()
    return _config_cache


def reset_config_cache() -> None:
    global _config_cache
    _config_cache = None
