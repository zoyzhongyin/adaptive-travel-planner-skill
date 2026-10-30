# 阿勒泰机票独立数据源筛选｜2026-10-30

> 状态：已完成仓库/代码核查；**没有新来源的 TFU⇄AAT 真实采价通过验收**。给 Codex 的隔离实验说明。本文件不修改运行监控。

## 现状
- 用户现有 `zoyzhongyin/adaptive-travel-planner-skill`：FlyAI、低频同程备源、Cloudflare、GitHub Actions、Server酱、V2 看板已部署。详见 `CODEX_HANDOFF_2026-10-30.md`、`TONGCHENG_FALLBACK.md` 和 `RETURN_FLIGHT_DIAGNOSIS.md`。
- 2026-10-30 20:41 BJT 同程快照 `tongcheng-latest.json` 的 12/09—12/14 ¥1740 是**未核实是否含税或可出票**的参考价；不能触发自动购票。
- 飞猪 FlyAI `status=1` 属上游不明异常，不能确诊是设备指纹限制。

## 候选源码与核查
1. **不优先引入 [AI4MSE/FlyClaw](https://github.com/AI4MSE/FlyClaw)**：`sources/fliggy_mcp.py` 仍访问 `https://flyai.open.fliggy.com/mcp`，与现有 FlyAI 属同一上游，而且携带默认鉴权与设备 ID 逻辑。其 Google Flights/Skiplagged 可分别低频验证 TFU⇄AAT，但不因“聚合3源”就误算 3 个独立、有效的国内供应商。
2. **优先隔离测试**：[Yybrook/ctrip-ticket-crawler](https://github.com/Yybrook/ctrip-ticket-crawler)：项目研究报告显示普通 Chromium 浏览器网页会话下能读取携程 `batchSearch` JSON；但成功案例为 CKG→YTY，不能直接推断 TFU→AAT。浏览器内正常访问、仅监听页面自身响应，不在浏览器外复制站点签名。
3. **参考实现**：[zhanglong-ustc/flight-price-monitor](https://github.com/zhanglong-ustc/flight-price-monitor) 的携程/去哪儿/途牛适配；[LLL151/ticket](https://github.com/LLL151/ticket) 的数据源健康、舱位/余票/税费过滤；[ToLiveAndLove/flight-explore](https://github.com/ToLiveAndLove/flight-explore) 对携程 WAF、去哪儿设备挑战的实际限制说明。
4. **风险**：[LLL151/ticket](https://github.com/LLL151/ticket) 2026-10-27 才创建，未获阿勒泰实跑验证；`tuniu.py` 中提及设备指纹轮换，**不得直接移植规避频控手法**。长期稳定目标优先正常授权登录会话、低频和失败停手。

## Codex 最小实验任务
- P1 官网对照仍按原 `CODEX_HANDOFF_2026-10-30.md`；不得因新增数据源延误国航、川航、春秋官网核价。
- 在独立临时环境先测试 **2026-12-09 TFU→AAT** 与 **2026-12-14 AAT→TFU** 两个单程，1 成人经济舱，机场必须为 TFU/AAT、直飞。来源优先携程普通可访问网页。
- 需拿到：航班号、承运/实际执飞航司、准确日期/机场、经济舱、最低票价口径、税费、可售性/余票、行李政策字段、来源、北京时间时间戳。无法确认的字段标 unknown；**不把日历价、航班列表、HTTP 200 误报为已确认可出票价**。
- 如果两段通过，再试另十航段：12/08–13、12/17–22、12/18–23、12/26–31、12/27–2027/01/01。沿用原 6 组，不改排班、预算（理想 ¥1200、上限 ¥1500）和有效提醒。
- 如需本人登录，在本机正常浏览器中征得用户协助后登录，正常保存隔离浏览器 profile（不入库）；验证码/403/429 停止并记录，不进行设备 ID 轮换、IP/代理轮换、破解验证码、未授权会话复用。
- 实验成功后才考虑新增一个独立 `source` 模块，2 次/日或更低频，不影响原流程；先 PR + 单元测试 + 截止回归，不直接合并或发微信。失败则给出可复现错误与放弃依据。

## 验收标准
必须有阿勒泰路线两段日期准确、价格/航班号一致且来源可复查的真实查询结果；不能把候选 Skill 项目自身 README 声明当作实测。不得增加任何付费。
