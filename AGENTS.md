# 本地项目协作约束

## 当前主线与范围

- 唯一开发目录为 `D:\internship\viral-video-agent`。临时导入目录只作比较来源，禁止递归导入、整目录覆盖、镜像删除、`git reset --hard` 或 `git clean`。
- 先读 `docs/project-status.md`；当前路线为：稳定性与试用配置完善 → 工程验证并推送 → 网页 ChatGPT 只读复审 → 用户本地真实任务与报告质量验收 → 小范围创作者试用 → 反馈迭代。保留简洁柔和前端；旧计划保留为历史，不自动继续旧待办。
- 保持 B 站单平台、LangGraph v2 默认和 v1 回退；不切换默认模型，不擅自开启实验开关。
- P0-C 质量 Gate 失败并冻结；vNext-C 工程通过不等于报告质量通过。P0-D/P0-E、vNext-D、付费订阅、团队协作、多平台不在当前实施范围。

## 协作与 Git

- 后续代码修改、测试和 Git 操作集中在本地 Codex；网页 ChatGPT 负责审查、讨论和计划。
- GitHub 远端访问与推送须有用户明确授权。2026-10-20 已授权整合及试用前可靠性修复批次；2026-10-31 用户通过前端视觉验收，并授权本轮前端/文档/清理收尾后，用标准 Git 仅推送目标 `main` 至 `https://github.com/wogua-haozi/viral-video-agent`。后续批次仍须用户确认。不访问旧账号仓库，不创建 PR、不部署、不探测账号恢复状态。
- 今后任何项目和环境，都禁止通过 GitHub API 或连接器上传代码、写文件、创建提交或更新分支引用来发布代码。
- 保存代码使用常规 `git commit`。保留用户已有暂存、未提交和未跟踪的重要内容，只提交当前任务相关文件。
- 只有用户明确确认某一批次，才可常规 `git push`；不得自动换用其他上传方式。只推送已审查的目标分支，不使用 `--all`、`--mirror` 或顺带上传本地实验分支。

## 数据与验证

- 备份仅放在被 Git 忽略的 `backups/`；保留真实 `.env`、知识资料、媒体、数据库和 Docker 数据卷。配置盘点只输出变量名与是否缺失。
- App 的 Compose 启动会自动迁移数据库。现用库升级前必须确认目标、停止写入、建立可恢复备份并准备回退方案；不能确认安全则只继续隔离验证。
- PostgreSQL 回归仅用专用测试数据库及 `PILOT_TEST_POSTGRES_URL`；默认夹具测试，不擅自调用真实付费模型、ASR 或外部视频服务。禁止删除业务数据卷或 `docker compose down -v`。
- 优先运行 `python -m pytest -q`、前端 `npm run lint` / `npm run build`、`git diff --check`；UI 变更复用 `frontend/tests/creator-pilot.cjs` 并目检实际截图。
- 当前状态、任务优先级和本机验收统一维护在 `docs/project-status.md`。历史记录保持原结论；新测试不能把冻结失败改成通过。
