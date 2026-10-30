#!/usr/bin/env python3
"""One-off, bounded, read-only public booking-page compatibility diagnostic.

No credential, provider API, XHR interception, CAPTCHA handling, fingerprint
evasion, cookie persistence, requests to undocumented endpoints, booking or
state modifications. An HTML price token is NOT a verified fare. Fail closed.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
import re
import shutil
from urllib.parse import urlencode, urlparse
from playwright.sync_api import sync_playwright

BJT=timezone(timedelta(hours=8))
DATES=(("TFU","AAT","2026-12-09"),("AAT","TFU","2026-12-14"))
MATCHERS={
  "spring":"[data-route-index]",
  "ctrip":".flight-list .flight-item, [class*=flight-card], [class*=flightItem]",
  "tuniu":".J-flightlist,[class*=flight-list],[class*=flightItem]",
  "qunar":"[class*=flight-list],[class*=flightItem]",
  "trip":"[class*=flight-card],[class*=flight-list]",
}
def address(source,o,d,day):
    if source=="spring":
        q=urlencode({"FDate":day,"ANum":1,"CNum":0,"INum":0,"SType":0,
                     "IfRet":"false","MType":0})
        return f"https://en.ch.com/flights/{o}-{d}.html?{q}"
    if source=="ctrip":
        return f"https://flights.ctrip.com/online/list/oneway-{o.lower()}-{d.lower()}?depdate={day}&cabin=y_s&adult=1"
    if source=="tuniu":
        return f"https://m.tuniu.com/flight/domestic/new/{o}_{d}_OW_1_0_0?deptDate={day}&isGo=0"
    if source=="qunar":
        return "https://m.flight.qunar.com/ncs/page/flightlist?" + urlencode({"depCity":"成都" if o=="TFU" else "阿勒泰", "arrCity":"成都" if d=="TFU" else "阿勒泰", "goDate":day, "from":"touch_index_search", "child":"0", "baby":"0", "cabinType":"0"})
    if source=="trip":
        return f"https://www.trip.com/flights/{o.lower()}-to-{d.lower()}/tickets-{o.lower()}-{d.lower()}?dcity={o}&acity={d}&ddate={day}"
    raise ValueError(source)

SCRIPT=r"""(selector) => {
 const text=(document.body?.innerText||'').slice(0,150000);
 const flightMatches=[...new Set((text.match(/\b(?:CA250[56]|3U657[3456]|9C668[56])\b/gi)||[]).map(x=>x.toUpperCase()))];
 const amounts=(text.match(/(?:¥|￥|CNY|RMB)\s*(?:[1-9]\d{1,4})(?:\.\d{1,2})?/g)||[]).length;
 const bad=/验证码|请登录|扫码登录|注册或登录|访问过于频繁|滑动验证|安全验证|captcha|access denied|robot check|rate limit|需要登录/i.test(text);
 const dateMentions=(text.match(/(?:2026[-/.]12[-/.](?:09|14)|12月(?:9|14)日)/g)||[]).length;
 const rows=document.querySelectorAll(selector).length;
 return {
   dom_ready:document.readyState,
   visible_chars:text.length,
   explicit_target_flightnos:flightMatches,
   money_token_count:amounts,
   exact_date_text_mentions:dateMentions,
   raw_rows:Math.min(rows,1000),
   visible_challenge_or_login:bad
 };
}"""
def probe():
    results=[]
    with sync_playwright() as p:
        binary=shutil.which('google-chrome') or shutil.which('chromium')
        browser=p.chromium.launch(headless=True, **({'executable_path':binary} if binary else {}))
        try:
            for source in ("tuniu","qunar"):
                for origin,dest,day in DATES:
                    page=browser.new_page(locale="zh-CN", viewport={"width":390,"height":844}, device_scale_factor=2, is_mobile=True, has_touch=True)
                    result={"provider":source,"day":day,"route":origin+"→"+dest,
                            "verified_fare":False}
                    try:
                        resp=page.goto(address(source,origin,dest,day),
                                       wait_until="domcontentloaded",timeout=22000)
                        page.wait_for_timeout(4500)
                        state=page.evaluate(SCRIPT,MATCHERS[source])
                        if source == "spring":
                            state["spring_dom"] = page.evaluate(r"""() => {
                              const pick=(s)=>[...document.querySelectorAll(s)].slice(0,5)
                                .map(n=>({
                                  label:(n.innerText||n.value||"").trim().slice(0,180),
                                  title:(n.getAttribute("title")||"").slice(0,60),
                                  name:(n.getAttribute("name")||"").slice(0,60),
                                  cls:(n.className||"").toString().slice(0,80)
                                }));
                              return {
                                selected_dates:pick(".J-date-picker .selected,.J-date-picker .active,.J-date-picker .cur,.J-date-picker li.on,.J-date-picker li.current"),
                                calendar_head:pick(".J-date-picker li"),
                                date_inputs:pick("input[name*=Date], input[id*=date],input[name*=date]"),
                                flight_rows:pick("[data-route-index]"),
                                flightnos:pick("[data-route-index] .c-flight-no"),
                                prices:pick("[data-route-index] .td-price-item"),
                                route_dep:pick("[data-route-index] .td-left .local"),
                                route_arr:pick("[data-route-index] .td-right .local")
                              };
                            }""")
                        result.update({
                          "http_status":resp.status if resp else None,
                          "final_host":urlparse(page.url).hostname,
                          "title":(page.title() or "")[:100],
                          **state
                        })
                    except Exception as exc:
                        result["error_class"]=type(exc).__name__
                    finally:
                        page.close()
                    print(json.dumps(result,ensure_ascii=False),flush=True)
                    results.append(result)
        finally: browser.close()
    return results

def main():
    results=probe()
    out=os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out,"a",encoding="utf8") as f:
            f.write("# 第三方机票网页独立渠道验证（只读无登录）\n\n")
            f.write("普通 Chromium 访问，不尝试跳过登录/风控、不可视为实际可出票报价。\n\n")
            f.write("| 来源 | 航段 | HTTP | 页面明示航班 | 价格字符数量 | 日期字符 | 登录/风控迹象 |\n")
            f.write("|---|---|---:|---|---:|---:|---|\n")
            for r in results:
                f.write("| "+r["provider"]+" | "+r["day"]+" "+r["route"]+" | "+
                        str(r.get("http_status") or r.get("error_class") or "—")+
                        " | "+(", ".join(r.get("explicit_target_flightnos") or []) or "无")+
                        " | "+str(r.get("money_token_count","—"))+
                        " | "+str(r.get("exact_date_text_mentions","—"))+
                        " | "+str(r.get("visible_challenge_or_login","unknown"))+" |\n")
            f.write("\n本测试没有解析、核实实际价格：看到￥数字或航班号不等于可售座位。"+
                    "如遇登录/风控则不可自动接入。\n")
            f.write("北京时间："+datetime.now(BJT).isoformat(timespec="seconds")+"\n")

if __name__=="__main__":
    main()
