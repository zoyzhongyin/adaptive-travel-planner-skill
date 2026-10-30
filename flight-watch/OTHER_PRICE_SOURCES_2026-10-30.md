# 阿勒泰航线其他机票数据源调查｜2026-10-30

**目标**：仅成都天府 TFU ⇄ 阿勒泰 AAT，2026-12-08/09、17/18、26/27去程和五晚后返程，国航CA/川航3U/春秋9C，零新增付费，关注可靠实际价格与低价提醒。现有 FlyAI 和同程已运行，本实验**不触碰生产监控**。

## 已实测公开页面（GitHub Actions 普通 Chromium）

实验环境：云端 Ubuntu + Chromium，无账号、Token、验证码绕过、隐蔽私有 API、代理轮换，也未永久保存 Cookie。

[5来源/双方向试验](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41063893430)：

| 来源 | TFU→AAT 12月9日 | AAT→TFU 12月14日 | 价格有效性 | 结论 |
|---|---|---|---|---|
| 春秋官网 en.ch.com | HTTP 200、部分运行出现9C6685和日历金额 | HTTP 200、部分运行出现9C6686 | 不稳定、未验证日期对应可售机票 | **值得针对性二次测试** |
| 携程 flights.ctrip.com | HTTP 432 | HTTP 432 | 没有 | 当前云端不可直接接入 |
| Trip.com | HTTP 432 | HTTP 432 | 没有 | 当前云端不可直接接入 |
| 途牛第一入口 | HTTP 404 | HTTP 404 | 没有 | 首次 URL 无效 |
| 去哪儿第一入口 | HTTP 200 但只有通用首页 | 同左 | 没有 | 未命中目标航班明细 |

[正确途牛/去哪儿深链及普通移动端视口二次试验](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41064830497)：
- 途牛标准 H5 国内机票列表页返回 HTTP 500，两个方向均无航班明细。
- 去哪儿标准 H5 `/ncs/page/flightlist` 返回 HTTP 200，但正文仅有通用标题，没有目标航段/日期/航班或票价；不能认定成功。
- 因此两者截至当前未达“真实价格”数据源的标准，不宜装进每天自动轮询。
- 以上都是 **云端测试结果**，不能推断本机已登录浏览器也一样。

[春秋二次精确日期检查](https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41064379398)：
- 12月9日 TFU→AAT：所选日期字段为 `2026-12-09`，航司官网公开低价日历显示 `CNY920`，但当次 DOM 无可确认的航班列表。
- 12月14日 AAT→TFU：所选日期字段为 `2026-12-14`，日历显示 `--`，且当次 DOM 无可确认的航班列表。
- 此数据只能称“对应日期公开日历提示值”，不是完整单程可售报价，不能与同程 ¥840/¥900直接比较或触发微信。

## 无需复制爬虫即可得到的独立预警渠道

- [Google Flights 已覆盖成都→阿勒泰航线](https://www.google.com/travel/flights/flights-from-chengdu-to-altay-prefecture.html)；[Google 官方支持按指定航线、日期/航班设置免费价格跟踪并发邮件或移动端提醒](https://support.google.com/travel/answer/6235879?co=GENIE.Platform%3DAndroid&hl=en-PN)。无需逆向接口，但账户需本人登录配置；航班覆盖不保证完整。
- [国航官方将航旅纵横作为直销平台](https://www.airchina.com.cn/zh-CN/content/c/2025-07-28/26096.shtml)；[川航官方也把航旅纵横列为直销平台](https://www.sichuanair.com/affiche/791.html)。**适合作为购买前核价基准**，但没有查到无需授权的个人免费实时价格 API。
- 应注意 Google Flights 显示的国航/川航一周直飞频率可能与国航最新公布的冬春航季时刻表有差异，因此不能当成完整排班/库存唯一来源。

## 对现有系统的建议

1. **维持 FlyAI + 同程双源运行**：这两个目前已有真实取数记录；未核实网页候选价格只展示，不单独发“¥1500达标”微信。
2. **春秋官网**是优先备用源：研究日期日历和真实单程列表匹配的稳定性，确保具体航班、正确日期、TFU/AAT、舱位/税费才可升级为实际第三源。
3. **Google Flights 价格跟踪**可以由用户登录后为六组行程开启，不依赖 ChatGPT Token；邮件本身不能证明当下可出票，应跳转航空公司复核。
4. **去哪儿、携程**：能用本人已登录的普通本机浏览器合理查价，可研究用户授权会话；不能将 HTTP 200/432、风控重定向或空列表当成有效结果。
5. 第三方 Skill 仅作为可选代码参考，**不能以 GitHub 项目宣称支持五平台就当成五个已验证稳定的数据源**。
6. 不用共享账号密码，不伪造注册身份，不自动出票；如果涉及设备标识、验证码或访问限制，优先正常手机浏览器/用户本机合法会话，不把重度反风控方案放进云端长期运行。

## 本轮交付范围

所有新代码和一次性测试只存在实验分支 `experiment/altay-additional-public-sources-20261030`；未合并 main、未创建新定时监控、未更新 Cloudflare Worker、未更改降价微信规则。结论是**暂时没有找到通过验证、能马上替代/扩展生产监控的第三个自动票价数据源**。
