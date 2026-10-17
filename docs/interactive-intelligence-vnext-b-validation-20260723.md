# vNext-B 验证记录（2026-07-23）

> 历史验收档案：结果和旧版截图仅对应标题日期的版本，不代表本轮本机验收或当前界面。当前状态见 [项目状态](project-status.md)。

## Gate 范围与 Git

- 仓库：仓库根目录
- 基线分支：`feat/interactive-intelligence-vnext`
- 起始 SHA：`c34214e0570a7a8b3258fc9be6e0c6cbff0b10a3`
- 工作分支：`feat/interactive-intelligence-vnext-b`
- 本次 Gate 阻塞修复基线：`c160387b7d915402023ba09574a1a207234494ec`
- 未合并 `main`，未修改 `feat/content-intelligence-p0` 或 `archive/p0c-architecture-failed-20260719`。
- 最终提交、远端 SHA、ahead/behind 和工作树状态以本次 Gate 汇报为准。

## 总控负面复现与根因

总控复现了 `waiting_user` Job 创建修订后，旧 Job 变为 `cancelled`，但 pending clarification 按审计要求继续保留。旧前端只根据 `status in {failed, cancelled}` 显示“重新分析”，因此展示了必然被后端 `JOB_NOT_RETRYABLE` 拒绝的按钮；Job 页 retry 又没有 catch、loading 或就近错误提示，可能产生未处理 Promise rejection。

根因不是后端 retry 校验错误，而是前端复制了不完整的状态判断。修复不删除 clarification，也不放宽 retry：由 `JobRead` 统一返回操作能力，前端消费能力，后端继续使用同一规则校验请求。

## 操作能力合同

- `can_retry=true`：Job 状态属于 `failed`、`cancelled`、`partial`，且不存在 pending clarification。
- `can_retry=false`：包括已被范围修订取消但仍保留 pending clarification 的旧 Job，以及 completed、pending、running、waiting_user。
- `can_revise=true`：Job 状态属于 `waiting_user`、`failed`、`cancelled`、`completed`、`partial`。它表示状态机允许作为修订来源；用量限制和深度分析能力仍在提交时校验。
- 能力由 ORM 响应属性计算，不增加数据库冗余列。详情、列表和写操作响应使用同一合同。
- retry 接口直接复用 `can_retry`，所以页面加载后的并发状态变化仍返回 409；前端隐藏按钮不替代后端防线。

## vNext-B 设计结论

### 澄清历史

`GET /jobs/{job_id}/clarification` 先校验 Job 所有权，再分开返回：

- `current`：只包含 `waiting_user` 当前可回答的问题。
- `history`：只包含按 round 升序排列的已回答记录，包括所选选项、自定义回答、状态和回答时间。

接口不返回内部 Prompt、模型原始响应、Key、Cookie 或其他敏感执行数据。Job 页也把当前问题与历史回答分成独立区域。

### 范围修订

采用“根据旧任务创建新 Job”，不原地修改旧 Job。新 Job 通过 `revision_of_job_id` 指向来源；旧、新 Job 都记录审计事件。旧 clarification、TopicSpec、报告和用量保持原记录。

- `pending`、`running` 拒绝修订。
- `waiting_user` 在同一事务内先取消旧任务，再创建修订任务；旧问题和回答不删除。
- `failed`、`cancelled`、`completed`、`partial` 可作为不可变来源。
- 来源 Job 已有修订时禁止删除，避免破坏审计链。
- 新 Job 从 `clarification_round=0`、`execution_version=0`、`retry_count=0` 开始。

没有选择重置同一 Job，因为它会混淆轮次、执行版本、报告归属和历史审计。

### Commit / enqueue 崩溃窗口

采用 PostgreSQL reconciliation，不引入完整 transactional outbox。理由是当前只需恢复一种可由 Job 状态完整重建、且已有确定性 ID 的 Arq 消息；新增 outbox 表和发布生命周期会扩大当前阶段的迁移与运维面。

- 创建、回答、retry 和修订在提交 `pending` 时写入 `dispatch_pending_at`。
- Worker 每分钟运行一次有限批量扫描；默认只处理超过 60 秒、`pending + arq_job_id=null` 的记录。
- 恢复复用原 `execution_version` 和 `analysis:{job_id}:v{execution_version}`，不增加 `retry_count`。
- cancelled、failed、running、waiting_user、completed、partial、近期任务或已有 Arq ID 的任务不会被恢复。
- 恢复前、成功和失败都有审计事件；失败后至少再等待安全阈值，不忙等待。
- Redis 已接收但数据库未保存 Arq ID 时，重复派发仍使用同一个队列身份。

Migration `20260723_0003_interactive_vnext_b.py` 增加 `revision_of_job_id`、`dispatch_pending_at`、外键和扫描索引。

## 自动化验证

- vNext-B 定向：`21 passed`，包含原 vNext-B 恢复测试和本次操作能力修复测试。
- `tests/test_interactive_brief.py`：`14 passed`，vNext-A 回归保持通过。
- `tests/test_product_api.py tests/test_graph_v2.py tests/test_model_bootstrap.py`：`22 passed`。
- 完整 Python pytest：`97 passed`；只有既有 LangGraph pending-deprecation warning。
- Python compile、`docker compose config --quiet`、前端 lint、TypeScript/生产 build、`git diff --check` 均通过。
- 全部测试使用 Fake/Mock；没有调用真实 LLM、UAPI、ASR、B站或 MCP。

定向覆盖所有权隔离、current/history 顺序、旧回答不可变、新 Job 审计关系、非法状态、commit 后中断恢复、retry_count 不变、确定性 Arq ID、状态白名单、旧执行版本隔离、重复 reconciliation 幂等和默认关闭回退。

本次新增覆盖：修订后旧 Job `can_retry=false`、直接取消 waiting_user 后仍不可 retry、普通 failed/cancelled/partial 可 retry、其他状态不可 retry、详情/列表能力一致、伪造 retry 仍返回 409，以及前端使用服务端能力并完整处理 retry 失败。

## Migration 往返

使用独立临时 PostgreSQL 16 容器，不接触项目正式卷：

- upgrade 到 `20260723_0003` 成功。
- downgrade 到 `20260722_0002` 后，新列/索引残留为 `0 / 0`。
- re-upgrade 后，新列/索引恢复为 `2 / 2`。
- `alembic check` 无漂移。
- 临时容器已删除，Docker Desktop 恢复为停止状态。

## 浏览器与可访问性 QA

真实 Chromium 验证了澄清历史、当前问题分区、修订表单、报告页入口、修订后导航和来源链接：

- 桌面浅色：`output/playwright/vnext-b-clarification-history-desktop-20260723.png`
- 375×812 移动端浅色：`output/playwright/vnext-b-revision-mobile-20260723.png`
- 375×812 移动端深色：`output/playwright/vnext-b-revision-mobile-dark-20260723.png`
- 375×812 cancelled + pending clarification：`output/playwright/vnext-b-gate-can-retry-mobile-20260723.png`

修订表单支持 Tab/Enter 键盘操作；按钮 loading/disabled 明确；Textarea 有真实 label；澄清选择保留 fieldset/legend；错误使用 `role=alert`。移动端 `scrollWidth/innerWidth=375/375`，无横向溢出；浏览器控制台 0 error / 0 warning。开发服务器仍会输出既有 Next 本地跨域 future warning 和 Node deprecation warning，不影响生产 build。

本次 Gate 阻塞复核中，cancelled + pending clarification 页面不显示“重新分析”，仍显示“修改范围”，并明确旧任务和回答会保留；实测 `scrollWidth/innerWidth=360/375`，无横向溢出，静态页面控制台 0 error / 0 warning。另模拟页面加载后新增 pending clarification：原按钮触发 retry 后后端返回预期 409，页面就近显示 `role=alert`，重新读取后按钮消失且“修改范围”保留；控制台只有该预期 409 的网络资源记录，没有未处理 Promise rejection。

## 安全、外部调用与边界

- 未读取或提交 `.env`；未硬编码 Key、Token、Cookie、账号、MID 或私有路径。
- 未提交 QA SQLite、Playwright 调试快照、缓存、构建目录、真实响应或大型调试文件。
- 外部业务调用 0，费用 0。
- PostgreSQL 业务状态机仍不等于 LangGraph 原生 interrupt/resume。
- 本阶段没有证明候选账号选择质量提升。
- P0-C 继续失败冻结；P0-D/P0-E 未开始。
- vNext-C 候选账号人工确认尚未开始。

## Gate 结论

vNext-B 为 Gate 候选，等待总控复核。该结论只覆盖澄清历史、可审计范围修订、派发崩溃窗口恢复、必要前端入口和兼容性回归；不得据此自动进入 vNext-C。
