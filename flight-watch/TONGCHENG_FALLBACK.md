# 阿勒泰 · 同程备用报价来源（2026-10-30）

## 背景

现有 FlyAI 接口在 TFU ⇄ AAT 多个日期持续返回业务状态 `1`，不能仅凭定时任务成功认为获取了有效票价。用户重点关注国航（CA）、川航（3U）、春秋（9C）。

## 真实试验与判断

- [公开页面探针](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41054577604)：12月9日/14日及18日/23日同程页面均 HTTP 200，包含 `window.__NUXT__.state.book1.flightLists`。
- [隔离 Chromium 双程验证](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41054840937)：12月9日去程与12月14日返程，各3个航班通过航班号、机场、日期和直飞校验；CA/3U/9C 各1。
- [六组完整比对](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41055137287)：12个航段均成功返回精确日期、TFU/AAT 机场的直飞航班信息，最低**未核实网页参考价**如下。

| 去程—返程 | 两段最低来源 | 参考合计 |
|---|---|---:|
| 12月08—13日 | 春秋 + 春秋 | ¥1870 |
| 12月09—14日 | 春秋 + 春秋 | ¥1740 |
| 12月17—22日 | 春秋 + 川航 | ¥2210 |
| 12月18—23日 | 川航 + 春秋 | ¥2210 |
| 12月26—31日 | 国航 + 春秋 | ¥2750 |
| 12月27日—2027年1月01日 | 春秋 + 春秋 | ¥2570 |

这些结果**不是含税可出票价格，也没有验证经济舱库存、托运行李或雪具费用**。不能拿来自动购买或宣称已满足预算。可能有延迟、缓存或数据源内容变化。

春秋官网也能正常打开这两个方向的预订网页，但纯静态 HTTP HTML 没有可验证的机票价格。开源 SpringAirlines-Monitor 只对部分日本航线声称验证过实时数据，没有证明 TFU⇄AAT 价格可用。

## 本次实现

- `scripts/tongcheng_snapshot.py`：每次最多6组往返、12个只读公开网页，用正常 Chromium 加载；直接读取网页已呈现的 `window.__NUXT__` 数据，不把第三方 JS 原文拿到 Node/Python 中 `eval`。
- **严格数据过滤**：仅 TFU⇄AAT，5晚、exact date、航班号 9C/CA/3U、`airCompanyCode` 与航班号一致、`stopNum=0`、金额为有限正数。空数据、日期或机场不符一律记作缺口，不当作无航班。
- `.github/workflows/tongcheng-supplement.yml`：北京每天08:40/20:40两次低频采集，不用额外 API Key，不产生付费云服务器费用。写入私有 `flight-watch/tongcheng-latest.json`，**不会发送微信或更改原 FlyAI 查询状态**。
- `scripts/build_fare_dashboard.py`：仅白名单脱敏的备用报价字段可进入原 Worker `/api/fares`，保留各来源和采样时间；旧数据不能当作当前价格。
- `flight-watch/dashboard/index.html`：优先展示可用的较近参考价，展开每组可看国航、川航、春秋各自单程价格和来源；明确同程报价没有核税费和不会触发微信。
- `tests/test_tongcheng_snapshot.py`、`tests/test_tongcheng_dashboard.py`：测试错机场/日期/中转/航司金额过滤、历史数据与实时数据隔离、公有数据脱敏及网页 JS 语法。
- 不修改现有飞猪查价频率、微信阈值、Secret、Cloudflare Cron 和购票权限。原有价达标通知逻辑照常。

## 限制与后续 Codex 工作

1. 通过普通网页（非绕过/破解）核对 **国航、川航、春秋官网**在 TFU/AAT 指定日期对外展示的最低价、舱位、税费和托运行李说明。不存在合法稳定公开价格 API 时不要臆造或调用私有接口。
2. 对比同程价格字段 `flightPrice` 与实际预订页面可售库存、税费的关系；若存在重大差异，应标注为仅趋势观察，不参与微信。
3. 同程候选报价低于 ¥1500 时，目前只展示在看板；若要新增微信候选通知，须先确认价格准确性，设计**跨来源、跨窗口去重和免费额度保护**，并通过端到端模拟价测试，不能直接复用 FlyAI 的状态或伪称税费已验证。
4. 若官网出现风控、验证码、403/429，应明确标记数据缺口并停止该次抓取，不实施验证码绕过/伪装登录/匿名代理轮换。
5. 12月正式排班出炉后重新验证6组候选日期；当前为暂定窗口，勿自动购买。

## 技术边界

正式监控代码保持私有；公开 Worker 仅脱敏展示，不能泄露 Server酱 Key、Cloudflare/GitHub/FlyAI token、私人日历备注或原始 HTML。GitHub Actions 的自动化成功不代表报价可用。
