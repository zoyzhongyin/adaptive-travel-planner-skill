# 阿勒泰新增国内票务来源实测｜2026-10-31

用户查询固定条件：成都天府TFU ⇄ 阿勒泰雪都AAT；1成人经济舱、直飞、六组五晚日期。

## GitHub真实执行证据
- 平台入口访问：https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41158740300
- 美团正常城市及12月日期选择：https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41159245650
- 美团三组完整列表与API被动响应检查：https://github.com/zoyzhongyin/adaptive-travel-planner-skill/actions/runs/41159549104

## 新来源结论
1. 美团机票公开 H5 可正常打开、填写成都、阿勒泰（雪都机场）、12月9日。12/09去程日历显示443元，12/14返程日历683元，12/18去程443元；但三次均显示“查不到相关航班信息，请稍后重试”。网页自己请求 getflightwiththreecode 返回HTTP200，data里只有msg字段，没有航班清单；另一个getLowPriceCalendar返回61天日历起步价。搜索参数为成都城市码CTU，不能认定TFU。绝不能将443+683=1126元认作可购买往返价。暂不接入。
2. 智行移动入口 https://m.suanya.com/h5/index.html 此次浏览器被HTTP432 whaleguard阻断。无有效报价。
3. 航旅纵横公开H5直销跳转 https://m.umetrip.com/n/lFOI2I 返回HTTP504。官方App直销服务实际存在，国航川航公告支持，但匿名网页本次没有取得可比价数据。

## 下一步优先试行美团官方 AI Skill
- 官方出处：https://developer.meituan.com/ai-hub/skill-list/detail/12
- 官方美团旅行Skill提供机票搜索，需要美团Passport扫码授权和官方 @meituan-travel/ht-ai-open CLI；未取得授权、未证明匿名或GitHub无人值守可用，不能冒称上线。
- 在用户自己本地Codex验证，扫码仅在官方页面完成，不让用户粘贴密码/Token/手机号/验证码。仅完成12/09去程、12/14返程的机票查询，核航班号、真实机场TFU、税费、行李和可售舱位。只有支持低频自动再接云端。
- 不用未知第三方多源代理冒充官方，不购买API，不跨越登录验证。

## 生产状态
FlyAI、同程、携程、飞猪PC、Google Flights CNY 五条取价技术通道不受影响。没有新增第六条正式来源，也没有更改Cloudflare、微信提醒或购票规则。