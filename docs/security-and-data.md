# 权限、数据与 Evidence 边界

## 身份与会话

- 邮箱唯一，密码使用 Argon2
- JWT 只保存在 HttpOnly Cookie，不进入 localStorage
- `SameSite=Lax`；`APP_ENV=production` 时自动启用 `Secure`
- 生产环境仍使用默认开发 `JWT_SECRET` 时拒绝启动；当前代码不验证任意自定义 Secret 的强度，部署者须配置足够随机的 Secret
- Next.js middleware 做页面级拦截，FastAPI 对每个资源再次验证身份与所有者

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

- 只接受公开 B 站 HTTPS URL，并在下载前执行主机白名单校验，避免任意 URL/SSRF
- 用户不上传音频；Worker 在任务内临时提取并压缩，临时目录退出时自动删除
- 原始音频、Base64 Data URL 和 API Key 不写入 PostgreSQL，也不得进入应用日志
- PostgreSQL 只保存必要的转写文本、来源 URL、provider、model 和 `audio_hash`
- MCP 工具错误、非结构化字符串及缺少文本或来源的转写结果不会保存为 Evidence
- Redis 只缓存转写结果，不缓存原始音频；BVID 与 `audio_hash` 两类键的 TTL 均为 30 天
- ASR 失败时降级为元数据分析，报告不得声称已经读取视频口播或脚本内容
