#!/usr/bin/env python3
"""Test GitHub's FlyAI secret and three planned itineraries, without exposing it."""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.flight_fare_query import query, OUT_DIR

def cheapest_direct(leg):
    prices=[Decimal(o["price_cny_reference"]) for o in leg.get("offers",[]) if o.get("direct")]
    return min(prices) if prices else None

def run():
    if not os.environ.get("FLYAI_API_KEY"):
        raise RuntimeError("FLYAI_API_KEY secret missing from GitHub Actions environment")
    OUT_DIR.mkdir(exist_ok=True)
    cases=[
        ("dec05_out","TFU","AAT",date(2026,12,5)),
        ("dec10_ret","AAT","TFU",date(2026,12,10)),
        ("dec14_out","TFU","AAT",date(2026,12,14)),
        ("dec19_ret","AAT","TFU",date(2026,12,19)),
        ("dec23_out","TFU","AAT",date(2026,12,23)),
        ("dec28_ret","AAT","TFU",date(2026,12,28)),
        ("reference_target","TFU","AAT",date(2026,12,8)),
        ("reference_mainstream","成都","北京",date(2026,11,10))
    ]
    result={}
    lines=["# 飞猪正式密钥查价实测","**GitHub 已提供 FLYAI_API_KEY 环境变量；这不代表上游已认可授权。**",""]
    for name,a,b,day in cases:
        obj=query(a,b,day,name)
        options=obj.get("offers", [])
        p=cheapest_direct(obj)
        result[name]={"status":obj.get("api_status"),"message":str(obj.get("api_message") or "")[:120],
                      "cli_exit":obj.get("cli_exit"),"raw_offer_count":obj.get("raw_offer_count",0),
                      "parsed_options":len(options),"cheapest_direct_cny":str(p) if p is not None else None,
                      "query_error":obj.get("error")}
        lines.append("- "+name+" "+day.isoformat()+": status="+str(obj.get("api_status"))
                     +"，候选="+str(len(options))+"，最低直飞="+("¥"+str(p) if p is not None else "无数据")
                     +"，提示="+str(obj.get("api_message") or "")[:80])
    for prefix,a,b in [("12月05–10","dec05_out","dec10_ret"),
                       ("12月14–19","dec14_out","dec19_ret"),
                       ("12月23–28","dec23_out","dec28_ret")]:
        pa,pb=result[a]["cheapest_direct_cny"],result[b]["cheapest_direct_cny"]
        lines.append("- **"+prefix+" 直飞双程参考价：**"
                     + ("¥"+str(Decimal(pa)+Decimal(pb)) if pa is not None and pb is not None
                        else "无法计算（至少一个航段无有效报价）"))
    lines += ["","参考价为两张单程最低直飞票价简单相加，非最终含税、行李、雪具或库存确认。",
              "status=1 / 无报价不表示航班不存在。",
              "测试不调用微信推送，也不更新正式提醒去重状态。"]
    text="\n".join(lines)+"\n"
    print(text,flush=True)
    with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:f.write(text)
    (OUT_DIR/"safe-key-check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if all(result[x]["cheapest_direct_cny"] is None for x in result):
        print("::warning title=FlyAI returned no direct fares::Check key authorization or account quota; no deal alert.")
    elif any(result[x]["cheapest_direct_cny"] is None for x in ["dec05_out","dec10_ret","dec14_out","dec19_ret","dec23_out","dec28_ret"]):
        print("::warning title=Some monitored legs unavailable::Cannot verify a complete roundtrip price for all dates.")
if __name__=="__main__":
    run()
