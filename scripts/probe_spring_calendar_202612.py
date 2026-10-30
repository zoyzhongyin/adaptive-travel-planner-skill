#!/usr/bin/env python3
"""A single, read-only public Spring Airlines calendar coverage audit.

No account, tokens, cookie persistence, device identifier changes, hidden API
calls, booking, fare alerts or production write. Calendar prices are
*indicative*, not confirmed available seat or final taxed fare.
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, urlparse
from playwright.sync_api import sync_playwright

BJT=timezone(timedelta(hours=8))
LEGS=[
("TFU","AAT","2026-12-08"),("AAT","TFU","2026-12-13"),
("TFU","AAT","2026-12-09"),("AAT","TFU","2026-12-14"),
("TFU","AAT","2026-12-17"),("AAT","TFU","2026-12-22"),
("TFU","AAT","2026-12-18"),("AAT","TFU","2026-12-23"),
("TFU","AAT","2026-12-26"),("AAT","TFU","2026-12-31"),
("TFU","AAT","2026-12-27"),("AAT","TFU","2027-01-01"),
]
JS=r"""() => {
 const selected = document.querySelector('.J-date-picker .current');
 const selectedText = selected ? (selected.innerText||'').trim().slice(0,110) : '';
 const input = document.querySelector('input[name="FDate"]');
 const depInput = document.querySelector('input[name="departureDate"]');
 const flightRows=[...document.querySelectorAll('[data-route-index]')];
 const number=(document.body?.innerText||'').match(/\b(?:9C6685|9C6686)\b/gi)||[];
 return {
  chosen_fdate:input?.value?.slice(0,10) || null,
  shown_departureDate:depInput?.value?.slice(0,10) || null,
  selected_label:selectedText,
  calendar_price: (selectedText.match(/(?:CNY|¥|￥)\s*([\d,]+)/i)||[])[1]||null,
  row_count:flightRows.length,
  flight_numbers:[...new Set(number.map(x=>x.toUpperCase()))],
  selected_has_dash: /^\s*--/.test(selectedText),
  visible_gate: /(验证码|访问过于频繁|安全验证|滑块验证|captcha|access denied)/i.test(document.body?.innerText||'')
 };
}"""
def main():
    outputs=[]
    with sync_playwright() as p:
        import shutil
        binary=shutil.which("google-chrome") or shutil.which("chromium")
        browser=p.chromium.launch(headless=True,**({"executable_path":binary} if binary else {}))
        try:
            for origin,dest,day in LEGS:
                opts={"FDate":day,"ANum":"1","CNum":"0","INum":"0",
                      "SType":"0","IfRet":"false","MType":"0"}
                url=f"https://en.ch.com/flights/{origin}-{dest}.html?"+urlencode(opts)
                page=browser.new_page(locale="en-US")
                report={"route":origin+"→"+dest,"requested_day":day,
                        "provider":"spring_official_public_calendar",
                        "bookable_verified":False,"taxes_verified":False}
                try:
                    resp=page.goto(url,wait_until="domcontentloaded",timeout=21000)
                    page.wait_for_timeout(2400)
                    result=page.evaluate(JS)
                    report.update({
                        "http_status":resp.status if resp else None,
                        "host":urlparse(page.url).hostname,
                        **result,
                    })
                    report["date_accurate"]=(
                        result.get("chosen_fdate")==day
                        and result.get("shown_departureDate")==day)
                    if not report["date_accurate"]:
                        report["calendar_price"]=None
                except Exception as exc:
                    report["error_type"]=type(exc).__name__
                finally:page.close()
                outputs.append(report)
                print(json.dumps(report,ensure_ascii=False),flush=True)
        finally:browser.close()
    step=os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step,"a",encoding="utf8") as f:
            f.write("# 春秋官方日期低价日历 · 六组往返（仅研究）\n\n")
            f.write("只读公开网页；日期、机场匹配后仍只是**日历参考价**，不是库存/含税/可出票价。\n\n")
            f.write("| 日期 | 航段 | HTTP | 所选日期准确 | 日历报价 | 航班明细条目 |\n")
            f.write("|---|---|---:|---|---:|---:|\n")
            for x in outputs:
                f.write("| "+x["requested_day"]+" | "+x["route"]+" | "+
                        str(x.get("http_status") or x.get("error_type") or "—")+
                        " | "+str(x.get("date_accurate"))+
                        " | "+str(x.get("calendar_price") or "—")+
                        " | "+str(x.get("row_count","—"))+" |\n")
            f.write("\n此实验无外部购买/支付/写入监控行为。完成时间（北京时间）："+
                    datetime.now(BJT).isoformat(timespec="seconds")+"\n")

if __name__=="__main__":
    main()
