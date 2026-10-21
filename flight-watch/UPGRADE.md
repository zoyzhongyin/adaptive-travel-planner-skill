# 阿勒泰机票监控：调度可靠性升级

## 已应用（无需新的账号）

- GitHub 每15分钟尝试触发一次；它不是可靠的每15分钟定时器。官方文档承认延迟、丢弃。
- 一旦运行，优先补查上一次检测超过90分钟的出行日期，一次最多查3组，避免某个日期反复占用配额。
- 历史检查结果写入 flight-watch/state.json 的 last_scan_results、last_scan_bjt；未取得双程报价不作降价通知。
- 价格规则不变：两张单程直飞参考价加总不高于1500元时发送微信，1200元属于理想目标；不保证税费、行李和可出票。
- CI 单测：tests/test_flight_watch_batch.py。GitHub 触发记录不等于接口已返回完整机票价格。

## 更可靠的外部触发器（代码已准备，尚未部署）

代码：flight-watch/cloudflare-dispatch/worker.js
配置：flight-watch/cloudflare-dispatch/wrangler.toml

Cloudflare Workers 免费版支持 Cron Triggers。它可每15分钟通过 GitHub workflow_dispatch 启动本项目的监控工作流，避免依赖 GitHub 自己的 schedule 事件；GitHub Actions 执行与 FlyAI 查询仍可能延迟或报错。

需要用户自行操作：

1. 在 https://dash.cloudflare.com/ 登录自己的 Cloudflare 账户，创建一个 Worker，部署 worker.js。
2. 为该 Worker 添加 Cron Trigger：7,22,37,52 * * * *（UTC，每15分钟）。
3. 在 https://github.com/settings/personal-access-tokens 创建 fine-grained token：只选择 zoyzhongyin/adaptive-travel-planner-skill 这一个仓库，只授权 Actions: Read and write，设置到12月底前后的合理到期日。
4. 在 Cloudflare Worker 的 Settings → Variables and Secrets 新建 Secret，名称 GH_ACTIONS_TOKEN，值为 GitHub token。切勿发到 ChatGPT、提交到 GitHub 或放入公开变量。
5. 部署并验证 GitHub Actions 出现 event=workflow_dispatch 的任务记录。

原先 GitHub Actions 的 schedule 保留作备用，Cloudflare 定时触发和 GitHub 定时触发共用最近90分钟的每组行程查询冷却限制，防止多次重复抓取。Cloudflare 尚未连接/部署时，只有 GitHub 不可靠的内部定时任务在尝试运行。

## 排查

- flight-watch/state.json：查看 last_scan_results（每组日期的真实检查时间、去返程 API 状态、参考报价）。
- https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/workflows/altay-fare-watch.yml ：查看实际运行次数。
- 警惕 status=1、缺报价与工作流成功：这些都不证明当时无航班或机票价格超过阈值。
- Server酱 SendKey 已经在 GitHub Secret 内，不能复制到 Cloudflare；Cloudflare 的 GH_ACTIONS_TOKEN 是独立的 GitHub 定时调用权限。
