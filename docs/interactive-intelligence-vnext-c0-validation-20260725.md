# vNext-C0 稳定账号身份数据契约验证记录（2026-07-25）

## Gate 范围与 Git

- 基线分支：`feat/interactive-intelligence-vnext-b`
- 基线 SHA：`07a9e3ad37e28ca0191b0f5ae284785d8886aab5`
- 工作分支：`feat/interactive-intelligence-vnext-c0`
- 开始前远端 ahead/behind：`0/0`，工作树干净。
- 冻结分支保持：`feat/content-intelligence-p0=ca5e8b73402e1cf91a8fcb6cb719e3b3c71f6628`；`archive/p0c-architecture-failed-20260719=e224b5b5d20384b959a937f3f24841a8b398d80d`。
- C0 只修复稳定账号身份数据契约；不实现 vNext-C 候选确认闭环，不进入 vNext-D。

## 阻断根因与修复

原 `_parse_bilibili` 从 B 站视频对象中只保留 `owner.name` 为 `author`，即使输入包含 `owner.mid` 也会丢弃。后续 `raw_data` 和 Evidence 因此只能看到显示名称，不能形成稳定账号身份。

C0 新增启用 Pydantic strict mode、不可变、拒绝额外字段的 `BilibiliAccountIdentity`：

- `platform_account_id`：从合法 `owner.mid` 规范化得到的正整数字符串。
- `display_name`：展示名称，不参与身份判断。
- `profile_url`：只能是由 MID 确定性生成的 `https://space.bilibili.com/{mid}`。

有效整数、数字字符串和带前导零的数字字符串会收敛到同一 MID。缺失、零、负数、布尔值、浮点数和非数字字符串不会产生身份或主页。显示名称相同但 MID 不同的结果保持两个不同身份；没有 MID 时不会使用名称猜测账号。

## 数据流与兼容性

- B 站排行榜和热门接口继续使用同一个 `_parse_bilibili`，没有增加新网络请求。
- 搜索结果 raw data 保存三个新身份字段。
- Evidence `raw_data` 保留完整搜索结果；有限 `data_fields` 投影新增 `platform_account_id`、`display_name` 和 `profile_url`。
- 既有 `author` 字段保留，并等于 `display_name`，避免破坏现有 Prompt、Analyst、Writer 和评测调用者。
- 视频 `evidence_id` 仍按视频来源身份生成；账号字段不会改变已有视频 Evidence 的稳定规则。
- 没有数据库 Schema、Migration、API、状态机、Worker 分阶段、功能开关或前端变化。

## 自动化验证

全部测试使用本地构造数据和 Fake HTTP Client，不发起真实 B 站、LLM、MCP、UAPI 或 ASR 调用。

- `tests/test_candidate_identity_contract.py`：15 collected，覆盖合法 MID 规范化、无身份不猜测、同名不同 MID、Schema 额外字段拒绝、MID/主页一致性、Evidence 投影和搜索入口透传。
- `tests/test_candidate_identity_contract.py tests/test_reporting_validation.py tests/test_graph_v2.py tests/test_researcher_mcp.py`：34 passed。
- 完整 Python pytest：112 passed；仅有既有 LangGraph pending-deprecation warning。
- Python compile、`docker compose config --quiet` 和 `git diff --check` 通过。

C0 没有数据库变更，因此没有伪造 Alembic 往返结果；没有 UI 变更，因此没有运行或沿用浏览器截图作为本阶段证据。

## 外部调用、安全与边界

- 外部业务调用 0，费用 0。
- 未读取或提交 `.env`、Key、Token、Cookie、真实账号、真实 MID、私有评测或完整响应。
- 没有提交临时数据库、缓存、构建目录或调试截图。
- C0 只证明当前搜索数据契约能够携带稳定 MID 和规范主页；不证明候选账号质量、自动竞品判断、稳定 Top 5、用户价值或生产 SLA。
- P0-C 质量 Gate 继续失败冻结；P0-D/P0-E 未开始。

## Gate 结论

vNext-C0 为独立 Gate 候选：稳定账号身份不再在搜索解析阶段丢失，缺失身份时不会按显示名称猜测，且身份能够进入 raw data 与 Evidence 投影。当前必须停在 C0 Gate Review；未经总控复核不得自动开始 vNext-C，也不得进入 vNext-D。
