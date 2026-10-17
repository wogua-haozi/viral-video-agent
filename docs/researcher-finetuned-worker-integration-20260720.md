# Researcher 微调模型 Worker 可选接入验证（2026-07-20）

> 本文是 2026-07-20 的历史接入验收，结论与数据保持原样；当前运行、任务与实际验证以 [项目状态](project-status.md) 为准。可选路由仍默认关闭。

## Gate 结论

本维护分支完成项目三 Qwen3-4B v4.1 到项目二真实 Arq Worker 的可选 Researcher 路由接入。默认开关仍为关闭；显式启用时只覆盖 Researcher，Planner、Analyst、Writer 的默认 DeepSeek V4 Pro 路由不变。该接入已通过总控复核，并以 fast-forward 方式进入 `main`。

这不是生产部署、默认模型切换或长期稳定性证明。

## 起始状态与范围

| 项目 | 状态 |
|---|---|
| 项目二分支 | `feat/researcher-worker-finetuned-route` |
| 项目二起始 SHA | `b8c7abf7224ca65864c88dc6f75063bb75c982b3` (`origin/main`) |
| 冻结 P0 分支 | `feat/content-intelligence-p0@ca5e8b73402e1cf91a8fcb6cb719e3b3c71f6628`，未修改 |
| P0-C 失败归档 | `archive/p0c-architecture-failed-20260719@e224b5b5d20384b959a937f3f24841a8b398d80d`，未修改 |
| 项目三 | `main@22c6e8c632ed631737d859e5f49e3b4ba7c0a96e`，保持只读 |
| P0 | 未修改 P0-C，未进入 P0-D/P0-E |

## 实现

- 新增 `src.gateway.model_bootstrap.configure_optional_model_routes()`，由 App 导入和 Arq Worker startup 共用。
- `USE_FINETUNED_MODEL=true` 时只注册 `researcher`：`provider=openai`、`model=qwen3-tool-calling`、`base_url=FINETUNED_MODEL_URL`。
- `qwen3-tool-calling` 只是 OpenAI 兼容服务模型 ID；实际加载的是 Qwen3-4B 基座与 v4.1 Direct Adapter，不是另一个模型版本。
- 开关关闭时只注销 Researcher 覆盖，不清空 Registry，不影响其他 Agent 注册。
- Worker 在 startup 中初始化；图可以提前构建，因为节点执行时才动态调用 `get_llm("researcher")`。
- Compose 同时向 App 和 Worker 传入 `USE_FINETUNED_MODEL` 与 `FINETUNED_MODEL_URL`。
- 未修改 `llm_router.py`、`config.py`、Researcher Prompt、动态工具契约、ASR、MCP、RAG、Evidence、数据库 Schema 或项目三。

## 自动化与静态检查

| 检查 | 结果 |
|---|---|
| 定向测试 | `26 passed` |
| 完整 Python 测试 | `62 passed` |
| Python compile | 通过 |
| `docker compose config --quiet` | 通过 |
| 展开后的 Worker 默认开关 | `false` |
| 展开后的 Worker URL | `http://host.docker.internal:8002/v1` |
| `git diff --check` | 通过 |

聚焦测试覆盖默认 DeepSeek、只替换 Researcher、幂等、同进程 true→false 回退、保留其他 Agent 注册、App 导入、Worker startup 和路由解析。聚焦测试中的 LLM 构造器均被替换，没有真实 API 调用。

## 项目三服务 smoke

- 使用现有 `scripts/smoke_openai_service.py`。
- 服务模式：4-bit Base + v4.1 Direct Adapter；`RESEARCHER_PROMPT_VARIANT=contract`。
- 3/3 通过：完整项目二 Prompt、裸任务只包装一次、RAG `top_k` Schema 裁剪。
- OpenAI 兼容响应均可解析；未修改或覆盖项目三正式结果。

## 真实 Arq Worker canary

Compose 启动时发现已有持久卷数据库记录了 P0 分支 revision `20260715_0002`，而 main 没有该 revision。没有降级或改写该数据库；本轮创建独立数据库 `researcher_worker_canary_20260720_222851`，现有 P0 数据与卷保持不变。

### 负面设置尝试

第一次提交因 Windows PowerShell 默认请求编码把中文替换为 ASCII `?`，冻结输入字节不匹配。Job `3c1603b1-a28b-42eb-9298-e31e75e749b8` 在 Entry 阶段直接回答，没有进入 Researcher；本地模型请求增量为 0。该尝试消耗 1 次 DeepSeek 调用，估算 `$0.000035`。负面结果保留，不作为 Worker 接入证明。

### 有效 canary

| 项目 | 结果 |
|---|---|
| 冻结任务 | `mvp-01`，`standard`，UTF-8 字节与冻结文件一致 |
| Job | `8c579ac5-6868-46e4-824e-b34aa408d5f7` |
| Arq Job | `analysis:8c579ac5-6868-46e4-824e-b34aa408d5f7:0` |
| 最终状态 | `partial / EVIDENCE_INSUFFICIENT`，0 重试 |
| 事件 | queued → collecting → validating → persisting → partial |
| LLM 调用 | Planner 1、Researcher 2，总计 3 |
| 本地 8002 增量 | 2 次，HTTP 200 / 200 |
| Researcher 解析 | 2 次 JSON 路径，0 `invalid_params` |
| 工具结果 | `empty` |
| Evidence / claims | 0 / 0 |
| ASR | `0` 秒，未启用 |
| 估算收费 | `$0.000156`，来自默认 DeepSeek 路径；本地模型无 API 费用 |

本地服务新增的 2 次请求与 trace 中 Researcher 的 2 次 LLM 调用严格对应；Planner 的 1 次调用没有到达本地服务，因此仍走 DeepSeek。Analyst 和 Writer 因 Evidence Gate 在空结果处终止而未执行；自动化路由测试证明两者没有 Registry 覆盖。

`partial` 的原因是外部工具返回空，不是模型路由、Schema 或 Worker 失败。没有 UAPI、P0 Gate、ASR 或 holdout 调用，也没有修改数据库 Schema 定义。

## 回退与清理

- App/Worker 重建为 `USE_FINETUNED_MODEL=false`。
- 关闭状态下共享初始化返回 `False`，Researcher 注册为 `None`；本地服务请求数没有继续增加。
- 停止本任务启动的项目三模型 PID、App/Worker/MCP/Chroma/PostgreSQL/Redis 服务和 Docker Desktop。
- 删除本轮 `__pycache__`、`.pytest_cache` 和临时原始模型日志；未修改 `.venv`。
- 保留脱敏仓库外证据、独立 canary 数据库和 Docker 卷；未使用 `git clean -fdx`、`docker compose down -v` 或 `docker system prune`。

仓库外私有证据仅记录索引，不公开本机路径或正文：

- round：`20260720-222851-worker-integration`
- 摘要文件：`worker-canary-summary.json`
- SHA-256：`2F6F368158802E85C84391333C5224E259E5BD22B5DCFF5F926F6D97C466FF26`

## 调用与真实性边界

- 真实收费 DeepSeek 调用共 2 次：负面编码尝试 1 次、有效 canary 的 Planner 1 次。
- 有效 canary 的 Researcher 本地调用 2 次；项目三服务 smoke 本地调用 3 次。
- 没有重训、继续微调、合并 Adapter、量化、下载模型或修改项目三。
- 没有证明线上稳定性、并发吞吐、速度/成本更优或端到端产品质量更高。
- 默认模型仍是 DeepSeek V4 Pro；只有显式启用时替换 Researcher。
