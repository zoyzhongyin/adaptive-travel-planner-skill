# 2026-10-29 阿勒泰返程缺报价调查与缓解

## 证据（不等于“没有航班”）

- 现有监控：AAT→TFU 航段常出现 status=1，message=“搜索机票低价行业失败”，CLI exit=0，itemList=0。部分 TFU→AAT 去程也同样失败，所以并非仅返程方向问题。
- [对照实验 A](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/40862838541)：2026-12-14 的 AAT→TFU，价格升序+经济舱、有/无舱位、推荐排序、限定 9C6686 均 status=0 且有票价；但同轮 2026-12-23 返程及 12-09 去程出现 status=1。
- [对照实验 B](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/40863191910)：2026-12-23 AAT→TFU 换 sort_type=2 或只限定 9C6686 仍 status=1；2026-12-31 限定 9C6686 同样 status=1，而 12-14 AAT→TFU 成功。
- [区间实验](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/40863565851)：AAT→TFU 2026-12-22～23 及 12-30～31 两组两日区间搜索也均 status=1。
- 同日早先自动工作流 [12:52 北京时间](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/40820161253) 成功查到 12-14 返回航班 9C6686 ¥838；[13:07 北京时间](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/40821555268) 成功查到 12-23 返回航班 9C6686 ¥1038。价格为原始 ticketPrice，未验证含税/库存/行李。
- 春秋官方冬季航班时刻表存在 9C6686 AAT→TFU 每日计划班次；本记录不宣称具体日期仍有实际可售座位。

## 判断

1. 起降机场写反、舱位参数、sort_type、某个方向无航线不是主要根因。部分日期曾成功后又失败，且完全相同请求在不同时点表现不同。
2. FlyAI 上游查询/库存/服务端间歇性报错或额度/风控是可疑原因，但 status=1 没有明确的服务端错误分类，**不能确认具体根因**。有用户在官方 flyai-skill issue #54 报告高频请求 HTTP 403/451 风控；这与当前 status=1 **不是同一种确定错误**。
3. 频繁失败时三次不同参数重复调用、六组行程频繁轮询，可能加重请求量与免费额度风险；不能保证 15 分钟触发=15分钟拿到有效报价。

## 已部署的保守缓解

- scripts/flight_price_watch.py: effective_leg_attempts：前几次缺完整报价时保留官方三种尝试；同一行程连续失败≥3次后，每段仅做1次基线调用；每第6次连续失败恢复完整3次测试，以免永久错过参数级恢复。成功往返后计数归零。
- scripts/flight_watch_batch.py: 完整报价成功时保存 last_valid_fares，后续接口失败不覆盖历史有效价；摘要展示历史价格及时间但**绝不作为实时低价微信触发依据**。
- tests/test_flyai_retry_pressure.py 离线回归检查，通过 GitHub CI。

## 未解决与后续方向

- 尚不能修复 FlyAI 服务端 status=1 的真实根因，也不能证明限流触发；应查看账户的实际 API 剩余额度并与飞猪技术支持/官方仓库报告脱敏复现。
- 评估独立可授权的备用机票报价源；不得抓取受保护内容或使用无授权接口。订票价格须登录后核实税费、托运和雪具。
- 不要将历史报价冒充当前价格，任何 API 数据缺口都不能推断航班不存在。
