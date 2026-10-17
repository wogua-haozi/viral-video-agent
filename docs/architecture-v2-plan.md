# Architecture v2 改进计划与实验结果

> 本篇保留 2026-07 架构方案和实验历史，旧阶段待办暂停，不再作为自动执行计划。当前唯一主线和任务见 [项目状态](project-status.md)；本轮执行、用量和证据契约见 [创作者试用改进](creator-pilot-20261017.md)。历史实验不证明当前质量或生产性能。

> 状态：Phase 1～3 已完成，v2 已在两组真实 B站任务和一组不支持平台任务上验证并设为默认；v1 仍可回退。Phase 4 的项目2 RAG 数据治理已完成第一轮。产品层已采用 PostgreSQL 持久化与 Arq + Redis 后台任务，本项目尚未部署或规模化验证。

## 目标

在保留前端、MCP、RAG 和 Agent 能力的前提下，把主流程从“Supervisor 每步 LLM 路由”改为“确定性主流程 + 异常重规划”，并用同一套评测比较质量、证据完整性和延迟。产品 API 通过 PostgreSQL 任务模型和 Arq Worker 承载长任务。

## 改造前基线（2026-07-11）

- BFCL 风格 35 条：工具名 30/35，参数 14/31，完全 14/35。
- tau-inspired 严格 18 条：13/18；主体任务 11/11，边界任务 2/7。
- 通过用例平均耗时 161.8 秒，平均 Supervisor 轮数 12.2。
- 项目2 RAG 固定集：27/27 可回答用例来源命中，另有 1 条覆盖缺口。
- 真实视频搜索当前只落地 B站；有关键词时优先使用公开 WBI 视频搜索，失败或空结果时回退排行榜/热门池及标题过滤。该公开入口不承诺稳定全站覆盖；抖音/快手未接入，趋势工具无真实供应商。MiMo ASR 是默认转写路径，讯飞仅为可选回退。

## 当前产品运行职责

- PostgreSQL：用户、任务、报告、Evidence、反馈、用量、分享链接和持久事件。
- Redis：Arq 队列、临时状态/事件、锁和转写缓存，不作为业务历史真相源。
- Arq Worker：执行 LangGraph v2 长任务、取消、超时、有限重试和 ASR 深度分析。
- 默认通用 LLM：`deepseek-v4-pro`，使用标准 DeepSeek API；产品结构化节点显式关闭 V4 默认 thinking。ModelRegistry 仍支持按 Agent 切换其他获得后端授权的 Provider，`provider=mimo` 使用余额扣费 Key 和公共 OpenAI 兼容接口。
- ChromaDB：RAG 知识库向量，不保存用户、任务或报告。
- MiMo ASR：独立 OpenAI 兼容客户端；标准模式不调用，深度模式自动处理本次样本中的公开视频音频，失败降级为元数据分析。
- Evidence 入口：MCP 工具错误、非结构化字符串和缺少文本或来源的转写结果不得转换为 Evidence。
- 凭证边界：Token Plan 虽包含 ASR 模型和独立 `/v1` 地址，但供应商页面禁止用于自动化脚本或应用后端；Worker 只接受明确允许应用后端使用的 ASR 凭证。
- Analyst/Writer：要求可解析文本输出，结构化 JSON 节点关闭 thinking；两者输出预算为 2048 token。Evidence 已存在但 claims 为空时禁止发布。

## Researcher 可选模型路由

项目三 Qwen3-4B v4.1 通过本地 OpenAI 兼容服务接入时，只覆盖 `researcher`：

1. `src.gateway.model_bootstrap.configure_optional_model_routes()` 在 FastAPI App 导入和 Arq Worker startup 中复用。
2. `USE_FINETUNED_MODEL=false` 是默认值；初始化会精确注销 Researcher 的可选覆盖，其他 Agent 注册不受影响。
3. `USE_FINETUNED_MODEL=true` 时注册 `provider=openai`、`model=qwen3-tool-calling` 和 `FINETUNED_MODEL_URL`。
4. LangGraph 可以在 Worker 导入时构建，因为 Researcher 节点执行时才动态调用 `get_llm("researcher")`；Worker startup 完成注册后，真实任务会读取当前 Registry。
5. Planner、Analyst、Writer 继续使用默认 DeepSeek V4 Pro；MiMo ASR 使用独立客户端和配置。

Docker Compose 必须同时向 `app` 和 `worker` 传入 `USE_FINETUNED_MODEL` 与 `FINETUNED_MODEL_URL`。开关变更通过新进程生效，不承诺线上热切换。

证据边界：离线冻结评测回答模型层候选价值，项目三只读 A/B 回答 Prompt/Schema/图兼容性，Arq Worker canary 回答后台运行路径是否实际路由到本地服务；这些证据均不等同生产部署、长期稳定性或默认模型切换。

## 分阶段实施

### Phase 1：能力和数据契约（已完成）

1. 动态能力注册：只向 Researcher 暴露当前可用工具和平台。
2. Pydantic 参数校验：统一平台、默认值、范围和必填字段。
3. 结构化工具结果：记录 success / empty / unavailable / error、来源、查询参数和证据。
4. Evidence Gate：无真实证据时不进入正常分析，返回 partial/failed。

### Phase 2：可切换的 v2 图（已完成）

1. `GRAPH_VERSION=v1/v2` 保留现有稳定链路。
2. v2 使用 Intent → Planner → Research Loop → Evidence Gate → Analyst → Writer。
3. Supervisor 只保留给异常重规划，不参与正常的每一步流转。
4. v2 默认 Analyst 最多 2 次、Writer 生成 1 次；是否继续由规则决定。

### Phase 3：评测和发布门禁（已完成第一轮）

1. 冻结新的工具调用、证据完整性、边界请求和不可用能力用例。
2. 对比 v1/v2 的成功率、证据覆盖、LLM 调用次数和延迟。
3. v2 只有在主体任务不退化、无数据编造为 0 且延迟明显下降时才设为默认。

### Phase 4：RAG 与后训练（项目2第一轮已完成）

1. 项目2知识库按覆盖缺口扩充高质量摘要；当前 40 篇、235 个标题感知 chunk，保留来源、日期、类别、平台、章节和来源等级元数据。
2. 项目1按 detail/list/general 拆检索路径并重跑 90 条评测。
3. 项目3 v4.1 已按当前 Researcher 动态工具契约完成训练、冻结评测、OpenAI 兼容服务、DeepSeek V4 Pro 同集基线和 3 条项目2只读 A/B。当前结论是把 v4.1 作为 Researcher 优先候选；项目2默认仍为 `deepseek-v4-pro`，Planner、Analyst、Writer 不切换，也不根据离线窄域结果自动更改产品默认模型。

## 明确不做

- 不为展示而接入 Celery。
- 不用 mock 趋势数据冒充真实能力。
- 不在新 holdout 冻结前继续围绕旧题调 Prompt 或追加模板训练数据。
- 不一次性删除 v1；所有架构变化先以 A/B 方式验证。
- 不把单次本地真实 API 冒烟解释为线上性能、真实用户完成率或大规模 ASR 成功率。

## 2026-07-12 实验结果

| 任务 | v1 | v2 | 结论 |
|------|----|----|------|
| B站科技爆款分析 | 164.8s / 16 次 LLM / 13 轮 Supervisor | 79.4s / 7 次 LLM / 0 轮 Supervisor | 耗时下降 51.8%，报告长度 929→1558 |
| B站美食分析 + 知识库 | 179.6s / 14 次 LLM / 12 轮 Supervisor | 119.4s / 6 次 LLM / 0 轮 Supervisor | 耗时下降 33.5%，报告长度 1593→1557，v2 保留 20 条证据 |
| 抖音实时搜索（未接入） | 会进入长链路风险 | 0 次 LLM，直接 `partial/unsupported_platform` | 能力边界前置 |

- 能力范围路由：冻结 dev 21/23，独立 holdout 13/13；未继续针对 dev 两条错题堆 Prompt 规则。
- RAG：40 篇文档、235 个 chunk，来源审计通过；固定检索集 28/28 来源 Recall@5 命中。
- 发布决定：`GRAPH_VERSION=v2` 设为默认，保留 `v1` 用于回退和后续扩大 A/B 样本。
- 限制：目前只有两组真实主体任务，报告质量尚未经过足够规模的盲评，不能宣称 v2 在所有任务上质量更高。
