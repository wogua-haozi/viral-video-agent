# vNext-C 候选账号人工确认闭环验证记录（2026-07-25）

## Gate 范围与 Git

- 基线分支：`feat/interactive-intelligence-vnext-c0`
- 起始 SHA：`d75ef5be428908a6d81472128d5d7e6fd9d3b04f`
- 工作分支：`feat/interactive-intelligence-vnext-c`
- 开始前远端 ahead/behind：`0/0`，工作树干净。
- 冻结分支保持：`feat/content-intelligence-p0=ca5e8b73402e1cf91a8fcb6cb719e3b3c71f6628`；`archive/p0c-architecture-failed-20260719=e224b5b5d20384b959a937f3f24841a8b398d80d`。
- 本阶段只实现“真实 Evidence → 确定性候选 → 用户逐项确认 → 原快照 Synthesis”的工程闭环；不重新修复 P0-C，不进入 vNext-D、P0-D 或 P0-E。
- 最终提交、远端 SHA、ahead/behind 和工作树状态以本次 Gate 汇报为准。

### Gate 阻塞修复追加轮次

- 修复起始 SHA：`298b36e45e6d00401041c2d0c9bd651c058a83cb`，工作分支仍为 `feat/interactive-intelligence-vnext-c`。
- 修复前远端 ahead/behind 为 `0/0`，工作树干净。
- 已确认断点：Brief Validator 已持久化 TopicSpec，但 Worker 保留原始 query 传入 Collection 后，Entry 仍只调用 `requires_analysis_workflow(user_request)`；“相机”“分析相机账号”等输入因此错误进入 direct-answer。
- 本轮只修复 TopicSpec 到 Collection Entry 的路由接管，不修改候选排序、MID 身份、快照、决策、报告过滤或冻结的 P0-C。

### 用户入口 Gate 阻塞修复

- 修复起始 SHA：`033d5ccdcf150ae82020d383f4285b9d165a30ec`；分支仍为 `feat/interactive-intelligence-vnext-c`，开始前远端 ahead/behind 为 `0/0`，工作树干净。
- 已确认剩余断点：`JobCreate.query` 和 `JobRevisionCreate.query` 的 `min_length=3` 使“相机”“摄影”“美食”“AI”等两字符主题在 Brief Validator 前被 FastAPI 以 422 拒绝。
- 两个请求 Schema 现在先裁剪首尾空白，再统一执行 2～2000 字符边界；纯空白、单字符和 2001 字符输入仍拒绝。
- 数据库保留裁剪后的用户原始语义，不拼接关键词，不用 TopicSpec 覆盖 query；默认功能开关、旧完整图和明确长请求路径不变。
- 本轮不修改 TopicSpec Entry 路由、候选提取、MID 身份、快照、决策、报告过滤、Migration 或冻结的 P0-C，也没有重复真实 B 站 Canary。

## 最小真实身份 Canary

正式实现前，对当前既有公开 B 站入口执行一次严格受限 Canary：

- 公开 HTTP 请求：1 个；读取结果：10 条。
- 合法 `platform_account_id`：10/10。
- 规范 `profile_url`：10/10。
- BVID、标题、URL 字段完整率：100%。
- Provider 状态正常，错误类别：无。
- Cookie、登录、代理、浏览器指纹和风控绕过：0。
- LLM、MCP、UAPI、ASR 调用：0；费用：0。

Canary 只记录上述聚合统计，没有输出、保存或提交真实 MID、账号名、标题、搜索关键词或完整响应。它只证明当前公开入口实际能提供稳定 MID，不证明候选账号质量、竞品准确率或入口长期可用性。

## 候选身份、去重与排序

候选使用 Pydantic strict mode、`extra=forbid` 和不可变投影：

- `candidate_id = "cand_" + sha256("bilibili|mid:{mid}")[:24]`。
- 只使用 C0 的合法 `platform_account_id` 作为身份；`display_name` 仅展示。
- 同 MID 的多条视频 Evidence 合并为一个候选；同名不同 MID 保持分离；无 MID 不生成候选。
- `source_evidence_ids`、最多 3 个 `sample_titles` 和 Evidence 链接都来自当前采集快照。
- `why_surfaced` 只说明搜索样本中有多少视频来自该账号，不宣称该账号已经被模型判定为竞品。
- 排序依次为匹配 Evidence 数降序、首次 Evidence 出现顺序、MID 稳定排序，最多 8 个。
- 候选和快照使用 canonical JSON SHA-256；相同内容得到稳定哈希。

没有使用 P0-C 权重、标签、Prompt、账号名单、人工真值、粉丝数、增长率或其他推断指标。

## Collection / Synthesis 架构

v2 图在 Evidence Gate 后安全切分，并复用同一套现有节点函数：

```text
Collection: Entry -> Planner -> Researcher -> Evidence Gate -> candidate extraction -> PostgreSQL snapshot
Synthesis:  PostgreSQL snapshot -> confirmed Evidence filter -> Analyst -> Writer -> report validation
```

- `build_collection_graph_v2()` 只含 Entry、Planner、Researcher、Evidence Gate，结束后持久化快照并进入 `waiting_candidate_confirmation`。
- `build_synthesis_graph_v2()` 只含 Analyst 和 Writer，没有 Planner 或 Researcher。
- 确认后不再执行 Brief Validator、搜索、MCP、UAPI、ASR 或任何重新采集路径。
- Worker 根据 `candidate_synthesis_runs` 和新的 `execution_version` 判断 Synthesis，不依赖进程内 `MemorySaver`。
- 自动化测试将运行时图和测试图指向同一 Collection / Synthesis 核心函数，避免平行实现漂移。

### TopicSpec Entry 路由修复

经过严格校验并持久化的 TopicSpec 现在是 Collection Entry 的结构化分析契约。合法且 `platform=bilibili` 时，Entry 直接进入 Planner / Researcher / Evidence Gate，不再要求原始 query 同时包含平台与分析动作关键词。原始 `analysis_jobs.query` 和图内 `user_request` 不覆盖、不改写、不拼接，继续用于展示与审计。

非空 TopicSpec 会在 Entry 再次按 `TopicSpec` Schema 校验并规范化；非法平台、空必填集合或额外字段会以 `invalid_topic_spec` 保守终止，且 direct-answer、Planner、Researcher 和采集工具调用均为 0。TopicSpec 不存在时，旧 `requires_analysis_workflow()` 行为保持不变；候选确认开关关闭时，Worker 继续运行原完整图。

修复前真实 Collection Graph 回归稳定复现：3 个模糊输入均为 `planner=0 / researcher=0 / tool=0 / direct=1`。修复后同一组输入均为 `planner=1 / researcher=1 / tool=1 / direct=0`。该较早测试直接向数据库插入已带 TopicSpec 的 Job，只证明 TopicSpec 接管 Entry 后的 Collection 路由，不再被表述为完整用户入口证据。

本轮新增组合测试从真实 `POST /jobs` 提交 `query="相机"` 开始：API 创建 Job 并保留 query；Worker 首次执行真实 Brief Service，由 Fake Validator 生成澄清并进入 `waiting_user`；真实 clarification API 接收回答、增加执行版本并重新入队；Worker 恢复后由 Fake Validator 生成合法 TopicSpec，再运行真实 `build_collection_graph_v2()` 的 Entry、Planner、Researcher 和 Evidence Gate。最终各持久化 1 个 CollectionSnapshot、1 个 CandidateSnapshot 和 1 个候选账号，Job 进入 `waiting_candidate_confirmation`。Brief Validator 调用 2 次，对应初次与回答后恢复；Planner、Researcher 和 Fake 搜索各 1 次，direct-answer 为 0，没有重复采集。

## 快照、Evidence 与数据库

Migration `20260725_0004_candidate_confirmation.py` 新增 6 张表：

- `collection_snapshots`
- `candidate_snapshots`
- `candidate_accounts`
- `candidate_decision_batches`
- `candidate_decisions`
- `candidate_synthesis_runs`

同时把 `analysis_jobs.status` 从 `varchar(20)` 扩为 `varchar(40)`，并新增 5 个显式查询索引。结构边界如下：

- Collection 快照保存恢复 Synthesis 所需的 TopicSpec、计划、最小 raw data、Evidence、工具结果、查询和采集用量。
- 候选快照与用户 decision batch 分表；用户决策不能覆盖系统候选事实。
- Collection/Candidate 快照按 `job_id + source_execution_version` 唯一；快照 ID、Schema version 和内容哈希持久化后不修改。
- Evidence ID 在暂停前后保持不变；Synthesis 只接受当前 Job、执行关系和哈希均匹配的快照。
- Job 删除只级联自己的快照；新范围修订产生新 Job，不继承旧候选决策作为真值。
- 手动 retry 继续关联既有 decision batch 与原快照，不重新采集。

使用独立临时 PostgreSQL 16 容器完成往返，不接触正式卷：

- upgrade head、current、`alembic check` 通过。
- downgrade 到 `20260723_0003` 后，6 张新表和 5 个新索引残留均为 0，`analysis_jobs.status` 恢复为 `varchar(20)`。
- re-upgrade 后 6 张表恢复，status 为 `varchar(40)`；再次 current 与 `alembic check` 通过。
- 临时 PostgreSQL 容器已删除。

## 状态机与服务端能力

新增非失败状态 `waiting_candidate_confirmation`：

```text
running -> waiting_candidate_confirmation -> pending -> running -> completed / partial / failed
```

- Collection 有候选时进度为 55%，Worker 正常结束等待用户。
- 无合法候选时直接 `partial / CANDIDATE_EVIDENCE_INSUFFICIENT`，不生成空确认页，也不按账号名猜测。
- 等待确认时 `can_retry=false`、`can_revise=true`、`can_confirm_candidates=true`，并允许取消。
- 决策提交后进度至少为 60%，增加 `execution_version`，清除旧 `arq_job_id`，写入 `dispatch_pending_at`，数据库提交后再 enqueue。
- 提交期间或采集期间若 Job 已取消，旧执行版本不能把状态改回等待或完成。

前端只消费服务端能力，不复制 `waiting_candidate_confirmation` 的操作判断。

## API、权限与幂等

新增：

```text
GET  /jobs/{job_id}/candidates
POST /jobs/{job_id}/candidates/decisions
```

GET 只返回最多 8 个候选的有限投影、TopicSpec 摘要、当前 decision、快照版本/哈希、上限与 `can_submit`，不返回大型 raw data。

POST 具备以下约束：

- 登录与 Job 所有权隔离；其他用户得到与 Job 不存在相同的外部语义。
- snapshot 必须属于当前 Job 与采集执行版本。
- 所有候选必须明确提交一次 decision；未知、遗漏或重复 `candidate_id` 被拒绝。
- 不接受 `undecided`，且至少一个候选必须为 `confirmed`。
- reason trim 后最长 200 字；请求体由 ASGI middleware 限制为 16 KiB。
- 相同 `request_id`、Job、snapshot、用户和规范化 payload 幂等返回，不增加执行版本或重复入队。
- 相同 `request_id` 的不同内容返回 409；已提交 snapshot 不能被后台模型覆盖。
- enqueue 失败返回明确的派发等待语义，并保留 vNext-B reconciliation 所需意图。

## 报告过滤与 Evidence 追溯

Synthesis 恢复时重新计算并核对 Collection 哈希、Candidate 哈希和 Decision 哈希。confirmed 对应的视频 Evidence，以及与 confirmed 视频 URL 同源的 Transcript Evidence，才会进入 Analyst / Writer：

- confirmed：进入正常分析。
- excluded：不进入正常竞品结论，也不传给 Analyst / Writer。
- uncertain：不传给 Analyst / Writer，只进入确定性的“未纳入或待确认范围”。

最终报告继续通过现有 Claim/Evidence 引用校验，并追加用户确认边界：候选来自系统检索、纳入由用户确认、结论只适用于本次公开 Evidence 快照、用户确认不等于模型准确率，也不代表市场份额、全站排名、长期增长或完整行业覆盖。

## 前端与浏览器 QA

使用现有 Next.js、Tailwind 和 Lucide，没有引入新 UI 框架。候选区域使用 `fieldset` / `legend`、原生 radio、真实 label、就近 `role=alert`、loading/disabled、可选原因和 Evidence 链接；默认不选择“纳入分析”。

真实 Chromium 使用本地虚构 QA 数据完成：

- 1440px 桌面浅色候选页。
- 375px 移动端深色候选页；`scrollWidth=clientWidth=360`，无横向溢出。
- 键盘 Space 完成 confirmed / uncertain / excluded 三态选择。
- 全部已选择但 confirmed 为 0 时出现总错误；缺失选择在对应候选旁显示 `role=alert`。
- 修改范围面板可打开；等待确认状态可取消，取消后保持 `cancelled`。
- 移动菜单 Escape 关闭并恢复焦点。
- 提交路由延迟 1.2 秒时，按钮 `disabled=true`、`aria-busy=true`；第二次点击被阻止，请求计数为 1。
- 提交后刷新：Job 为 `pending`、进度 60%、`execution_version=1`；GET candidates 恢复 1 个 confirmed、1 个 uncertain、1 个 excluded，`can_submit=false`。
- 修复主题按钮初始 SSR `aria-label` 不一致后，干净候选/提交页面 console 为 0 error / 0 warning。

正式截图：

- `output/playwright/vnext-c-candidates-desktop-light.png`
- `output/playwright/vnext-c-candidates-validation-errors.png`
- `output/playwright/vnext-c-scope-revision.png`
- `output/playwright/vnext-c-candidates-mobile-dark.png`
- `output/playwright/vnext-c-submit-pending.png`

截图已目检；QA 账号、密码、SQLite、日志、浏览器调试快照、临时目录、后端/前端进程和 Redis 容器均已删除，只保留上述正式截图。

## 自动化验证

全部自动化测试使用 Fake/Mock，不调用真实收费服务：

- `tests/test_candidate_confirmation_vnext_c.py`：18 passed。
- `tests/test_topic_spec_collection_routing_vnext_c.py`：16 passed，包含真实 API、Brief Service、clarification API、Worker 与 `build_collection_graph_v2()` 组合路径；Validator、Planner/Researcher LLM 与搜索均为 Fake。
- `tests/test_interactive_brief.py`：14 passed。
- vNext-C0：15 passed。
- vNext-A：14 passed。
- vNext-B：21 passed。
- 完整 Python pytest：146 passed；只有既有 LangGraph pending-deprecation warning。
- 前端 lint、TypeScript/生产 build 通过。
- Python compile、`docker compose config --quiet`、`git diff --check` 通过。
- 本轮变更文件的高风险秘密模式、私有本机路径和危险命令模式扫描均为 0；测试密码文本均为固定占位值，不是凭证。

原 18 条 vNext-C 测试覆盖候选身份/去重/排序/上限/哈希、严格契约、快照跨会话恢复、跨 Job/执行版本隔离、无候选诚实终止、所有权、完整决策校验、至少一个 confirmed、幂等/冲突、单次入队、派发恢复、16 KiB 限制、confirmed-only Synthesis、禁止重复 Brief/Planner/Researcher/搜索/ASR、报告边界、哈希篡改、手动 retry、取消并发、分阶段图节点和前端可访问性合同。16 条入口/路由测试覆盖 TopicSpec 接管、direct-answer 禁止、完整 API 到候选等待链路、JobCreate/JobRevisionCreate 一致边界、无 TopicSpec 与明确请求回归、功能开关回退、非法 Schema 拒绝及不重复 Brief/搜索/采集。

## 外部调用、安全与负面边界

- 外部业务调用只有实施前的 1 个公开 B 站 Canary 请求；其余测试与浏览器 QA 都在本地，费用总计 0。
- 未通过命令查看或输出 `.env` 内容；未提交 `.env`、Key、Token、Cookie、真实 MID、账号名、标题、搜索响应、私有评测、P0 Evidence、Bundle 或 archive 内容。项目既有配置模块在导入时仍保留 `load_dotenv()` 行为。
- 未提交 QA 密码、SQLite、临时路径、数据库日志、Playwright 调试目录、构建缓存或临时容器数据。
- 默认 `ENABLE_CANDIDATE_CONFIRMATION=false`；App、Worker、Compose 与 `.env.example` 保持一致，不改变 Researcher 微调模型开关。
- Canary 只证明稳定 MID 可读；用户入口组合测试只证明两字符主题能通过真实 API 和澄清服务进入真实 Collection。工程 Gate 不证明候选质量提升、自动竞品识别、模型准确率、真实用户价值、生产 SLA 或 P0-C 成功。
- P0-C 质量 Gate 继续失败冻结；P0-D/P0-E 未开始；vNext-D 未开始。

## Gate 结论

vNext-C 工程闭环 Gate 阻塞修复候选通过，等待总控复核。当前证据证明：两字符主题可通过真实创建 API，真实澄清 Service 和回答 API 能恢复同一 Job，经过严格校验的 TopicSpec 能接管真实 Collection Entry 路由，裁剪后的 query 保持语义可审计；候选来自真实公开 Evidence 的稳定 MID；采集与确认可跨数据库会话恢复；用户确认后不重复采集；excluded/uncertain 不会进入正常分析；权限、执行版本、哈希和幂等边界成立；完整回归通过。

必须停在 vNext-C Gate Review。该结论不代表候选质量、P0-C 或生产部署通过，不得自动进入 vNext-D。
