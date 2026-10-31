# Windows 本地运行与数据保护

当前状态、验收和唯一任务清单见 [项目状态](project-status.md)。工作目录始终为 `D:\internship\viral-video-agent`。工程补修的既有只读复审结论保留；10/31 用户已通过前端视觉验收并授权本轮收尾与标准 Git 推送到 `wogua-haozi/viral-video-agent`。完成后等待反馈；后续推送仍需明确确认批次，没有自动部署或收费调用。

10/20 工程验收和 10/31 视觉验收后均按授权清理本项目可重建产物；当前 `.venv`、`frontend/node_modules`、`frontend/.next` 不保留。恢复宿主开发时按下方命令重建，不使用已删除的解释器或旧构建。Docker 不依赖这些宿主目录，仍按原 Compose 构建、拉取和启动；现用库安全要求不变。清理记录统一见 [项目状态](project-status.md)，全部数据卷和共享环境保留。

本轮完成后等待用户真实使用反馈，不自动追加优化。完整业务/报告质量仍需用户本地验收，通过后才开始少量创作者试用；MCP 请求、取消与关停的 Docker 实际验收继续保留。本文的部署命令是后续操作说明，本轮没有运行完整业务栈。

当前已清理预览依赖和构建。只看前端可先按下面的开发方式恢复；生产预览须先安装依赖并重新构建：

## 前端预览与开发

PowerShell：

```powershell
Set-Location D:\internship\viral-video-agent\frontend
# 清理后首次运行需要恢复依赖；安装完成后无需每次重复
npm ci
npm run dev:local
```

浏览 [首页](http://127.0.0.1:3007) 与 [示例](http://127.0.0.1:3007/examples)。停止按 `Ctrl+C`。独立前端只提供公共页预览，注册、工作台、提交任务需要后端；浏览器回归里的工作台和报告使用明确的虚构接口夹具。

```powershell
Set-Location D:\internship\viral-video-agent\frontend
npm ci
if ($LASTEXITCODE -ne 0) { throw '前端依赖恢复失败，停止构建' }
npm run lint
if ($LASTEXITCODE -ne 0) { throw '前端检查失败，停止构建' }
npm run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败，停止启动旧构建' }
npm run preview
```

本机已实际使用生产构建运行回归。由于项目保留 Docker 的 `output: standalone` 设置，`next start` 会打印提示；本地服务可启动，Docker 正式入口是镜像中的 `node server.js`。

Windows PowerShell 使用上面的固定参数脚本，避免 `npm run ... -- --hostname ...` 转发时丢失参数、把 IP 当作项目目录。已有构建直接 `npm run preview`；修改源码后先重新 build。`dev:local` 用于需要热更新的开发预览，两者均在 `127.0.0.1:3007`，不要同时启动。

另一终端运行既有浏览器回归（不调用业务后端）：

```powershell
Set-Location D:\internship\viral-video-agent\frontend
# 本机已有的 Playwright；其他电脑改为自身安装目录
$env:VVA_PLAYWRIGHT_PACKAGE='D:\srp_project\AI_school\report-web\node_modules\playwright-core'
$env:VVA_BROWSER_EXECUTABLE='C:\Users\0\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe'
$env:VVA_OUTPUT_DIR=Join-Path 'D:\internship\viral-video-agent\backups' ('browser-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
if (Test-Path -LiteralPath $env:VVA_OUTPUT_DIR) { throw '验收目录已存在，请换新目录以保留历史结果' }
$env:VVA_BASE_URL='http://127.0.0.1:3007'
node tests/creator-pilot.cjs
```

脚本默认输出 `output/soft-ui-20261018`；复跑时务必像上方一样指定新的 `VVA_OUTPUT_DIR`，避免覆盖历史验收。演示数据不代表实际视频、账号或产品质量。当前 README 图片仍准确反映保留的界面；新回归证据和历史图片分开。

## 2026-10-18 前端产物清理（历史）

自动审批曾拒绝递归删除命令；用户随后执行了两条精确清理命令。2026-10-18 已复核两处前端产物不存在，清理前约 435 MiB，回执在 `backups/soft-ui-20261018/manual-cleanup-confirmation.json`。这是当时记录；10/20 为工程验证重建过环境，之后按新授权再次清理，详情见当前状态页。

## 后端夹具测试与依赖

清理后先恢复本项目独立虚拟环境（不继承全局包）：

```powershell
Set-Location D:\internship\viral-video-agent
if (-not (Test-Path .venv\Scripts\python.exe)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

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

同时覆盖新队列恢复回归：

```powershell
$env:PILOT_TEST_POSTGRES_URL='<dedicated-test-database-url>'
.\.venv\Scripts\python.exe -m pytest -q tests/test_creator_pilot_postgres.py tests/test_worker_dispatch_postgres.py
# 可选：专用隔离 Redis；只操作随机转写键和随机 Arq 队列，不使用业务 Redis
$env:PILOT_TEST_REDIS_URL='<dedicated-test-redis-url>'
.\.venv\Scripts\python.exe -m pytest -q tests/test_transcript_runtime.py tests/test_worker_dispatch_postgres.py
Remove-Item Env:\PILOT_TEST_REDIS_URL
Remove-Item Env:\PILOT_TEST_POSTGRES_URL
```

PostgreSQL 用例只迁移随机 schema 并清理自身 schema。完整队列集成需同时有两个专用 URL；不能把业务连接串填进测试变量。无真实收费调用。

2026-10-17 继承全局包的旧 `.venv` 已退役。10/20 验收时创建过不继承全局包的新环境并完成 `pip check`，现已清理；当时版本快照保存在忽略目录 `backups/pilot-hardening-20261020/python-packages.json`，不是锁文件。Python 按原版本范围安装，前端按锁文件 `npm ci`，Docker 部分标签仍会变动，不宣称逐字节复现。清理前安装/工程测试的历史结果保留，完整 Docker 业务栈仍待用户验收。宿主机深度分析需要 PATH 中的 `ffmpeg`；Dockerfile 已声明安装。自动取消测试使用会持续运行的本地子进程夹具，不能冒充真实视频下载/FFmpeg 内容处理验收。

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
if ($LASTEXITCODE -ne 0) { throw '未能确认停止业务写入，停止升级' }
docker compose @compose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw '已确认的 PostgreSQL 未就绪，停止备份' }
$prePilotBackup=Join-Path 'backups' ('vva-pre-pilot-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.dump')
if (Test-Path -LiteralPath $prePilotBackup) { throw '备份目标已存在，禁止覆盖' }
New-Item -ItemType Directory -Path backups -Force | Out-Null
docker compose @compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/vva-pre-pilot.dump'
if ($LASTEXITCODE -ne 0) { throw '数据库备份失败，停止升级' }
docker compose @compose cp postgres:/tmp/vva-pre-pilot.dump $prePilotBackup
if ($LASTEXITCODE -ne 0) { throw '备份复制失败，停止升级' }
Get-FileHash -LiteralPath $prePilotBackup -Algorithm SHA256
```

3. 在独立的 PostgreSQL 16 恢复库验证 `pg_restore`，核对迁移版本、关键表行数及历史用量，再演练 `0004 → 0005`；仅有备份文件或 `pg_restore --list` 不算恢复验证。未完成恢复演练则不升级现用库。
4. 通过后先迁移，再启动完整服务：

```powershell
docker compose @compose build app worker frontend mcp-server
if ($LASTEXITCODE -ne 0) { throw '镜像构建失败，停止迁移和启动' }
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

基础/本地配置仅用于本机开发，调试端口都绑定 `127.0.0.1`。它没有提供公网入口限制，不能拿来直接对外试用。

## 受控 HTTPS 试用入口（仅配置，本轮不部署）

采用 Caddy 的整站 HTTPS + Basic Auth，并在 App 关闭自助注册、人工开通账号。入口限制覆盖页面、静态资源、API 与分享页；试用分享链接同样要求入口密码。应用账号仍通过 HttpOnly Cookie 验证所有权，不共用账号。入口密码共享给受邀者后，退出应用不会退出浏览器保存的 Basic Auth；撤回整站访问需更换入口密码并重建入口。

准备独立域名、DNS 和可用的 80/443；本机 80 已被其他项目占用，不能停止它来试部署。公网证书、DNS、网络防火墙与真实登录链路留到确认的试用环境验收。配置模板只收域名，不要加 `http://`。Caddy 自动 HTTPS 的要求见 [官方说明](https://caddyserver.com/docs/automatic-https)，整站认证见 [basic_auth](https://caddyserver.com/docs/caddyfile/directives/basic_auth)。

```powershell
Set-Location D:\internship\viral-video-agent
if (-not (Test-Path .env.pilot)) { Copy-Item deploy/pilot.env.example .env.pilot }
# 交互输入入口密码，得到 bcrypt hash；不要将明文密码写入命令或仓库
docker run --rm -it caddy:2-alpine caddy hash-password
```

仅在本机编辑被忽略的 `.env.pilot`：设置 `PILOT_DOMAIN`、`PILOT_GATE_USER`、`PILOT_GATE_HASH`、原库匹配的 `POSTGRES_PASSWORD` 与随机 `JWT_SECRET`；hash 用单引号包住，保留 `$`。旧库密码含 URL 特殊字符时设置 `PILOT_DATABASE_URL`，连接地址中的密码须 URL 编码；不要通过改 `.env` 密码假装完成旧库密码迁移。真实 `.env` 不覆盖。

```powershell
$pilot=@('--env-file','.env','--env-file','.env.pilot','-f','docker-compose.yml','-f','docker-compose.pilot.yml')
docker compose @pilot config --quiet
```

试用文件必须最后合并。即使前面加了 `docker-compose.local.yml`，`!reset []` 也会清空 Redis/Chroma/MCP/App/Frontend/Nginx 的宿主端口；**只有 `pilot-entry` 发布 80/443**，不能再加其他覆盖把端口重新打开。普通 Compose 的端口会追加，因此使用支持 `!reset` 的新版 Compose；本机 v5.1.0 已实际验证两种合并顺序。见 [Compose 合并规则](https://docs.docker.com/reference/compose-file/merge/)。检查配置不要把完整输出贴到日志或聊天，可能包含真实凭证。

完成旧库备份/恢复演练、只读复审与部署环境确认后才运行：

```powershell
docker compose @pilot build app worker frontend mcp-server
if ($LASTEXITCODE -ne 0) { throw '镜像构建失败，停止迁移和启动' }
docker compose @pilot up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw '已确认的 PostgreSQL 未就绪，停止迁移' }
docker compose @pilot run --rm --no-deps app alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw '迁移失败，停止启动' }
docker compose @pilot up -d
# 在交互终端中人工开通账号，密码不回显；不放入 argv / 环境变量 / 日志
docker compose @pilot exec app python -m src.manage_users creator@example.com
# 停止时保留数据与证书卷
docker compose @pilot stop
```

PostgreSQL 及内部依赖应先按前节启动并确认目标，迁移命令不会自动选择安全数据库。注册 API 在试用配置返回 `403 REGISTRATION_CLOSED`；注册页仍可打开，会明确提示联系管理员，不能靠重复注册获取额度。本地开发默认保留 `REGISTRATION_ENABLED=true`。手工账号脚本只创建账号，不迁移数据库、不重置已有账号密码；无交互终端时拒绝回显密码。

## 网页复审后的最短真实任务验收

本轮仅完成工程验证；下面由用户确认费用和样本范围后执行，不把夹具结果当真实报告质量。

1. 按前节安全恢复数据库并启动本地栈，核对登录、工作台、用量与队列/知识库连通；默认模型和实验开关保持原值。若试受控入口，核对无密码访问页面/API/分享均为 401、自助注册为 403、人工账号可登录。
2. 提交一条明确的 B 站标准研究，例如自己的赛道、受众、希望解决的创作问题与样本范围。记录任务 ID、起止时间、执行版本和提交前额度；刷新/重提未决请求应回到同一任务，额度只增加一次，等待页跟踪到终态。普通文字日期不保证被结构化过滤，以报告披露为准。
3. 逐条打开报告来源，抽查关键观察与建议能否由样本支持，核对发布时间/采集时间、样本量、缺失值/真实零值、部分结果和局限。引用存在只证明结构合法；需要用户判断是否可信、可执行，不能用模型自评分替代。
4. 完成 Markdown 导出、打印/PDF、创建/打开/撤销分享及提交反馈；另一应用账号不可读私有任务/报告。记录反馈是否保存；记录 token、ASR 秒数、估算费用和供应商账单，响应丢失可能导致费用不可观测，两者不必相等。
5. 在另一个明确的小预算任务中测试运行中取消，等待停止中结束，确认下载/转码子进程与临时音频已清理，用量仍保留；失败任务可有限重试。重试响应先断连时，即使先读到相同执行版本的旧失败/取消状态，当前任务页也应继续核对，发现新版本后跟踪到终态；20 秒仍无确认则提示“重试结果仍未确认”，重试按钮禁用，只用“继续核对重试结果”或“重新连接”恢复只读核对，不再次 POST。范围修订 503/响应丢失后在**同一标签页刷新**再提交同一内容，任务/额度只新增一次；不要关标签页或清除站点存储来验证此保证。
6. 若准备开放深度模式，再选少量有权分析的公开视频验证真实下载、FFmpeg、ASR及相同视频缓存复用；第二次不应增加 ASR 用量。总超时/中断恢复如需实测，在独立验收环境短时配置并观察，不能对现用业务库/其他用户任务断服务。保留任务 ID、失败原因、恢复事件和耗时。

只有真实任务完成、主要来源可核对、建议可执行且取消/失败路径可靠后，才邀请少量创作者；否则把明确复现与报告问题回填 [唯一任务清单](project-status.md#当前任务与进入试用的门槛)。P0-C/vNext-C 的冻结历史不因本轮结果改变。

## 常见阻碍

| 现象 | 检查与处理 |
|---|---|
| 6379/80 被占用 | 使用本地覆盖文件，不停止 AI_school 的服务 |
| 页面出现 API 连接失败 | 独立前端不提供真实业务接口；需要安全准备好的后端或夹具回归 |
| 数据库认证失败 | 核对原有卷和角色，不能仅改 `.env` 假定旧密码已同步 |
| 报告缺少近期数据 | 默认未启用澄清；自由文本日期不保证经过结构化过滤，以报告边界为准 |
| pytest 无 PostgreSQL 结果 | 未设置专用 `PILOT_TEST_POSTGRES_URL`，不是迁移已验证 |
| ASR 环境不全 | 核对 `yt-dlp`、`ffmpeg`、转写配置；不要为测试偷偷调用外部服务 |
| `MCP cancellation cleanup not confirmed` | 客户端 3 秒内未收到远端实际清理完成通知；核对 MCP 连通性和 App/Worker/MCP 镜像是否同步，检查远端进程与临时目录。该告警不代表清理已经完成，取消不会触发本地重复下载 |
| MCP SSE 关闭后 ASGI 二次响应日志 | 独立夹具环境 MCP 1.30.0 / Starlette 1.9.0 / uvicorn 0.54.0 已观察到，夹具中的资源清理与 ACK 通过不代表该日志无害。仍须在完整 Docker 栈实测正常请求、取消与关停；有影响先解决兼容性再开放试用，不在其他项目全局环境中升级 |
