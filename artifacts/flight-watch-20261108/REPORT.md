# 机票监控最小修复报告（2026-11-08）

执行身份：Cursor 云端代理，模型 Grok 4.7。本机没有已登录的 `codex` CLI，未执行 `codex exec`，也未安装或登录 Codex。未读取、复制或外发密钥。未调用 FlyAI 查价，未发 Server酱，未部署，未合并。

修复前 SHA：`4c4dee4a1dec6585c9a936ed3c50eea98eb6f5f0`。`flight-watch/config.json` 的日期、阈值、乘客和价格口径未改：提醒 ≤1500、理想 ≤1200、再降 ≥50，均为不含税票面。

## 证据命令

| 北京时间 | 命令 | exit |
| --- | --- | --- |
| 20:33:39 | `git rev-parse HEAD`；`command -v codex` 无输出 | 0 |
| 20:36:35–20:36:37 | `curl` 公开 `GET /api/fares` | 0，HTTP 200 |
| 20:36:35–20:36:37 | `gh run view 42479935911` 与最近 20 次 workflow 列表 | 0 |
| 20:37:07–20:37:11 | `gh run view --log` 三次运行（42479935911、42478753706、42477634801） | 0 |
| 20:42:10–20:42:11 | 相关 Python 单测；随后修正一处断言 | 首轮 1 |
| 20:42:10–20:42:11 | `node --test flight-watch/cloudflare-dispatch/worker.test.mjs` | 0，11/11 |
| 20:42:40 | 聚焦单测 56 项 | 0 |

公开快照摘要：`artifacts/flight-watch-20261108/public-fares-20261108T203635+0800.json`。抓取时间 2026-11-08 20:36:35 +0800。快照自身 `generated_at_bjt` 为 19:53:00，`most_recent_check_bjt` 为 19:52:56。6 组里只有 12-18 仍标 `priced_reference`，票面合计 2337，检查时间 18:52:48。这是未刷新的旧参考，不是新报价，也不是含税或可出票确认。其余 5 组为 incomplete，完整度 1/6。20:07 之后的状态包里 6 组都已不完整；看板没有跟上。

## 已核对的运行

- [42479935911](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/42479935911)：创建 12:22:23Z（北京 20:22:23），结论 success，SHA 同上。日志原文：`No itinerary due; skipped FlyAI. Workflow start is not a valid fare.` Node、FlyAI 安装、查价、看板发布全部 skipped。绿色只表示流程走完。
- [42478753706](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/42478753706)：北京 20:07。到期组为 12-26、12-18、12-09。同轮里既有 `cli_exit=0, api_status=1, api_message=搜索机票低价行业失败`，也有 `cli_exit=1, error=JSONDecodeError, api_status=null`。看板步骤原文：`Dashboard skipped: public snapshot is recent or no newer completed scan.`
- 19:52 那轮发布了 19:53 的快照。12-17 在 19:52 仍是接口 status=1，不是“无票”。其上次完整参考早于 30 小时，调度并没有把它饿死：高失败次数的间隔已退到 60 分钟。

20:22 全跳过是 15 分钟触发和 20 分钟失败重试错开，再加上其余组已退到 60 分钟。20:07 刚查过的组未满 20 分钟，19:52 那组未满 60 分钟。下一档 20:37 只会重试连续失败 1 次的 12-18。容量上限仍是每轮 3 组，最旧的到期组优先。GitHub `14,44` 备份最近几次相隔数小时，不能单独保证 60 分钟。用户间隔和日期没有改。

## 修复

1. 诊断分层：`http` / `cli` / `api` / `empty` / `parse`。文本脱敏并限长 120。上游失败、空结果和解析失败都仍然是数据缺口，不算无票。
2. 报价状态变化时立即允许发布看板，不再被 45 分钟去抖挡住。未变化的快照仍去抖。看板把陈旧价标成非当前，并写出最后成功与最近失败时间。工作流成功不等于取得报价。
3. 持续缺口不再被 `anomaly_episode_active` 永久吞掉。24 小时冷却和同日限制仍在。技能文档写的是 12 小时，代码原来是 24 小时；这次没有把 24 改成 12。提醒测试只 mock `send_wechat`。
4. Worker 派发截止从北京 2026-12-24 00:00 延到 2027-01-01 00:00，从而盖住 `stop_after` 2026-12-31，以及仍在出发当日的 12-26、12-27。GitHub 备份 cron 保留。12-28 起这些出发日已过，选择器不再查它们；2027-01-01 的返程不是单独的监控出发日。此改动在重新部署 Worker 前不影响线上。

## 回滚

未部署、未合并。若只合并了代码而尚未部署 Worker：`git revert` 该提交即可，线上 Worker 仍是旧截止时间。若已经部署 Worker：把 `worker.js` 的比较恢复为 `2026-12-24T00:00:00+08:00` 后再部署；`14,44` 备份不用删。配置文件无需回滚。

## 测试

聚焦 Python 单测 56 项，北京时间 20:42:40，exit 0。覆盖 JSON 解析、HTTP、CLI 空输出、API status=1、空结果、三次重试、单程不能凑往返、20:22 全跳过、20:37 公平补位、最旧组不被挤掉、12-24/12-27/12-28 日期边界、陈旧看板字段、45 分钟内的状态变化发布、告警冷却与恢复。Server酱入口被 mock，测试里另把 `urlopen` 设为断言失败。

Worker 测试 11 项，exit 0。12-24、12-27、12-31 23:52 仍派发；2027-01-01 00:00 北京时间停止。

`tests/test_fliggy_mark_failed.py` 在本仓库当前的 `flight-watch/fliggy-latest.json` 上失败：文件里当前总价已是 null，`last_valid` 为 1790.0，断言却要求两者相等。这次没有改该文件或 `mark_failed`。

## 仍需线上验证

合并和部署未做。上线后才能看到新的 `failure_layer`、状态变化后的看板，以及 12 月 24 日之后的 Worker 派发。那些都要等后续明确的发布指示。
