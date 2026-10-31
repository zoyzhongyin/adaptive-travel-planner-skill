# 阿勒泰三家航司官网核验｜2026-10-31

## 核验范围
- 2026-12-09 去：成都天府 TFU→阿勒泰 AAT；2026-12-14 返：AAT→TFU；1 成人、直飞经济舱。
- 对比第三方页面实测：春秋 9C6685 12/09 ¥780；9C6686 12/14 ¥840；分段报价之和 ¥1620；**未核税费/库存/实际出票**。
- GitHub 单独实验分支 `flight-source-probe-20261030`；生产机票监控、Cloudflare、Server酱不变，无付费/购票。

## 官网证据
### 春秋 9C6685/9C6686
- 官网正式冬春时刻：[9C6685](https://flights.ch.com/flight-date/num-9C6685/)（周三 10:05 TFU→AAT）、[9C6686](https://flights.ch.com/flight-date/num-9C6686/)（周一 15:55 AAT→TFU）；匹配 12/09 和 12/14。
- 官网页面 https://www.ch.com/flights/ 能正常显示可交互城市/日期搜索入口；自动化城市选择器弹层未完成选定真实日期并跳转可支付明细；**因此没有取得官网含税可售报价**。不能把 OTA ¥1620 等同官网成交价。官网表单检查 [日志](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41154205335) 和交互 [日志](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41154428531)。
- 官网 [2026-10-30 公告](https://www.ch.com/News/d9a67efbf79b4ac08dafb77a2dd003dc.Html)：**2026-11-05 起购票**，800km 以上燃油附加费成人 **¥140/段**；具体以系统计算结果为准。该线路长于800公里。此前/此后票款差额不要靠臆断：目前可用国航 10-10 公告 ¥90/段，春秋 11-05 公告 ¥140/段；仍应核春秋当前票价实显税费。
- [春秋官方行李政策](https://flights.ch.com/general-conditions)：超惠飞无免费托运；优选飞分含/不含行李；含行李优选飞及尊享飞通常20kg（2026-03-29后出票航班政策），滑雪板按托运行李，滑雪板等长边最高180cm；以购票产品详情为准。
- 既有第三方报价不是最终应付价，不能用于真实预算上限报警。

### 川航 3U6573/3U6574
- 官网页面 https://flights.sichuanair.com/3uair/ibe/common/flightSearch.do HTTP 200，交互预订表单可见；**未提交完整日期/机场筛选，不存在已验证官网航班库存/含税票价**， [网页检查日志](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41154205335)。
- [川航官方免费托运](https://flights.sichuanair.com/common-problem/bell-service.html)：国内经济舱一般20kg，具体以票面行李额为准。
- [川航特殊行李规则](https://flights.sichuanair.com/baggage-service/baggage-restrictions.html)：滑雪用具可计入剩余免费托运额度；超过部分有独立按件计费档。
- 参考源前次 2026-12-09 川航 3U6573 在不同平台分别有 ¥820-¥860（税费不明）；不能称官方核价。

### 国航 CA2505/CA2506
- 官网 https://www.airchina.com.cn/ HTTP 200，出发/目的地/日期输入控件可见；**未提交完整航线日期且没有官方可售票价**，[检查日志](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41154205335)。
- [国航 2026-10-08 公告](https://www.airchina.com.cn/zh-CN/content/c/2026-10-08/30592.shtml)：10-10 起销售 800km 以上 ¥90/航段燃油附加，具体以购票系统为准。
- [国航特殊行李规则](https://webresource.airchina.com.cn/zh-CN/content/travel_info/preparing/luggage/check/bszsydgzqxzbjyp/)：滑雪用具只能作为托运行李运输，具体价额/数量再核。

## 运营结论
1. 春秋班期可由官网验证；三家**官网可购买最终含税票价均没有完成核验**。
2. 不启动同程/飞猪/携程来源的微信低价提醒；继续维持参考价看板，现有 FlyAI 提醒不改。
3. 用户最关键的成本为票面 + 机建 + 燃油 + 可能托运/雪具；若只租雪具不带雪板，可省该费用。
4. 若用户在真实本地浏览器实际核准12/09–14 春秋与川航官网最终应付，记录税费、托运行李和可售库存后再决定自动化与¥1500触发口径。不需任何账号/验证码提供给助手。
