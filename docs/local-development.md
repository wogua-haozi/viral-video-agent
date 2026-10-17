# Windows 本地运行与数据保护

当前状态、验收和唯一任务清单见 [项目状态](project-status.md)。工作目录始终为 `D:\internship\viral-video-agent`。本轮不访问 GitHub、不部署、不提交真实收费任务。

2026-10-18 已明确暂不启动完整 Docker 栈。本手册保留后续运行步骤，待准备试用时再执行；启动服务不属于当前整理阶段的未完成项。

## 前端预览与开发

PowerShell：

```powershell
Set-Location D:\internship\viral-video-agent\frontend
npm run dev -- --hostname 127.0.0.1 --port 3007
```

浏览 [首页](http://127.0.0.1:3007) 与 [示例](http://127.0.0.1:3007/examples)。停止按 `Ctrl+C`。独立前端只提供公共页预览，注册、工作台、提交任务需要后端；浏览器回归里的工作台和报告使用明确的虚构接口夹具。

```powershell
npm run lint
npm run build
npm run start -- --hostname 127.0.0.1 --port 3007
```

本机已实际使用生产构建运行回归。由于项目保留 Docker 的 `output: standalone` 设置，`next start` 会打印提示；本地服务可启动，Docker 正式入口是镜像中的 `node server.js`。

另一终端运行既有浏览器回归（不调用业务后端）：

```powershell
Set-Location D:\internship\viral-video-agent\frontend
# 本机已有的 Playwright；其他电脑改为自身安装目录
$env:VVA_PLAYWRIGHT_PACKAGE='D:\srp_project\AI_school\report-web\node_modules\playwright-core'
$env:VVA_BROWSER_EXECUTABLE='C:\Users\0\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
$env:VVA_BASE_URL='http://127.0.0.1:3007'
node tests/creator-pilot.cjs
```

脚本默认刷新 `output/creator-pilot` 的截图和验证 JSON；可通过 `VVA_OUTPUT_DIR` 指定其他结果目录。演示数据不代表实际视频、账号或产品质量。

## 后端夹具测试与依赖

```powershell
Set-Location D:\internship\viral-video-agent
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

默认未设置 `PILOT_TEST_POSTGRES_URL` 时，PostgreSQL 专用用例跳过；其他用例使用临时 SQLite、Fake 模型/队列/工具。仅在已经确认专用测试库后设置：

```powershell
# 在当前终端设置专用测试库连接串，不粘贴到日志或提交；不能使用业务库
$env:PILOT_TEST_POSTGRES_URL='<dedicated-test-database-url>'
.\.venv\Scripts\python.exe -m pytest -q tests/test_creator_pilot_postgres.py
Remove-Item Env:\PILOT_TEST_POSTGRES_URL
```

每条 PostgreSQL 测试只迁移随机 schema 并清理自身 schema。无真实收费调用。恢复其他电脑环境时按现有声明安装：

```powershell
# 仅缺失虚拟环境时创建；不覆盖已有环境
if (-not (Test-Path .venv\Scripts\python.exe)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
Push-Location frontend
npm ci
Pop-Location
```

本机现有 `.venv` 继承全局包，完整环境的 `pip check` 仍可能包含其他项目的冲突；项目实际测试结果以状态页为准，不为修复它们升级全局包。新的干净环境与 Docker 全栈构建需要另行验证。宿主机深度分析还需要 PATH 中的 `ffmpeg`；Dockerfile 已声明安装。

## 完整业务服务：先确认配置和旧库

本机留有 `viral-video-agent_postgres_data` 和 `viral-video-agent-ui-demo_postgres_data` 两套 PostgreSQL 16 卷。本轮只读确认了主版本，没有启动、升级或替换其中任何一套；旧库 schema、账号和数据完整性尚未验证。普通 Compose 项目名继续使用 `viral-video-agent`，不能把演示卷误当业务库。

真实 `.env` 已保留。只有文件不存在时才复制模板：

```powershell
Set-Location D:\internship\viral-video-agent
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

需要核对的变量名：`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`JWT_SECRET`、`DATABASE_URL`。Compose 会自行构造容器内 `DATABASE_URL`；宿主机直跑才使用 `.env` 的数据库地址。更改 `POSTGRES_PASSWORD` 不会自动改变已有卷里的数据库角色密码，必须先确认原库凭证。`DEEPSEEK_API_KEY`、`MIMO_API_KEY` 仅确认存在，本轮没有验证外部可用性。

保留默认模型、`GRAPH_VERSION=v2`、`USE_FINETUNED_MODEL=false`、`ENABLE_INTERACTIVE_BRIEF=false`、`ENABLE_CANDIDATE_CONFIRMATION=false`。若后续明确试用候选确认，App/Worker 必须使用一致开关，不能仅改前端。

80 和 6379 已被另一个项目使用。新增的本地覆盖文件只将本项目宿主机端口改成 8087 和 6387，容器内地址和既有卷名不变；不需要停止其他项目。

```powershell
$compose=@('-f','docker-compose.yml','-f','docker-compose.local.yml')
docker compose @compose config --quiet
```

### 现用库升级前的备份与回退

以下是后续操作手册，本轮未执行现用库升级。先确认原项目库的所有权与凭证；禁止直接运行整个 `up`，因为 App 启动会自动迁移到 `20261017_0005`。

1. 停止 App/Worker 的写入，只启动已确认的 PostgreSQL。保留原镜像/版本和 `backups/integration-20261017-232846` 中的 Git bundle、源码与配置快照。
2. 导出数据库到 `backups/` 并记录 SHA-256；备份包含业务数据，不能提交。示例使用容器自身环境变量，不把密码放进命令或输出。

```powershell
docker compose @compose stop app worker
docker compose @compose up -d postgres
docker compose @compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/vva-pre-pilot.dump'
if ($LASTEXITCODE -ne 0) { throw '数据库备份失败，停止升级' }
docker compose @compose cp postgres:/tmp/vva-pre-pilot.dump backups/vva-pre-pilot.dump
if ($LASTEXITCODE -ne 0) { throw '备份复制失败，停止升级' }
Get-FileHash backups/vva-pre-pilot.dump -Algorithm SHA256
```

3. 在独立的 PostgreSQL 16 恢复库验证 `pg_restore`，核对迁移版本、关键表行数及历史用量，再演练 `0004 → 0005`；仅有备份文件或 `pg_restore --list` 不算恢复验证。未完成恢复演练则不升级现用库。
4. 通过后先迁移，再启动完整服务：

```powershell
docker compose @compose build app worker frontend mcp-server
docker compose @compose run --rm --no-deps app alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw '迁移失败，停止启动 App 和 Worker' }
docker compose @compose up -d
docker compose @compose ps
```

回退先停止 App/Worker；优先把升级前备份恢复到另一个确认的数据库，核对后切回原代码与连接目标。不要覆盖唯一原库。`0005` 如已有 `job_id=NULL` 的保留用量，会拒绝降级到 `0004`；不能删除这些账目来强行降级，须采用升级前备份并处理升级后的新增数据。

业务服务全部就绪后访问：产品 [3000](http://localhost:3000)、API [8000/docs](http://localhost:8000/docs)、Nginx [8087](http://localhost:8087)。停止且保留容器/卷：

```powershell
Set-Location D:\internship\viral-video-agent
docker compose -f docker-compose.yml -f docker-compose.local.yml stop
```

## 常见阻碍

| 现象 | 检查与处理 |
|---|---|
| 6379/80 被占用 | 使用本地覆盖文件，不停止 AI_school 的服务 |
| 页面出现 API 连接失败 | 独立前端不提供真实业务接口；需要安全准备好的后端或夹具回归 |
| 数据库认证失败 | 核对原有卷和角色，不能仅改 `.env` 假定旧密码已同步 |
| 报告缺少近期数据 | 默认未启用澄清；自由文本日期不保证经过结构化过滤，以报告边界为准 |
| pytest 无 PostgreSQL 结果 | 未设置专用 `PILOT_TEST_POSTGRES_URL`，不是迁移已验证 |
| ASR 环境不全 | 核对 `yt-dlp`、`ffmpeg`、转写配置；不要为测试偷偷调用外部服务 |
