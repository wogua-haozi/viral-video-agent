# vNext-C 本地演示说明

> 本说明保留候选确认体验流程；Windows 环境、端口、启动、停止和迁移以 [当前运行手册](local-development.md) 为准。不要直接对未备份的旧库启动 App。

vNext-C 默认关闭。本说明用于本地演示“模糊需求澄清 → TopicSpec → 候选账号确认 → 复用快照生成报告”的工程闭环；它不证明候选质量、模型准确率、稳定 Top 5、完整行业覆盖或生产可用性。

## 1. 准备配置

复制示例配置后，只在本机 `.env` 中填写运行所需值，不要把真实值提交到 Git：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

至少准备 PostgreSQL 密码、JWT Secret，以及真实业务运行需要的默认 LLM 配置。不要把 Key、Token、Cookie、账号或密码写入文档、截图或提交记录。

## 2. 开启 vNext-C

在本机 `.env` 中设置：

```dotenv
ENABLE_INTERACTIVE_BRIEF=true
ENABLE_CANDIDATE_CONFIRMATION=true
GRAPH_VERSION=v2
USE_FINETUNED_MODEL=false
```

`USE_FINETUNED_MODEL=false` 表示项目三模型保持关闭，Researcher 继续使用项目二默认模型路线。App 与 Worker 必须接收相同的 vNext 开关；Compose 已同时注入两边。

## 3. 启动与访问

```powershell
# 先完成当前运行手册中的数据库恢复演练和迁移
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
docker compose -f docker-compose.yml -f docker-compose.local.yml ps
```

访问：

- 产品：<http://localhost:3000>
- API 文档：<http://localhost:8000/docs>
- Nginx：<http://localhost:8087>

注册时可以使用本地测试邮箱格式和至少 8 位密码。系统只要求邮箱、密码和确认密码，不发送邮箱验证码。

## 4. 推荐体验流程

1. 输入简短、模糊主题，例如“相机”。
2. 回答最多两轮澄清。
3. 确认系统形成的结构化 TopicSpec 范围。
4. 等待任务进入候选账号确认页。
5. 对每个候选选择 `confirmed`、`excluded` 或 `uncertain`，且至少确认一个候选。
6. 提交后等待同一个 Job 从 PostgreSQL 快照恢复并生成报告。
7. 在任务事件、日志或测试证据中确认恢复阶段只运行 Analyst / Writer，没有重复执行 Brief Validator、Planner、Researcher、搜索、MCP、UAPI 或 ASR。

真实业务运行可能调用 DeepSeek 和公开数据入口，可能产生费用，也可能受到外部服务、风控或公开入口可用性影响。需要零费用演示时，应使用仓库既有 Fake/Mock 自动化或隔离 QA 数据，不要提交真实业务任务。

## 5. 关闭并回退

将本机 `.env` 恢复为：

```dotenv
ENABLE_INTERACTIVE_BRIEF=false
ENABLE_CANDIDATE_CONFIRMATION=false
USE_FINETUNED_MODEL=false
```

然后重建 App 与 Worker 进程：

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --force-recreate app worker
```

关闭后，Job 不进入 `waiting_user` 或 `waiting_candidate_confirmation`，继续使用原有完整分析流程。已有历史 Job、快照和报告不会因关闭开关而删除。

## 6. 停止服务

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml stop
```

不要在正式本地环境使用 `docker compose down -v`，也不要删除正式 PostgreSQL、Redis、ChromaDB 或 embedding cache 卷。
