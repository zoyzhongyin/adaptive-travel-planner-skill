# 阿勒泰机票监控：沿用现有 Worker 对接

现有资源：`zoyzhongyin/adaptive-travel-planner-skill`，Cloudflare Worker `altay-fare-cron`。
不创建新项目或替代 Worker。部署前必须确认原 Worker 存在，否则停止。

## 调度与查价

- Cloudflare 仍为 UTC `7,22,37,52 * * * *`。GitHub 自己的 schedule 只作备份，错开到 UTC `14,44 * * * *`，避免和 Cloudflare 在同一分钟排队。
- 两组触发共用 concurrency `altay-fare-watch`，不取消正在运行的任务。没有到期行程时不安装 FlyAI CLI。推送代码不再自动查价，避免用分支上的旧状态重复请求飞猪并覆盖 main 的监控记录。手动复查用 workflow_dispatch。
- Cloudflare 用 Worker Secret `GH_ACTIONS_TOKEN` 调用 `altay-fare-watch.yml`，输入 `dry_run=false`、`trigger_source=cloudflare`。
- 成功拿到往返参考价的日期，60 分钟内不再查询。报价数据缺口先隔 20 分钟重试，再 40 分钟，之后回到 60 分钟，避免失败被当成一次有效检查。一次最多补查 3 组。每一段航程最多 3 次官方 FlyAI 请求。
- `trigger_source` 只是诊断标签，任何有 Actions 写权限的调用者均可设置；需和 Cloudflare 日志交叉验证来源。
- Worker 请求限时 10 秒；网络异常、429、5xx 最多尝试 3 次，401/403/404/422 立即失败。模糊超时可能重复排队，冷却减少重复查询，不承诺严格只执行一次。
- Worker 日志仅记录事件、HTTP 状态、尝试次数、预定时间；不记录请求头、响应体或密钥。公网 HTTP 仍返回 404，不能触发工作流。
- 监控于北京时间 2026-12-23 结束；Worker 从 12-24 零点起不再 dispatch。
- FlyAI CLI 固定为 1.0.16。报价不全标为 `health=degraded`；连续 8 小时没有有效往返参考价标为 `health=anomaly`。绿色任务只表示脚本执行完毕，不表示获得有效价格。
- 正式提醒条件保持：两段直飞参考价合计不高于 1500 元，1200 元为理想价，按既有规则去重。参考价未核实税费、行李及可出票性。

## 一次性敏感配置（由用户在平台完成）

1. Cloudflare 打开**已有** `altay-fare-cron`，确认 Secret `GH_ACTIONS_TOKEN` 已配置。若没有或已失效，在 [GitHub fine-grained tokens](https://github.com/settings/personal-access-tokens) 创建仅限本仓库、`Actions: Read and write` 的 token；只在 Cloudflare Secret 输入框粘贴。不要发到聊天或提交到 Git。
2. 自动部署需要在 [GitHub Actions Secrets](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/settings/secrets/actions) 添加 `CLOUDFLARE_API_TOKEN`，以及在 Variables 添加 `CLOUDFLARE_ACCOUNT_ID`。Cloudflare API token 限定正确账户，权限为 Account / Workers Scripts / Edit；查看现有 Cron 需要 Workers Scripts 权限。不要使用 Global API Key。
3. 运行 [Deploy existing Altay Cloudflare scheduler](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/workflows/deploy-altay-cron.yml)。先读取现有 Worker 设置并检查 Secret 绑定，再测试并更新原 Worker；保留 dashboard 变量和已有 Secrets，配置 Cron 与日志。
4. 若不愿授予自动部署权限，可在 Cloudflare 已有 Worker 的 Edit code 中使用本目录 `worker.js`，保存部署，再检查 Cron、Observability 和 Secret。无需新建 Worker。

FlyAI 正式访问：当前默认 CLI 是体验模式，接口明确提示部分搜索受限。若已获得 [飞猪AI开放平台](https://flyai.open.fliggy.com/) 正式 API Key，请由用户直接在同一个 GitHub Secrets 页面添加 `FLYAI_API_KEY`；监控和诊断工作流均已接入 CLI 原生支持的同名环境变量。不要发到聊天。正式 key 是否解决目标日期报价缺失，仍须运行真实复查确认，不能预先保证。

Server酱 `SERVERCHAN_SENDKEY` 只留在既有 GitHub Secret，Worker 不需要它。
GitHub Secrets 不可读取；不得把 `GH_ACTIONS_TOKEN` 放入普通变量。

## 验证与排查

1. GitHub 的 `schedule` 运行记录证明内部定时事件实际发生；不能证明每 15 分钟稳定执行。
2. Cloudflare 下个 Cron 后，应在 Worker Logs 看到 `dispatch_accepted`、HTTP 204 和 scheduled_at，再在 Actions 看到对应 `workflow_dispatch · cloudflare`。204 仅表示已接受排队；还需查看工作流结果。Cron 更新可能需约 15 分钟传播。
3. 手动 Run workflow：`dry_run=false`，`force_scan=true`，`trigger_source=manual`，可进行一次真实 FlyAI 复查；正常定时运行不要启用 force_scan。`dry_run=true` 为模拟、不发通知、不修改真实告警状态。
4. 查看 `watch-batch.json` 的 health、每组去返程 API 状态、查询诊断及参考价。`status=1`、0 条、无完整双程价格都不能推断无航班。原始响应留在本次 artifact；先解决上游查询问题再宣称查价正常。
5. 手动运行 [ServerChan WeChat Push Test](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/workflows/flight-wechat-test.yml)，查看 `ServerChan API accepted` 并在微信确认收件。测试消息明确不是降价。
6. GitHub 401/403：检查 Worker Secret 的 token 有效期、选定仓库及 Actions 写权限；404：检查仓库访问权限；422：检查 main 分支上 workflow_dispatch 和 inputs 是否匹配。
7. 本地离线验证：`node flight-watch/cloudflare-dispatch/worker.test.mjs` 和 `python3 -m unittest tests.test_flight_fare_query tests.test_flight_price_watch tests.test_flight_watch_batch tests.test_flight_watch_health tests.test_serverchan_push -v`。

## 2026-10-27 报价数据缺口

最近 226 次不重复扫描里，去程 TFU→AAT 大约 65% 返回 status=0，返程 AAT→TFU 大约 24% 返回 status=0。失败体是 `{"status":1,"message":"搜索机票低价行业失败","data":null}`，通常 1 秒内返回，同一日期稍后又能成功。所以缺的是飞猪低价行业查询的单次结果，不是“这天没有航班”。

旧逻辑每段只请求一次，而且失败也写入 `last_scan_bjt`，之后 90 分钟不再查。只要返程撞上 status=1，去程即使已经成功也会被丢掉，往返总价无法计算。

本次只在官方 `search-flight` 上重试：先按价格排序，失败再改为直飞优先，仍失败再用「成都 / 阿勒泰」城市名并加上直飞筛选。报价会核对机场、出发日期、航班号和经停；`adultPrice` 不会被当成票价。只有一段直飞查到时，保留该段航班和参考价，往返合计仍标为未计算。没有加入第二个数据源。Google Flights 抓取不符合使用规则，SerpAPI 需要付费，航司和 OTA 页面也没有可用的免费正式接口。

2026-10-27 12:02（北京时间）在本分支实测：12 月 5–10 日两段都一次成功，直飞 9C6685 ¥848 + 9C6686 ¥909，参考价合计 ¥1757。12 月 14 日去程和返程、12 月 23 日返程在三种官方参数下都仍是 status=1。换排序和城市名不能绕过这一次持续失败；下一轮靠更短的缺口重试，而不是把失败当成查完。该次价格高于 1500 元，没有发微信。

`flight-watch/cloudflare-dispatch/worker.js` 没有修改。合并到 `main` 后，现有 Worker 继续触发同一条 workflow 即可，不需要重新部署 Cloudflare。只有以后改了 Worker 代码，才需要主人在 Cloudflare 授权后运行 Deploy existing Altay Cloudflare scheduler。

微信降价提醒现在包含出发/返回日期、航班号和直飞情况、两段参考价、往返合计、北京时间采集时间、订票入口，并写明税费、行李和雪具都未核实。某一组日期连续 8 小时没有有效往返参考价时，发送一条监控异常（12 小时内不重复）。微信失败时才让 GitHub Actions 失败，从而走邮件备用通道。

## 2026-10-22 北京时间实测记录

- [GitHub schedule](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/39694630452)：07:37 实际启动并查 3 组；六段 API 均 status=1。
- [微信测试](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/39697206032)：08:02 Server酱 API 接受测试消息；实际微信收件待用户确认。
- [强制真实复查](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/39697617997)：08:06 查询 12-05/10、12-14/19、12-23/28，六段均 `搜索机票低价行业失败`、0 条报价，批次降级。
- [FlyAI 对照诊断](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/39697724754)：成都→北京和 12-08 TFU→AAT 各返回 10 条；API 明示体验模式限制，其他日期/返程未获报价。证明服务可达，不证明当前监控行程可获得有效双程价。
- [部署预检](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/39697622685)：缺少 CLOUDFLARE_ACCOUNT_ID 与 CLOUDFLARE_API_TOKEN，部署前即停止；现有 Worker 未被此流程修改，Cloudflare 实际定时触发尚未验证。
- [GitHub CI](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/39697598419)：全部离线 Python 测试和 release checks 通过。Worker 9 项离线测试也通过。
