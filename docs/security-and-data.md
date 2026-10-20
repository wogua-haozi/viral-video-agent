# 权限、数据与 Evidence 边界

## 身份与会话

- 邮箱唯一，密码使用 Argon2
- JWT 只保存在 HttpOnly Cookie，不进入 localStorage
- `SameSite=Lax`；`APP_ENV=production` 时自动启用 `Secure`
- 生产环境仍使用默认开发 `JWT_SECRET` 时拒绝启动；当前代码不验证任意自定义 Secret 的强度，部署者须配置足够随机的 Secret
- Next.js middleware 做页面级拦截，FastAPI 对每个资源再次验证身份与所有者
- `REGISTRATION_ENABLED` 默认 `true`，受控试用配置固定 `false`；注册 API 返回 `403 REGISTRATION_CLOSED`，仅通过本机交互命令人工创建账号。重复尝试注册不会创建用户或获得会话/额度

## 试用入口与网络边界

- 基础/本地 Compose 的调试端口仅绑定 `127.0.0.1`，不得直接作为公网配置
- `docker-compose.pilot.yml` 必须最后合并，使用 `!reset []` 移除 Redis、Chroma、MCP、App、Frontend、Nginx 的宿主端口；数据库本来不发布端口
- 仅 Caddy 入口发布 80/443，HTTPS 下整站 Basic Auth 覆盖页面、静态资源和全部 API，不能通过应用端口绕过入口；入口凭证从转发头移除，应用会话继续独立校验
- 分享页在受控试用配置也需要入口认证；应用退出不会清除浏览器缓存的入口密码。限制适用于受邀试用者，不是完整邀请/订阅系统
- 域名、证书、防火墙、旧数据库恢复和真实登录需在确定环境验收，本轮未部署。配置和人工账号命令见 [Windows 手册](local-development.md#受控-https-试用入口仅配置本轮不部署)

## 所有权

以下资源均按认证用户 ID 查询，不接受客户端传入 `user_id`：

- analysis jobs 与 job events
- reports 与 evidence items
- feedback 与 usage
- share links

非所有者访问任务返回 `JOB_NOT_FOUND`，避免泄露资源是否存在。公开分享只接受高熵 token 的 SHA-256 哈希匹配。

## 分享边界

- token 使用 `secrets.token_urlsafe(32)`，数据库只保存哈希
- 支持 1–90 天过期与用户撤销
- 公开响应清空 `model_info` 和 `usage`
- 不展示用户信息、成本、内部执行轨迹或 Worker 错误详情
- 公开接口只读

## Evidence 完整性

Evidence ID 来自工具名与稳定来源身份的 SHA-256 摘要。数据库对 `(job_id, evidence_id)` 建唯一约束。

发布前校验：

1. Claim 引用必须存在。
2. Observation 至少有一条 Evidence。
3. 报告正文不能出现未知 Evidence ID。
4. 数据附录由程序生成。

## 数据与秘密

- `.env`、JWT Secret、数据库密码和 API Key 不提交
- 后端 Provider 凭证必须具有应用后端/自动化调用授权；不得把仅限交互式编程工具的 Token Plan Key 接入 Worker
- 数据库使用 Compose 命名卷
- 备份如需落盘，只允许 `backups/`，该目录默认忽略内容
- 音频、WAV/MP3 与 `tmp/` 均忽略提交并在处理后删除

## ASR 音频与缓存

- 下载和缓存查找前均校验 HTTPS URL：精确 `bilibili.com`、带点子域或 `b23.tv`，拒绝 `evilbilibili.com`、其他后缀、URL 凭证和非默认端口。这是输入主机边界，不替代对上游重定向与下载器行为的完整 SSRF 防护审计
- 用户不上传音频；Worker 在任务内临时提取并压缩，临时目录退出时自动删除
- yt-dlp/FFmpeg 在独立子进程组/树中运行；取消、总超时和重复取消均等待终止与临时目录清理。自动测试使用长运行进程夹具，真实媒体处理仍待用户验收
- MCP 路径显式发送标准取消通知；服务端实际清理后才发送仅含请求 ID/完成标记的通知。客户端最多等待 3 秒；网络中断或旧服务未确认时记录脱敏告警，不宣称远端已清理，也不会因取消再启动本地回退。应同时更新 App/Worker/MCP 镜像，不能只换客户端
- 原始音频、Base64 Data URL 和 API Key 不写入 PostgreSQL，也不得进入应用日志
- PostgreSQL 只保存必要的转写文本、来源 URL、provider、model 和 `audio_hash`
- MCP 工具错误、非结构化字符串及缺少文本或来源的转写结果不会保存为 Evidence
- Redis 只缓存转写结果，不缓存原始音频；BVID 与 `audio_hash` 两类键的 TTL 均为 30 天
- MCP 容器明确连接内部 Redis。缓存错误不阻断分析，连接/读写有超时；日志只含操作和异常类型，不含连接串、音频、Key 或 URL
- ASR 失败时降级为元数据分析，报告不得声称已经读取视频口播或脚本内容
