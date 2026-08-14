# B站单平台产品 MVP 架构

## 页面信息架构

- 公共：首页、注册、登录、示例报告、公开分享报告
- 登录后：Dashboard、新建分析、任务进度、报告详情、历史任务、设置与用量
- 旧 `/report/{id}` 保留兼容跳转，正式报告路径为 `/reports/{id}`

## 任务流

```mermaid
flowchart LR
  U["登录用户"] --> A["POST /jobs"]
  A --> P["PostgreSQL 创建 pending 任务"]
  P --> Q["Arq 入队"]
  Q --> W["Worker 执行 LangGraph v2"]
  W --> R["Redis 状态和事件"]
  W --> E["Evidence 校验"]
  E --> D["PostgreSQL 报告和 Evidence"]
  D --> UI["前端轮询并打开报告"]
```

第一版进度读取采用可靠轮询。Worker 同时把短期状态写入 Redis Hash/Stream，后续可以在不改变任务模型的前提下增加跨 Worker SSE。

## 状态与恢复

- `pending`：已持久化并等待 Worker
- `running`：Worker 已领取
- `completed`：报告和引用校验通过
- `partial`：保留可用结果，并明确证据不足
- `failed`：保存产品错误码与可读说明
- `cancelled`：用户取消，Worker 轮询数据库后中止图任务

Worker 使用有限重试、指数退避、总超时与 Provider 并发信号量。API 幂等键在 `(user_id, idempotency_key)` 上唯一。

## 数据职责

| 组件 | 职责 |
|---|---|
| PostgreSQL | 用户、任务、报告、Evidence、反馈、用量、分享链接 |
| Redis | Arq 队列、临时状态、事件、锁、转写缓存 |
| ChromaDB | 知识库向量 |
| LangGraph Checkpointer | 当前仍为进程内短期图状态；业务恢复以任务与报告表为准 |

## 标准分析与 ASR 深度分析

标准分析链路：用户提交 → B站公开关键词搜索（失败或空时回退排行榜/热门池）→ RAG → LangGraph Agent 分析 → Evidence 校验 → PostgreSQL 保存报告。

深度分析链路：用户提交 → Worker 从本次返回样本中排除元数据已明确超过时长上限的视频，再选择最多 `ASR_MAX_VIDEOS` 个唯一的公开 B 站视频 → `yt-dlp` 提取临时音频 → `ffmpeg` 压缩为 64kbps MP3 → MiMo ASR → Transcript Evidence → Analyst/Writer 重新分析 → PostgreSQL 保存 → 临时目录自动删除。

`ASR_MAX_VIDEOS` 默认 5、合法范围 1～5。系统没有独立的全站 Top N 质量重排器，也不要求用户上传音频。全部转写失败时降级为元数据分析并记录 warning，报告不得假装读取过视频内容。

Agent LLM 默认使用 DeepSeek；网关也支持通过 `provider=mimo` 使用余额扣费 Key 和 MiMo 公共 OpenAI 兼容接口。MiMo LLM 与 MiMo ASR 共享凭证时仍走独立客户端，ASR 工具错误或缺少来源的非结构化结果不会进入 Evidence。
