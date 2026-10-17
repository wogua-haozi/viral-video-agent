# 2026-07-15 前端验收记录

> 历史验收档案：结果和旧版截图仅对应标题日期的版本，不代表本轮本机验收或当前界面。当前状态见 [项目状态](project-status.md)。

## 结论

前端视觉系统、核心页面和共享组件已完成升级。ESLint、TypeScript 与 Next.js production build 通过；真实 Chromium 会话在桌面、平板和手机尺寸完成页面与交互检查，最终干净会话控制台为 0 error / 0 warning，三个目标宽度均未发现页面级横向溢出。

这是一轮本地前端与浏览器验收，不代表产品已经部署，也不代表存在真实用户、线上完成率或线上性能数据。

## 自动检查

| 检查 | 命令 | 结果 |
|---|---|---|
| ESLint | `npm run lint` | 通过，无 warning / error |
| TypeScript | `npx tsc --noEmit` | 通过 |
| Production build | `npm run build` | 通过 |
| 依赖 | `frontend/package.json`、`package-lock.json` | 未修改，没有新增 UI 或动画依赖 |

## 浏览器范围

使用 Chromium 检查以下视口：

- 1440×900：公共首页、Dashboard、报告详情与长内容布局
- 1024×768：公共页、工作台、新建任务与响应式分栏
- 390×844：首页、认证页、工作台菜单、任务、报告、分享与长内容移动布局

覆盖页面与组件：

- 首页 `/`、登录 `/login`、注册 `/register`
- 示例列表 `/examples`、示例详情 `/examples/[id]`
- Dashboard `/dashboard`、新建分析 `/jobs/new`、任务进度 `/jobs/[id]`
- 报告详情 `/reports/[id]`、历史任务 `/history`、设置 `/settings`
- 公开分享 `/share/[token]`、旧报告路径 `/report/[id]` 的兼容跳转
- Header、移动导航、AppShell、Modal、Toast、状态标签、Evidence、结构化结论、反馈与分享组件
- loading、empty、error、partial、cancelled 等页面状态，以及 ASR 可用、不可用与降级提示

## 数据与环境边界

| 验证类型 | 实际使用 |
|---|---|
| 本地真实后端 | health、注册、登录、Dashboard、新建任务表单、历史与设置读取 |
| 确定性浏览器网络夹具 | 任务进度、报告、Evidence、partial 状态、分享、Modal 和长内容压力场景 |
| 未执行 | 未提交新的付费 LLM / ASR 分析任务 |

网络夹具只用于稳定复现视觉状态，不应被描述为真实任务成功率或真实业务数据。

## 交互与可访问性

- 浅色与深色主题均完成检查，Logo、正文、边界、状态与焦点在两种主题下可辨认。
- 桌面侧栏、公共移动导航和工作台移动菜单可正常操作。
- 表单有可见标签和靠近字段的错误反馈；图标按钮具有可访问名称。
- Modal 的 Escape、焦点管理、Tab 循环、遮罩关闭和关闭后焦点恢复已检查。
- 报告“复制”按钮已在真实浏览器确认显示 Toast：`报告已复制`。
- 键盘 Tab 顺序与跳到主要内容入口已检查。
- `prefers-reduced-motion` 已确认关闭主要动画和顺滑滚动。
- 长中文标题、长 URL、长表格、长报告和多条 Evidence 不造成页面级横向溢出。

## 视觉与输出检查

- 1440×900、1024×768、390×844 均未发现页面级横向溢出。
- 最终 1440×900 报告会话：`scrollWidth=1425`、`clientWidth=1425`。
- 最终干净浏览器会话：控制台 0 error / 0 warning。
- 浏览器打印/PDF 已实际生成并渲染检查；报告卡片未被横向裁切，章节标题未成为页尾孤行。临时 PDF 不作为正式产物保留。
- 已检查浅色、深色、移动端、长内容和减少动态效果场景；未发现明显布局跳动。

## 正式截图

- `output/playwright/home-desktop.png`
- `output/playwright/home-mobile.png`
- `output/playwright/dashboard-desktop.png`
- `output/playwright/report-desktop.png`

这些截图由 README 或本验收文档引用；调试截图、重复 `*-new.png`、临时 PDF 和 Playwright 会话文件不纳入提交。

## 尚未验证或不能外推

- 项目尚未部署，没有真实用户、真实线上流量、转化率或前端性能监控数据。
- 本轮没有重新提交真实付费 LLM / ASR 任务，任务进度、报告和分享的视觉压力状态包含网络夹具。
- 没有开展正式用户研究、可用性访谈或完整屏幕阅读器兼容矩阵。
- 浏览器验收以 Chromium 为主，不能等同 Safari、Firefox 和所有移动设备的完整兼容性结论。
