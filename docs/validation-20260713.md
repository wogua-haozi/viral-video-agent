# 2026-07-13 MVP 验收记录

> 历史验收档案：结果和旧版截图仅对应标题日期的版本，不代表本轮本机验收或当前界面。当前状态见 [项目状态](project-status.md)。

## 自动检查

| 检查 | 结果 |
|---|---|
| Python 测试 | 56 passed |
| 冻结 B 站产品输入 | 20/20 通过 schema、单平台与入口路由校验 |
| 前端 ESLint | 通过，无 warning |
| Next.js production build | 通过 |
| Python compile/import | 通过 |
| Alembic PostgreSQL 离线 SQL | 通过 |
| `docker compose config --quiet` | 通过 |
| Compose 服务 | 8 个服务全部启动 |
| PostgreSQL 迁移 | `20260713_0001` 成功执行 |
| API 冒烟 | health、注册、Cookie、`/auth/me`、capabilities 通过 |
| Worker | Arq 启动并连接 Redis |
| Nginx | `/` 与 `/api/health` 均返回 200 |

测试覆盖注册登录、Cookie、未登录访问、越权、幂等、取消、重试边界、Evidence 引用、分享只读与过期、反馈模型、MiMo ASR 请求格式、Base64 大小限制和 URL 白名单。自动测试未调用真实 LLM 或 ASR。

## 浏览器视觉验收

使用真实浏览器检查：

- 1440×900：首页与 Dashboard 无横向溢出
- 1024×768：首页布局正常，无横向溢出
- 390×844：首页、注册、Dashboard、新建任务无横向溢出
- 手机端主标题 36px，公共导航折叠，工作台显示移动菜单
- 注册成功跳转 Dashboard
- 深色与浅色主题切换正常，Logo 在两种背景均为 36px 清晰显示
- 工作台不再显示公开站“登录/免费试用”动作
- 浏览器控制台无页面错误

截图：

- `output/playwright/home-desktop.png`
- `output/playwright/home-mobile.png`
- `output/playwright/dashboard-desktop.png`

## 真实 API 冒烟

### MiMo LLM 标准分析

| 项目 | 结果 |
|---|---|
| 时间 | 2026-07-13 19:22（Asia/Shanghai） |
| 输入 | `分析B站游戏攻略视频的选题方向和标题表达` |
| 模型 | `mimo-v2.5-pro` |
| 产品链路 | 注册 → `POST /jobs` → Arq Worker → PostgreSQL → `GET /reports/{id}` |
| 最终状态 | `completed`，无重试或降级 |
| 总耗时 | 96.16 秒 |
| LLM 调用 | 6 次 |
| Token | 输入 22900，输出 3238 |
| 估算成本 | 当前 CostTracker 记录为 `$0`；不等同供应商真实账单 |
| Evidence | 25 条：15 条真实 B 站视频、10 条 RAG 来源；均有抓取时间，来源 URL 均为 HTTPS |
| 报告引用 | 发布校验通过；正文包含 32 处 Evidence 引用 |
| 标准模式 ASR | `asr_seconds=0` |
| 分享与权限 | 分享可读且脱敏；其他用户读取 job 返回 404 |
| Key 泄露检查 | 报告字段未发现 `.env` 中的 Key/Secret |

这是单次真实端到端冒烟，样本量 n=1，不代表线上性能、完成率或 p50/p95。

本次任务同时暴露：MiMo Analyst 在 thinking 模式下两轮只产生 thinking block，导致结构化 claims 为空。报告正文引用本身通过校验，但 UI 缺少结构化结论。随后已完成最小修复：

- Analyst 产品主链路关闭 thinking，强制返回可解析文本 JSON。
- Analyst 与 Writer 输出预算由默认 1024 提高到 2048 token，并限制 claims 数量与长度。
- 有 Evidence 但 claims 为空时触发 `REPORT_VALIDATION_FAILED`，不再静默发布。
- 修复后通过聚焦测试；为避免重复消耗，本轮没有再提交第二个标准收费任务。

### MiMo ASR 深度分析

| 项目 | 结果 |
|---|---|
| 时间 | 2026-07-13 20:06～20:08（Asia/Shanghai） |
| 输入 | `深度分析B站美食教程视频的口播节奏和信息结构` |
| Agent LLM | `deepseek-chat`，8 次调用 |
| ASR 模型 | `mimo-v2.5-asr` |
| `ASR_MAX_VIDEOS` | 1 |
| 视频来源 | `https://www.bilibili.com/video/BV1PUZsY8E8m` |
| 音频预处理 | 329.676 秒，64kbps MP3，约 2.64MB |
| 最终状态 | `completed`，无重试；约 104.24 秒 |
| Token / 成本 | 输入 27982，输出 6198；估算 `$0.005613` |
| 转写结果 | 1 个视频成功，1126 字符，provider=`mimo`，model=`mimo-v2.5-asr`，`audio_hash` 已保存 |
| 报告结果 | 5 条结构化 claims；有效 Evidence 26 条，其中 1 条 Transcript Evidence 被 claims 引用 |
| Redis ASR 缓存 | BVID 与 `audio_hash` 两个键均存在，TTL 约 30 天；第二次读取未调用 Provider 或音频提取 |
| PostgreSQL 音频数据 | 保存必要转写文本、来源、provider、model 和 `audio_hash`；未保存原始音频或 Base64 |
| 临时文件 | `/app/tmp` 无残留文件 |
| Key/Base64 日志 | 未发现 Key 或 Base64 音频输出 |

第一次尝试使用 Token Plan Key 调公共端点返回 401；供应商页面又明确禁止 Token Plan 用于自动化脚本或应用后端，因此没有切到 Token Plan `/v1` 规避限制。换成余额扣费 MiMo Key 后，公共端点认证和真实转写成功。该余额 Key 可供 MiMo OpenAI 兼容 Agent 路由与 ASR 独立客户端复用；当前默认 Agent Provider 仍为 DeepSeek。

本次任务还发现：一次 Researcher 生成的无效转写 URL令 MCP 返回错误字符串，v2 将其误包装为第二条 Transcript Evidence；该条没有进入 structured claims，但进入了确定性附录。因此数据库原始行数为 27，有效 Evidence 为 26。现已修复 MCP 错误识别、转写工具返回类型与 Evidence 结构校验，错误文本不再成为 Evidence。报告 `model_info` 也曾固定写成 `mimo-v2.5-pro`，现已改为记录实际默认 Provider 与模型。两项修复均为确定性逻辑修复，没有再次提交收费任务。

缓存复验直接读取真实 Redis 数据，并把 Provider 与音频提取替换为一旦调用就失败的实现；结果仍返回同一份 1126 字符转写，证明 BVID 缓存命中发生在音频下载和 ASR 调用之前。两个键复验时 TTL 均为 2591124 秒。

这是单次真实端到端深度分析冒烟，样本量 n=1，不代表大规模 ASR 成功率、线上延迟或真实用户完成率。

该深度任务发生在 DeepSeek 模型别名迁移前；官方说明 `deepseek-chat` 当时对应 `deepseek-v4-flash` 非 thinking 模式，并将于 2026-07-24 15:59 UTC 废弃。代码与 `.env.example` 已切换到 `deepseek-v4-pro`，同时按官方 OpenAI 格式传入 `extra_body={"thinking":{"type":"disabled"}}`，避免结构化 JSON 节点重新出现 thinking-only。

迁移后使用项目真实 `ChatOpenAI` 客户端做最小调用，响应模型为 `deepseek-v4-pro`，正文非空、`reasoning_content` 为空，输入/输出 14/70 token。该检查只验证模型名和 thinking 参数透传，不等同完整端到端报告验收。

### DeepSeek V4 Pro 迁移后标准任务

| 项目 | 结果 |
|---|---|
| 时间 | 2026-07-13 20:45～20:47（Asia/Shanghai） |
| 输入 | `分析B站游戏攻略视频的选题方向和标题表达` |
| 产品链路 | 注册 → `POST /jobs` → Arq Worker → PostgreSQL → `GET /reports/{id}` |
| Provider / 模型 | `deepseek` / `deepseek-v4-pro` |
| thinking | 官方 OpenAI 格式显式 `disabled` |
| 最终状态 | `completed`，无重试；69.16 秒 |
| LLM 调用 | 5 次；Planner 1、Researcher 2、Analyst 1、Writer 1 |
| Token / 成本 | 输入 12993，输出 3333；按 cache miss 输入价保守估算 `$0.008552` |
| Evidence | 25 条：15 条真实 B站视频、10 条 RAG 来源 |
| 结构化结论 | 5 条 claims，JSON 解析层全部直接成功 |
| 标准模式 ASR | `asr_seconds=0` |

这是迁移后的单次本地端到端冒烟，样本量 n=1，只证明当前 V4 Pro + 非 thinking 产品链路可用，不代表线上性能或报告质量统计。

### 报告导出轻量冒烟

- 真实标准报告的只读分享页由 Chromium 正常渲染，能看到报告、结构化结论区域和 Evidence 来源，控制台 0 error / 0 warning。
- 浏览器 PDF 导出成功，临时 PDF 为 975650 bytes；验证后已删除 `.playwright-cli` 临时快照和 PDF。
- Markdown 导出仍由报告页将 `report.content` 生成为 `text/markdown` Blob；前端源代码未在本轮改变，最终 production build 结果记录在自动检查中。

## 尚未伪造的线上指标

自动测试没有消耗真实额度；本轮两次人工冒烟只证明单任务链路可用。以下指标仍需真实小规模测试后填写：

- 真实任务完成率
- p50 / p95 总耗时
- 每任务 LLM 调用次数
- Evidence 覆盖率与报告验证失败率
- MiMo ASR 成功率
- 真实并发能力与长期稳定性
- 用户可见错误分布

20 条冻结任务目前只证明产品输入、单平台边界和确定性入口可回归，不等同 20 次真实端到端报告完成率。
