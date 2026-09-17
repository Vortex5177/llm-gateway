# llm-gateway

> 通用 LLM 网关 · OpenAI-Compatible · 单用户自托管

自托管、OpenAI 协议兼容的薄网关：把本地 vLLM（WSL2）与云端 API（DeepSeek / DashScope）统一到一个入口，提供模型别名解析、服务端回退链、硬顶参数注入与全链路可观测性。

## 架构

```
┌──────────────────────── 客户端 ────────────────────────┐
│   Chatbox 桌面版 / Python 脚本 / LangChain / 其他本地项目   │
└──────────────┬─────────────────────────────────────────┘
               │  OpenAI 协议: POST /v1/chat/completions (JSON / SSE)
               ▼
┌──────────────────── 网关 :4100 ─────────────────────────┐
│   别名解析 → 硬顶注入 → 回退链 → 上游转发                    │
│   请求落库(SQLite) · 指标采样(NVML + vLLM /metrics)         │
│   零构建静态看板 /  ·  聚合 API /api/stats                  │
└──────┬──────────────────────────────────┬───────────────┘
       ▼                                  ▼
 本地 vLLM :8200 (WSL2)            云端 API (DeepSeek / DashScope)
```

设计原则：**客户端只说"要什么"（模型 + 问题 + 可选 tag），网关决定"给谁做、怎么做、坏了换谁"**——协议适配、路由、护栏、记账全部收敛在网关层。

## 特性

- **OpenAI 兼容**：`POST /v1/chat/completions`（流式 + 非流式）、`GET /v1/models`；任何 OpenAI 兼容客户端改 base_url 即可接入
- **模型别名与切换**：`gateway.yaml` 的 `aliases` 把逻辑名映射到真实模型；切换本地/云只改一行，客户端零改动
- **服务端回退链**：`primary → fallbacks`，键支持 `模型@tag` 精确覆盖；客户端无感，响应头（`X-GW-Attempts` 等）与落库字段可观测
- **硬顶参数注入**：按 tag 覆盖（如 `max_tokens`、`repetition_penalty`），防弱模型失控/重复生成；客户端原值仅记审计
- **流式细节**：TTFT 度量、`stream_options.include_usage` 自动注入、客户端断连时 `asyncio.shield` 兜底清理（断连也保证落库）
- **可观测性**：NVML GPU 采样 + vLLM `/metrics` 引擎指标 → SQLite → 聚合 API → 零依赖 Chart.js 看板（请求/tokens/延迟/TTFT/GPU 曲线、tag 分组、模型与 Provider 面板）
- **健康检查**：`GET /health` 报告各 provider 可达性

## 快速开始

环境要求：Python ≥ 3.11；Windows 主机；WSL2（可选，本地模型需要）

```powershell
# 1. 环境
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置：按需编辑 gateway.yaml；云端密钥放 .env（模板见 .env.example）

# 3. 本地模型（可选）：WSL 内启动 vLLM（端口 8200）
wsl -d Ubuntu-24.04 -- /opt/scripts/start-vllm.sh

# 4. 启动网关
.\start.ps1

# 5. 验证
.\.venv\Scripts\python.exe smoke_test.py     # 端到端冒烟
# 浏览器打开 http://127.0.0.1:4100/ 查看监控看板
```

## 端点

| 端点 | 说明 |
|---|---|
| `POST /v1/chat/completions` | 聊天补全（流式/非流式），OpenAI 兼容 |
| `GET /v1/models` | 模型与别名清单 |
| `GET /health` | 存活 + 各 provider 可达性 |
| `GET /api/stats?days=N&tag=X` | 聚合统计（总量 / tag 分组 / 时间序列 / GPU / 引擎 / 最近请求） |
| `GET /api/models` | 模型目录（名称 / 本地或云 / 别名 / 回退链）+ provider 接入状态（密钥来源 / 连通性） |
| `GET /` | 静态监控看板 |

## 配置说明（gateway.yaml）

| 段 | 作用 |
|---|---|
| `server` | 监听地址、上游超时、鉴权开关（默认关闭，仅监听 127.0.0.1） |
| `providers` | 上游服务：base_url + 密钥（明文或 `*_env` 环境变量引用）+ metrics_url + 可选 `type`（local/cloud，缺省按 base_url 推断） |
| `models` | 客户端可见名 → provider + 上游真实名 |
| `aliases` | 逻辑别名（如 `default`），切换本地/云只改这一行 |
| `fallbacks` | 服务端回退链；键支持 `模型@tag` 精确覆盖 |
| `injection` | 硬顶注入表：tag 精确匹配 + `default` 兜底；`extra` 展开到请求体顶级 |
| `sampling` | 指标采样间隔与 GPU 来源（auto / nvml / wsl） |

## 数据与可观测性

每次请求落库 `data/gateway.db` 的 `request_logs` 表（该目录不入库）：请求/解析模型、provider、是否流式、prompt/completion tokens、延迟、TTFT、输出速率、状态、HTTP 状态码、attempts、回退标记、错误信息、注入快照、tag、时间戳。看板与 `/api/stats` 均读自此表。

## 测试与验收

```powershell
.\.venv\Scripts\python.exe -m pytest                       # 98 个单元测试（上游用 MockTransport stub）
.\.venv\Scripts\python.exe smoke_test.py                   # 33 项端到端检查（真调本地 vLLM）
.\.venv\Scripts\python.exe smoke_test.py --fallback-demo   # 9 项回退链检查（先以 gateway.fallback_demo.yaml 在 :4101 启动演示网关）
```

## 目录结构

```
app/            网关主体（config / registry / routing / proxy / streaming / sampler / stats + routes）
static/         零构建看板（index.html + dashboard.js + vendored Chart.js）
tests/          pytest 单元测试
gateway.yaml    主配置；gateway.fallback_demo.yaml 为回退链演示配置（配合 smoke_test --fallback-demo）
smoke_test.py   端到端冒烟脚本
start.ps1       一键启动
```

## 已知边界（v1）

- 仅实现 chat completions；无 embeddings / completions 等端点
- 单用户本地工具：鉴权默认关闭、仅监听 127.0.0.1（网页版浏览器客户端受浏览器安全限制无法访问 localhost，需桌面客户端）
- 配置驱动的规则路由（别名 / tag），无 ML 智能路由
- 无容器化、无压测结论
