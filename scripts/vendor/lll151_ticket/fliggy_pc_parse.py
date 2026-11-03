# -*- coding: utf-8 -*-
"""Pure Fliggy PC innerText parser, vendored from LLL151/ticket.

Source: https://github.com/LLL151/ticket
Commit: ca55181167a2a0856d577c542c815655679478ea
Paths: crawlers/fliggy.py FliggyCrawler._parse_pc_text and its regexes;
       crawlers/base.py iata2; core/models.py PRICE_MIN and PRICE_MAX.
License: Apache-2.0. See LICENSE and NOTICE in this directory.

This file is not upstream HEAD. Browser fetch, login, challenge handling,
and network code are not included. parse_pc_text keeps the pinned commit's
text-parser behavior. Do not replace it by cloning the default branch.
"""
import logging
import re

_LOG = logging.getLogger(__name__)
PRICE_MIN = 100
PRICE_MAX = 50000


def iata2(v) -> str:
    """Airline IATA designator guard copied from crawlers/base.py."""
    s = str(v or "").strip()
    return s if re.fullmatch(r"[A-Z0-9]{2}", s) else ""


_RE_FNO = re.compile(
    r"([\u4e00-\u9fa5]{1,3})?((?:[A-Z][A-Z0-9]?|\d[A-Z])\d{3,4})"
    r"(\s*经停)?$")
_RE_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d")
_RE_ARR = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d(?:\s*第(\d)天)?$")
_RE_PRICE = re.compile(r"[¥￥]\s*(\d{1,3}(?:,\d{3})+|\d{3,5})")

def parse_pc_text(text: str, date: str, share_map=None,
                  transfer_map=None, recheck_note: str = "",
                  cal_pts=None, nearby=None, round_pts=None) -> list:
    """PC 页 innerText 行序（实测）：
    航班名行（东航MU8369 / 9C8945）
      → 机型行（中型机 737 共享|经停|）
      → 出发 HH:MM
      → 到达 HH:MM [第N天]
      → 起飞机场 / 到达机场
      → [准点率%]
      → ¥价格 [折扣] / 余票 / 订票
    share_map：营销号→实际承运（_SHARE_JS 采集），命中行挂
    shareCarrier 透传（展示层「共享·南方航空CZ6993」）。
    recheck_note：页面级中转说明图例（dd.transfer_note[data-content]，
    _RECHECK_JS 采集），含「重新办理登机手续」精确子串时对中转定证
    行落 transferBaggage='recheck'（页面级图例非行级归属，只对中转
    行生效；不覆盖已有值——未来若现 direct 证据不得被图例翻转）。
    """
    from datetime import datetime as _dt, timedelta as _td
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out, cur = [], None
    # 中转块首段暂存（一期）：中转块=首段航班名行+机型行 →
    # 二段航班名行+机型行 → 4 条「N月N日 HH:MM」→ 出发机场 →「城市
    # 中转」→ 到达机场 → … → ¥价。二段行头会把未定价的 cur（首段）
    # 重置——暂存 pend，「XX中转」行定证中转块时回捞合并；普通直飞
    # 流 pend 恒被下一轮 append/head 覆盖丢弃，行为不变
    pend = None
    d0 = _dt.strptime(date, "%Y-%m-%d")
    for i, ln in enumerate(lines):
        m = _RE_FNO.match(ln)
        if m and len(ln) <= 14 and not ln.startswith(("第", "星期")):
            if cur and "price" in cur and not cur.get("_drop"):
                out.append(cur)
                pend = None
            elif cur is not None:
                pend = cur
            # transCity 恒空串初始键退役（r241 残留族收口：
            # 「城2中转」覆写路径 418 行有值才写，缺席≡空串消费端等价）
            # 航司二字码（调研 B-3，健康 dump 31/31 行 DOM 类钩子
            # pi-flightlogo-nl-XX 值域与 code 前缀同串）：五渠道唯一
            # 无 airlineCode 源的渠道——从 code 首两字符派生 + iata2
            # 守卫（qunar H5 flightMark.carrier ≡ code 前缀同款派生律），
            # 同名落键即 webui 白名单/CSV/搜索 hay 自动继承零协议改动
            cur = {"name": ln, "code": m.group(2), "_i": i,
                   "depDate": date,
                   "airlineCode": iata2(m.group(2)[:2])}
            if m.group(3):
                cur["stopover"] = True
                # 观察哨（经停细节）：页面 a.J_Stop 锚现无 data-content
                # 载荷（细节在 JS 悬浮层，SSR 无源；more-transfer-wrap
                # 备选中转块 tbody 同恒空）——dump 出现锚带 data-content
                # 即启动经停城市/时刻补采调研（tuniu stopPoints 同构出口）
            sc = (share_map or {}).get(cur["code"])
            if sc:
                cur["shareCarrier"] = sc
            continue
        if cur is None:
            continue
        # 已定价后仅放行价格行：同航班第二价格行（CA8564 ¥9900 与
        # ¥3960 双价行实证、疑跨舱位并列）不得被 "price" in cur 整行
        # 丢弃——否则明细可能只剩高价行。取低者为主价（明细供比价/告警），
        # 较高者记 _alt_price 留痕；第三个价格行同理收敛。
        # 行距锚（热修）：并列舱位价紧邻首价格行（≤2 行）——
        # 无锚时虚拟列表尾航班的 cur 会一直开到文本结束，把页面尾部
        # 低价日历/推荐模块的任意 ¥N 吸进来 min() 取低（生产实锤：
        # CA8564 列表价 9900/3960 被尾部动态价 820→700 逐轮污染）
        if "price" in cur:
            # 中转机建燃油行（第八批 dump 实证）：transferItem
            # 中转行价格行 +1 行独立成行「¥240机建燃油」（=两段机建+
            # 燃油合计，中转行内 100% 在场）——第七批挂起注「需点击
            # 展开」被证伪，SSR/innerText 静态可见。行距锚同余票行；
            # 值域守卫 60-600（单段 60-190、两段 120-380、三段上限
            # 放宽，拒绝 k 量级脏值）。前置判（税行含 ¥ 会被 _RE_PRICE
            # 命中，后置 elif 永不可达——首版实跑 0 命中根因）；守卫
            # 拒收的税行也不得落入价格分支（¥560 类会当副价 min 吞）。
            # 首版只采+展示：FLIGGY_TAX_PAD 已于 归零重标定
            # （12,303 对中位比 1.000），无配对样本证据不接达标口径
            _taxm = re.match(r"^[¥￥](\d{2,4})机建燃油$", ln)
            if (_taxm and i - cur.get("_price_i", -99) <= 2
                    and "transferTax" not in cur
                    and 60 <= int(_taxm.group(1)) <= 600):
                cur["transferTax"] = int(_taxm.group(1))
            elif not _taxm:
                pm = _RE_PRICE.search(ln)
                if (pm and "arrTime" in cur
                        and i - cur.get("_price_i", -99) <= 2):
                    pv = float(pm.group(1).replace(",", ""))
                    if PRICE_MIN <= pv <= PRICE_MAX:
                        # 高档舱词跟随它所在价格行的报价：首行词
                        # （cur["cabin"]）配首行价、本行行尾词配本行
                        # 价——高价带词（公务/商务/头等）落 bizPrice
                        # （与 qunar/tuniu/tongcheng 同键同协议 int，
                        # dump 实证 CA8564 9900 与 tongcheng 同值跨
                        # 渠道互证）；无词高价（同舱双价/「全价」）
                        # 与经济舱词宁缺勿错不落；单报价行主价即
                        # 高档舱价，不重复记账（只在本分支可达）
                        _hi_mc = re.search(r"(公务舱|商务舱|头等舱)$", ln)
                        if pv > cur["price"]:
                            _hi_p, _hi_c = pv, (
                                _hi_mc.group(1) if _hi_mc else None)
                            _lo_p = cur["price"]
                        else:
                            _hi_p, _hi_c = cur["price"], cur.get("cabin")
                            _lo_p = pv
                            # 首价格行折扣词（N折/「全价」）描述的
                            # 是被撤高价——保留价来自低者，词不随
                            # 行，撤键宁缺勿错（与 cabin 撤键同律）
                            cur.pop("discount", None)
                        if (_hi_c in ("公务舱", "商务舱", "头等舱")
                                and _hi_p > _lo_p):
                            # 多带词高档行取最低（协议=「高档舱最低
                            # 参考价」，qunar businessClassMinPrice/
                            # tuniu ADT 最低 baseFare 同语义；取
                            # max 会成「公务￥头等价」舱名数值双误）。
                            # 旧主价对（cur["cabin"]+cur["price"]）
                            # 是另一带词高档行——首行词在 cabin 未及
                            # 落 bizPrice，须一并入 min 候选
                            _cands = [int(_hi_p)]
                            if cur.get("cabin") in (
                                    "公务舱", "商务舱", "头等舱"):
                                _cands.append(int(cur["price"]))
                            cur["bizPrice"] = min(_cands)
                        cur["_alt_price"] = max(cur.get("_alt_price", 0),
                                                cur["price"], pv)
                        cur["price"] = min(cur["price"], pv)
                        cur["_price_i"] = i
                        # 跨舱位并列价：保留价来自低者，首价格行的舱位
                        # 词不再描述它——撤键宁缺勿错（词对高价的
                        # 归属已由 bizPrice 记账）
                        cur.pop("cabin", None)
                # 余票紧张行：.less-tag 文本「少量/紧张/N张」
                # 在 innerText 序列位于价格行后 ≤2 行（docstring「¥价格/
                # 余票/订票」，dump 26/32 行在场）——已定价后仅放行价格
                # 行的状态机在此唯一可达点收；行距锚防吸入其他模块同形
                # 短行。落既有键 fewTicket 与 qunar「票少」同名同义
                elif (i - cur.get("_price_i", -99) <= 2
                      and "fewTicket" not in cur
                      and re.match(r"^(少量|紧张|\d+张)$", ln)):
                    cur["fewTicket"] = ln
            continue
        # 机型行（docstring 实测形态「中型机 737 共享|经停|」）：原状态机
        # 无该行分支整行丢弃 → 经停班被当直飞入库。保守分支：以「X型机」
        # 前缀锚定行形态再提取，机型取型号，行内含「经停」直落
        # stopover（normalize 同判幂等）。证据等级：debug/ 有快照
        # （起），行形态与快照一致。
        # 前缀体量词入 planeSize（「大型机/中型机/小型机」，
        # 宽体舒适度信号——fliggy 报文/页面均无 planeModelName 类
        # 结构化源，DOM 行首词是唯一真值）
        mm = re.match(r"^([大中小]型机|其他机型)\s*(\S+)", ln)
        if mm:
            cur.setdefault("plane", mm.group(2))
            # 「其他机型」（dump 实证：EU 31A=A321neo 族近上线，
            # 中转块首段 4/86 行）无体量信号不落 planeSize——
            # planeSize 值域=大中小型机，体量筛选不被污染；
            # meal/经停子串判定对新前缀天然生效
            if mm.group(1) != "其他机型":
                cur.setdefault("planeSize", mm.group(1))
            # has-food-label 双态标签：机型行同 <p> 容器的
            # label 文本随 innerText 落行尾（「中型机 737 有餐
            # 食」/「中型机 320 无餐食」同位同构，dump 实证两态
            # 均有实发）——负向无营销虚增动机、正向是航司如实
            # 披露，出现即真；落既有 meal 键与 ctrip/tuniu 同值域。
            # 结构性边界（勿立项寻源「直飞 meal」）：渠道该 label
            # 元素只挂中转块段头，直飞行从不携带——DB 13 天窗实证
            # 直飞 62,652 元素 0 出勤 / 中转 2,342 元素 100% 出勤，
            # 属渠道结构性无源非解析缺陷
            if "无餐食" in ln:
                cur.setdefault("meal", "无餐食")
            elif "有餐食" in ln:
                cur.setdefault("meal", "有餐食")
            if "经停" in ln:
                # 经停语义直落 stopover，_via 内部哨兵不入库
                # （_via 是 DOM 兜底路径内部哨兵，落库即污染
                # extra schema，qunar._via 同律；消费端 normalize
                # 对 stopover 短路判定结果不变）
                cur["stopover"] = True
            if "共享" in ln and not (share_map or {}).get(
                    cur.get("code")):
                # 共享词面兜底（r339b F1）：「共享」词与 share
                # 载荷（a.J_Content data-content）同 DOM 元素渲染
                # ——_SHARE_JS evaluate 异常被吞/按屏漏采窗时，
                # 词面是共享事实的独立载体；shareCarrier 命中
                # （常态轮）时零增量不重复落
                cur["labels"] = ((cur.get("labels") + "·共享")
                                 if cur.get("labels") else "共享")
            continue
        # 机场行：「乌鲁木齐天山国际机场」（出发侧单航站
        # 楼无 T 码）/「虹桥国际机场T2」（到达侧 35/35 带码）——
        # 首个机场行挂 depTerminal、第二个挂 arrTerminal（qunar DOM
        # 同序状态机口径），T 码取行尾全匹配、无码不落键（恒空键
        # 卫生律：槽位判定锚 depAirport/arrAirport 恒真值写点，不锚
        # 可缺席的航站楼键）。
        # depTime 守卫防页面异源模块（日历/推荐）含「机场」文本吸入。
        # 行文本剥尾部 T 码即机场名，落 depAirport/
        # arrAirport（「虹桥国际机场」原值，渲染端统一剥后缀）
        if ("机场" in ln and ("depTime" in cur or cur.get("_dtl"))
                and "price" not in cur):
            tm = re.search(r"(T\d+)\s*$", ln)
            t = tm.group(1) if tm else ""
            air_name = ln[:tm.start()].strip() if tm else ln.strip()
            if "depAirport" not in cur:
                cur["depAirport"] = air_name
                if t:
                    cur["depTerminal"] = t
            elif "arrAirport" not in cur:
                cur["arrAirport"] = air_name
                if t:
                    cur["arrTerminal"] = t
            continue
        # 中转块日期时刻行（一期）：「10月05日 15:15」形态
        # 每段起降一条（两段 4 条：首段起/落+二段起/落），与直飞行
        # 裸 HH:MM 形态互斥（_RE_HHMM 锚定不匹配）——先行暂存 _dtl，
        # 「XX中转」定证行处统一定日期（月日无年份，按航线日期年份
        # 推算、跨年进位）；不足 4 条（折叠半截块）宁缺勿错不定时刻，
        # 该行随后无 arrTime 自然不落价（与既有丢弃行为一致）
        md = re.match(r"^(\d{1,2})月(\d{1,2})日\s*(\d{1,2}:\d{2})$", ln)
        if md and cur is not None and "price" not in cur:
            cur.setdefault("_dtl", []).append(
                (int(md.group(1)), int(md.group(2)), md.group(3)))
            continue
        # 中转定证行：「石家庄中转」（城市+中转，行序在两机场行之间，
        # 不含「机场」二字不触上行分支）——此刻 cur=二段行、pend=首
        # 段行，合并成统一 schema 中转行（code「A/B」tongcheng 同形、
        # name 取首段；时刻取 _dtl 首末条=整体起降，衔接=首段落−二段
        # 起结构化真值，layoverSrc=transInfo 豁免 flightnorm 1440
        # 回绕判伪，同 qunar/tongcheng 协议）。
        # 冗余校验源备案（r308 渠道调研）：行容器 DOM 有结构化
        # data-is-transfer="1" 旗标（66/158 行在场）——未来行状态
        # 机重写时作文本定证的互证源（文本定证与结构旗标不一致行
        # 告警落 dump）；当前文本定证在工作，不单独立项。
        # 跨楼中转行渠道在同 div 兄弟位补 <label class=change-terminal>
        # 换航站楼</label>，行文本实证「西安中转 换航站楼」（两 label
        # 间空白节点渲染成单空格，也可能无空白直接拼行）——后缀连同
        # 间隙并入定证锚（锚断=跨楼行整行丢失+孤儿段污染邻块嵌合行，
        # 生产实录在案）；「换航站楼」词面零增量不落键（跨楼由
        # transTerminal≠transDepTerminal 既有出口派生承载）。
        mt = re.match(r"^([\u4e00-\u9fa5]{2,8})中转\s*(?:换航站楼)?$",
                      ln)
        if mt and cur is not None and "price" not in cur:
            # 二次定证=三段两转异形块（实跑复现：
            # 「城1中转」已消费 _dtl 定盘，后续「中转机场」行错占
            # arr 位、「城2中转」覆写 transCity、pend 顶成二段——
            # 产出丢首段/中转机场当到达场/末城当经停的多字段错值行，
            # 看似正常入库最脏）——整行宁缺勿错弃，_drop 挡两侧 append
            if cur.get("transCity"):
                cur["_drop"] = True
                pend = None
                continue
            cur["transCity"] = mt.group(1)
            _dtl = cur.pop("_dtl", None) or []
            # 备份源哨（r312 渠道调研）：transfer 气泡 transfer-p2
            # 「停N小时M分钟」与 _dtl 四时刻推导 layover 16/16 全等
            # （含跨天）——若未来出现「_dtl 不足 4 条（折叠半截块）
            # 而 p2 在场」的行，p2 可作 layover 备份源（解析词面
            # 「N小时M分」形态与 qunar stopTime 同族）；当前 0 例
            # 不接线，宁缺勿错
            if len(_dtl) >= 4:
                try:
                    _mk = lambda m, d, t: _dt(
                        d0.year + (1 if (m, d) < (_dtl[0][0],
                                                  _dtl[0][1]) else 0),
                        m, d, int(t[:2]), int(t[3:]))
                    _d_dep, _d_arr = _mk(*_dtl[0]), _mk(*_dtl[-1])
                    _d_l1a, _d_l2d = _mk(*_dtl[1]), _mk(*_dtl[2])
                    cur["depTime"] = _dtl[0][2]
                    cur["arrTime"] = _dtl[-1][2]
                    cur["depDate"] = _d_dep.strftime("%Y-%m-%d")
                    cur["arrDate"] = _d_arr.strftime("%Y-%m-%d")
                    _xd = (_d_arr.date() - _d_dep.date()).days
                    if _xd > 0:
                        cur["crossDayDesc"] = f"+{_xd}天"
                    _lay = int((_d_l2d - _d_l1a).total_seconds() // 60)
                    if _lay > 0:
                        cur["layover"] = _lay
                        cur["layoverSrc"] = "transInfo"
                        cur["lay2dep"] = _dtl[2][2]
                except ValueError:
                    pass
            if pend is not None:
                cur["code"] = f"{pend['code']}/{cur['code']}"
                cur["name"] = pend["name"]
                # airlineCode 随合串 code 首段（与 qunar 中转
                # shortCarrier=首段承运语义对齐，勿留二段值）
                cur["airlineCode"] = iata2(pend["code"][:2])
                if pend.get("shareCarrier"):
                    cur.setdefault("shareCarrier", pend["shareCarrier"])
                # 首段餐食标签随段合并（卫生约束：不得只
                # 搬 code/name/shareCarrier——首段「无餐食/有
                # 餐食」二段未标时标签整段丢失；meal 值域={有
                # 餐食,无餐食}双态，两段异值时保守仲裁为「无
                # 餐食」（一段无餐食=全程存在无餐食段，正向
                # 优先会掩蔽该事实），同值/单侧照搬）
                if pend.get("meal"):
                    if cur.get("meal") and cur["meal"] != pend["meal"]:
                        cur["meal"] = "无餐食"
                    else:
                        cur.setdefault("meal", pend["meal"])
                # 首段机型随段合并（r309 调研 dump 实证 45/45 双机
                # 型行、跨段异值 28/43=65%，首段词面 DB labels
                # 0/11380 零出口——读者只看到二段机型会误读为全程
                # 机型）。段位口径备案：主槽 plane 恒=二段机型（现
                # 状不动，零存量语义漂移；tongcheng 中转行 plane=
                # 首段为渠道本态，跨渠道主槽段位差不在此收口——任
                # 一侧改落位都是存量无源可迁移的语义漂移）；首段机
                # 型以 labels 词面「首段XXX」消歧落地（tongcheng
                # share_txt 先例：labels 既有渲染通道，webui/CSV/
                # report 三端零协议改动）；两段同值不落（主槽已代
                # 表全程，零增量不采）；首段体量词不落（4/43 稀疏，
                # 型号异值已覆盖决策信息）。二段机型缺席时首段机型
                # setdefault 顶主槽（零冲突）且 labels 段位词面照
                # 落防误读。
                if pend.get("plane"):
                    if cur.get("plane") != pend["plane"]:
                        # 整槽覆写形态（r310 推送审校 B-E1 备案）：
                        # 本键是 fliggy 唯一写点、现值恒空故零实害；
                        # 未来在此行增设第二个 labels 词前须改
                        # 「append+去重」形态，覆写会静默丢前词
                        cur["labels"] = f"首段{pend['plane']}"
                    if not cur.get("plane"):
                        cur.setdefault("plane", pend["plane"])
                        if pend.get("planeSize"):
                            cur.setdefault(
                                "planeSize", pend["planeSize"])
                # 中转换乘楼号（第九批，_TRANSFER_JS 采集）：
                # transfer_map 值恒 (到达楼, 二段起飞楼) 二元组——
                # 唯一写点即本文件采集处，键为航班号；旧调用方
                # 单值 str 形态按「单到达楼」语义容错收编为
                # (str, '')，不被当序列下标产脏。
                # 以首段/二段号配对（行容器归属首段号，二段号兜底）；
                # 「正定国际机场T2」剥「国际机场/机场」后缀对齐
                # qunar「咸阳T3」/ctrip transTerminal 同形。
                # 二段起飞楼（跨航站楼中转，10-05 dump 实证）同剥
                # 「起飞」尾与机场后缀落 transDepTerminal，与
                # tongcheng ss[1].dat 同名同位；无第二段不落键。
                # （r265 备案）stopover 只随二段行头（cur）天然携带；
                # 首段带「经停」后缀的形态 dump 未证，若未来出现，
                # 合并分支不搬首段 stopover=真值静默丢——届时随本
                # 分支补搬。合并行 stopover=True（二段经停）进指纹族
                # （_fp_cands/_dedup_tie 有意设计：经停与无标渠道
                # 同组合不并比价组——多一次起降非同质产品，真值
                # 透传优先于跨渠道 tie 配对，r265 Soldier Major-1
                # 裁决备案；宁分勿混，比价省额不虚标）。
                _tt = ((transfer_map or {}).get(pend["code"])
                       or (transfer_map or {}).get(
                           cur["code"].split("/")[-1]) or ())
                if isinstance(_tt, str):
                    _tt = (_tt, "")
                if _tt:
                    cur["transTerminal"] = re.sub(
                        r"国际机场|机场", "", _tt[0], count=1)
                    _t2 = re.sub(r"\s*起飞\s*$", "", str(
                        _tt[1] if len(_tt) > 1 else "")).strip()
                    if _t2:
                        cur["transDepTerminal"] = re.sub(
                            r"国际机场|机场", "", _t2, count=1)
                # （调研 R4）：页面级图例守卫三 AND——(a) 本行
                # 中转已定证（此处 transCity 刚落）；(b) 图例含「重新
                # 办理登机手续」精确子串（渠道改文案即静默不落）；
                # (c) 不覆盖已有值。 观测转正（撤先观测备
                # 注）：修复生效后累计 11/11 全部 recheck、反例 0，
                # 反例出现即回滚该置值
                if ("重新办理登机手续" in recheck_note
                        and not cur.get("transferBaggage")):
                    cur["transferBaggage"] = "recheck"
                pend = None
            continue
        if _RE_HHMM.match(ln) and "depTime" not in cur:
            cur["depTime"] = ln
            continue
        ma = _RE_ARR.match(ln) if "depTime" in cur else None
        if ma:
            cur["arrTime"] = ln[:5]
            days = int(ma.group(2)) - 1 if ma.group(2) else 0
            cur["arrDate"] = (d0 + _td(days=days)).strftime("%Y-%m-%d")
            if days:
                cur["crossDayDesc"] = f"+{days}天"
            continue
        if ln in ("经济舱", "公务舱", "头等舱", "商务舱") and "cabin" not in cur:
            cur["cabin"] = ln
            continue
        # [准点率%] 行：纯数字串入库，与 tongcheng/ctrip/tuniu 形态
        # 一致（展示层统一拼「准点N%」，1-100 守卫同 tongcheng）。
        # 放宽带小数：DOM 快照实证 flight-ontime-rate 值形
        # 如「96.67%」「100.0%」，整数正则 0/34 命中（结构性全空）；
        # 四舍五入取整入库保持全站「准点N%」整数形态。
        # 供给间歇定性备案（r308 渠道调研，勿按解析缺陷立案）：
        # 渠道行级准点率单元格间歇供给——10-05/06 代无单元格、
        # 10-15 代多值健康带 {100.0%×24, 96.67%×11, 93.33%×6}
        # （多值排除恒档透传）、2027 代元素壳在场而文本全空；
        # DB prate 出勤 0/400 与之互证。本读层对带值形态可匹配、
        # 空串天然不落，行为正确，值恢复即自然复采；若连续两季
        # 仍恒空再立「渠道撤字段」备案。
        # 观察哨（r311 渠道调研）：中转行准点率双值格（二段
        # ontime）仅 10-15 代 6/64 中转行、2027 代全空——现行
        # 单值门采首段丢二段；双值格出勤回升 >30% 再立项补二段
        # 读法（届时按 dump 实证格形态，勿按推断）
        mp = re.match(r"^(\d{1,3}(?:\.\d+)?)\s*%$", ln)
        if mp and "prate" not in cur:
            try:
                _pv = float(mp.group(1))
            except ValueError:
                _pv = 0
            if 0 < _pv <= 100:
                cur["prate"] = str(int(round(_pv)))
                continue
        pm = _RE_PRICE.search(ln)
        if pm and "arrTime" in cur:
            # 价格 band 校验（全链路价带单源 PRICE_MIN=100）：越界
            # 不落 price → 该行最终不 append，debug log 留痕
            pv = float(pm.group(1).replace(",", ""))
            if PRICE_MIN <= pv <= PRICE_MAX:
                cur["price"] = pv
                cur["_price_i"] = i   # 双价行行距锚基点
                # 折扣同行提取：span.discount「5.6折」35 处
                # 实证全未解析；N折 形态校验同明细表 discount 门槛
                if "discount" not in cur:
                    md = re.search(r"(\d(?:\.\d)?)折", ln)
                    if md:
                        cur["discount"] = md.group(1) + "折"
                    elif "全价" in ln:
                        # 「全价」=无折扣可售（SSR span.discount 词
                        # 域 10-06 17/31=55%）；qunar/tuniu/tongcheng
                        # 同域已在产，消费端 discount_txt 单源放行。
                        # 双价行归属由合并分支裁决（词不随行）
                        cur["discount"] = "全价"
                # 行尾舱位词（调研实证「¥9900 商务舱」span.discount
                # 形态）：单报价行的裸价无从辨识舱位；$ 锚行尾，
                # 「全价」类非舱位词天然不匹配（discount「N折」值域
                # 协议与 cabin 双零误配路径）。双价行（跨舱位并列）
                # 不保此键——取低者为主价时首行舱位词不再描述保留价
                if "cabin" not in cur:
                    mc = re.search(r"(经济舱|公务舱|头等舱|商务舱)$", ln)
                    if mc:
                        cur["cabin"] = mc.group(1)
            else:
                _LOG.debug("[fliggy] 价格 %s 越界，弃用该行 %s",
                           pv, cur.get("code", ""))
            continue
    if cur and "price" in cur and not cur.get("_drop"):
        out.append(cur)
    # 去重（多屏收集同航班）与清理
    seen, clean = set(), []
    for f in out:
        f.pop("_i", None)
        f.pop("_price_i", None)
        f.pop("_dtl", None)   # 异形块半截暂存
        f.pop("_drop", None)
        # _alt_price 是双价行留痕内部键，无任何消费端——不 pop
        # 则双价行一出现即泄漏进 extra（卫生语义）
        f.pop("_alt_price", None)
        # totalDuration 不落库（调研占位键卫生：渠道「约N小时」
        # 粗粒度且按页摇摆（td.flight-total-time 在场/全撤两态均
        # 实证，A/B 渲染随机），采了反降级——消费端
        # flightnorm 按 dep/arr+跨天自算精确到分覆盖（normalize
        # 后 4时35分 实证），有值才落键口径维持；消费端全 .get()
        # 风格+normalize 空值安全，缺键无行为差
        key = (f["code"], f.get("depTime"), f["price"])
        if key in seen:
            continue
        seen.add(key)
        clean.append(f)
    # 幻影价守卫（qunar 0.5x 同思想）：下四分位作群体锚而非中位
    # ——中位锚在宽价差航线误杀真实早班低价（SHA→BJS 实测：中位
    # ￥930，MU5195 ￥405 与去哪儿同班同价却被弃）；下四分位只
    # 锚尾部异源模块（CA8564 ￥700 vs 群 2850+ 生产实锤仍命中）。
    # 中转真值豁免（实跑复现）：layoverSrc=
    # transInfo 行的时刻/衔接是渠道结构化真值非页面猜测，其价也是
    # 独立报价——低价中转恰是本批核心价值行（¥900 中转 vs 直飞群
    # 2020 曾被 0.5x 中位锚误杀弃行），守卫只服务猜测值（与
    # flightnorm 1440 回绕判伪豁免同哲学）
    if len(clean) >= 4:
        prices = sorted(f["price"] for f in clean)
        anchor = prices[len(prices) // 4]
        kept = [f for f in clean if f["price"] >= anchor * 0.5
                or f.get("layoverSrc") == "transInfo"]
        for f in clean:
            if (f["price"] < anchor * 0.5
                    and f.get("layoverSrc") != "transInfo"):
                _LOG.warning("[fliggy] 幻影价守卫弃行 %s ￥%.0f"
                             "（< 下四分位 ￥%.0f 的 0.5x，页面异源"
                             "模块污染）", f.get("code"), f["price"], anchor)
        clean = kept
    # 日历邻日最低价（trendGo 跨渠道协议归一第三源）：qunar
    # goFTrend / tongcheng pc[] 同语义同键同形态 [["MM-DD",价],…]，
    # 挂当轮最低价行（逐行重复=extra 膨胀，同两渠道「仅挂最低行」
    # 律）；消费端 webui 改期胶囊/CSV「改期最低」列零改动三渠道
    # 受益。cal_pts 已过 _parse_cal_points 逐点校验（日期形/价带），
    # 语义=「换个日子飞多少钱」的该渠道展示价（与行价同口径）。
    # nearby（周边城市特价）同槽同律：语义=「换个地方降落多少钱」
    # （邻近到达城市差价，决策辅助变量非本航线价格），已过
    # _parse_nearby 逐点守卫。trendRound（往返程推荐）同槽第三
    # 兄弟：语义=「往返一起订多少钱」（打包价 vs 两张单程，
    # trendGo 换日子/nearby 换目的地同族读者问句），已过
    # _parse_round 逐点守卫；三者同守「仅挂当轮最低价行」与
    # 无值不落键，行 schema 与既有轮全等
    if (cal_pts or nearby or round_pts) and clean:
        lo = min(clean, key=lambda f: f.get("price") or 9e9)
        if cal_pts:
            lo["trendGo"] = cal_pts
        if nearby:
            lo["nearby"] = nearby
        if round_pts:
            lo["trendRound"] = round_pts
    return clean
