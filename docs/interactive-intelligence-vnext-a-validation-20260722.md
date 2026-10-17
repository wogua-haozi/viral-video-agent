# vNext-A 验证记录（2026-07-22）

> 历史验收档案：结果和旧版截图仅对应标题日期的版本，不代表本轮本机验收或当前界面。当前状态见 [项目状态](project-status.md)。

## 范围与 Git

- 仓库：仓库根目录
- 起始分支：`main`
- 起始 SHA：`a5fb6b14de0db02ce3fd2d10565cd798fd6e41b7`
- 工作分支：`feat/interactive-intelligence-vnext`
- 状态机修复前 SHA：`160e1f59fdd6e2eaed1cd864cee453b625ae32af`。
- 本轮继续使用同一分支，不合并 `main`，最终提交与远端状态记录于最终汇报。
- 未修改 `feat/content-intelligence-p0` 或 `archive/p0c-architecture-failed-20260719`。

## 功能验证边界

- `ENABLE_INTERACTIVE_BRIEF=false` 为默认值，App 与 Worker 配置一致。
- 自动化 Brief Validator 使用 Fake/Mock LLM；外部 LLM、UAPI、ASR、B 站和 MCP 调用均为 0。
- 没有真实收费 canary，外部费用为 0。
- Job 页包含极简回答表单；没有复杂对话 UI 或视觉重构。
- 没有候选账号确认；没有修改 P0-C 账号资格、评分、排序、权重或 Provider。
- 没有证明候选质量提升，没有重新打开 P0-C，没有进入 P0-D/P0-E。

## 状态机与并发修复

- 澄清回答和普通 retry 均先锁定、校验并提交数据库状态，再调用 Redis/Arq enqueue；独立数据库会话在 enqueue 时已能看到 `pending` 和新 `execution_version`。
- enqueue 失败不会留下静默 `pending`：同一执行版本进入 `failed / WORKER_FAILED` 并记录失败事件；clarification 回答保持 `answered`，普通 retry 可用新版本恢复。
- 相同回答重复提交不会再次增加版本或入队；不同回答仍返回 HTTP 409。
- Brief Validator 的 LLM await 前后使用不同数据库会话；返回后锁定并重查 Job，只有当前执行版本且仍为 `running` 才能写 clarification 或 TopicSpec。
- Validator 期间取消后最终保持 `cancelled`，不创建 clarification、不进入图；旧 `execution_version` 的结果同样不能覆盖新版本。两种情况下，已经产生的 Validator 用量仍保存。
- 两轮上限统一由 Service 控制：round 1、round 2 均可由真实 `BriefValidator` 产生；第二次回答后直接形成带 assumptions、低 confidence 的保守 TopicSpec，Fake LLM 总调用次数为 2，不发第 3 次请求。

## Migration 往返

- 本轮未修改数据库 Schema 或 Migration，因此不重复运行完整 PostgreSQL 往返；以下结果沿用 vNext-A 初始实现的既有验证证据。
- 使用独立临时 PostgreSQL 16 容器，不接触 Compose 正式卷；验证后容器已删除。
- `upgrade head` 后 current 为 `20260722_0002 (head)`，`alembic check` 无漂移。
- downgrade 到 `20260713_0001` 后，4 个新增列和 `job_clarifications` 表的残留计数为 `0 / 0`。
- re-upgrade 后，新增列和表的恢复计数为 `4 / 1`；current 再次为 `20260722_0002 (head)`，`alembic check` 无漂移。

## 自动化与静态检查

- `tests/test_interactive_brief.py`：14 passed；新增覆盖提交后入队观察、普通 retry、enqueue 失败恢复、取消并发、旧版本防覆盖和真实 Validator 两轮上限。
- `tests/test_product_api.py tests/test_graph_v2.py tests/test_model_bootstrap.py`：22 passed；与定向测试合计 36 passed。
- 完整 Python pytest：76 passed，只有既有 LangGraph pending-deprecation warning。
- Python compile、`docker compose config --quiet`、前端 lint、TypeScript、生产 build 和 `git diff --check` 均通过。
- 澄清表单使用 `fieldset/legend` 关联 Radio 问题，Textarea 使用真实 `<label>`，提交错误保留 `role=alert`，loading/disabled 和原生键盘操作语义保持明确。
- 本轮无可见视觉变化，不重新生成截图。保留的 5 张 vNext-A 正式 QA 截图：
  - `output/playwright/vnext-a-home-final-20260722.png`
  - `output/playwright/vnext-a-templates-desktop-20260722.png`
  - `output/playwright/vnext-a-templates-mobile-20260722.png`
  - `output/playwright/vnext-a-templates-dark-20260722.png`
  - `output/playwright/vnext-a-clarification-form-20260722.png`
- 既有 Playwright 证据覆盖 1440px、375px、812×375 横屏、浅色/深色和 reduced-motion；模板登录回跳保留参数并正确预填；澄清回答提交后由 `waiting_user` 恢复为 `pending`；控制台 0 error / 0 warning。

## Gate 结论

vNext-A 状态机修复 Gate 候选通过，待总控复核。该结论只覆盖默认关闭的 PostgreSQL durable clarification backend、提交后入队、并发保护、两轮上限、极简回答表单语义和兼容性回归；PostgreSQL 业务状态机仍不是 LangGraph 原生 interrupt/resume。没有真实收费 canary，没有候选质量提升证明，P0-C 仍失败冻结，vNext-B 未开始且未经总控复核不得进入。
