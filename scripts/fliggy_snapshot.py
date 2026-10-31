"""Fliggy PC public-page independently parsed flight listings.

Different technical channel from FlyAI; still the same Fliggy platform.
No booking, paid API, user login, CAPTCHA handling or auto-alerts.
"""
import json, os, re, sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote,urlparse

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from scripts import ctrip_snapshot as common

ROOT=Path(__file__).resolve().parent.parent
OUTPUT=ROOT/"flight-watch/fliggy-latest.json"
CONFIG=ROOT/"flight-watch/config.json"
SOURCE="fliggy_pc_public_listing"
BJT=timezone(timedelta(hours=8))

def clean_rows(raw,origin,destination,day):
    seen={}
    for r in raw:
        if not isinstance(r,dict):continue
        dep=str(r.get("depAirport") or "")
        arr=str(r.get("arrAirport") or "")
        dep_ok=("天府" in dep) if origin=="TFU" else ("雪都" in dep or "阿勒泰" in dep)
        arr_ok=("天府" in arr) if destination=="TFU" else ("雪都" in arr or "阿勒泰" in arr)
        no=str(r.get("code") or "").upper()
        tm=str(r.get("depTime") or "")
        cabin=str(r.get("cabin") or "")
        if (not dep_ok or not arr_ok or not re.fullmatch(r"[A-Z0-9]{2}\d{3,5}",no)
                or not re.match(r"^\d{2}:\d{2}",tm)
                or r.get("transCity") or r.get("stopover")
                or r.get("transfer") or cabin in ("公务舱","头等舱","商务舱")):
            continue
        try:
            fare=Decimal(str(r.get("price")))
            if not fare.is_finite() or not (0<fare<50000):continue
        except (InvalidOperation,TypeError,ValueError):continue
        carrier=no[:2]
        row={"flight":no,"carrier":carrier,
             "airline":{"CA":"国航","3U":"川航","9C":"春秋","CZ":"南航","MU":"东航",
                        "MF":"厦航","G5":"华夏","EU":"成都航空"}.get(carrier,carrier),
             "price_cny":str(fare),"departure_time":day+" "+tm[:5],
             "operating_flight":str(r.get("shareCarrier") or no)[:35]}
        key=(no,tm[:5])
        if key not in seen or fare<Decimal(seen[key]["price_cny"]):seen[key]=row
    return sorted(seen.values(),key=lambda x:Decimal(x["price_cny"]))

def snapshot(config,prior=None,now=None):
    from playwright.sync_api import sync_playwright
    sys.path.insert(0,os.environ.get("FLIGGY_PARSER_PATH","/tmp/ticket"))
    from crawlers.fliggy import FliggyCrawler
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True)
        page=b.new_page(locale="zh-CN",viewport={"width":1440,"height":900})
        def getter(a,d,day):
            fc="CTU" if a=="TFU" else a
            tc="CTU" if d=="TFU" else d
            fn="成都" if a=="TFU" else "阿勒泰"
            tn="成都" if d=="TFU" else "阿勒泰"
            url=("https://sjipiao.fliggy.com/flight_search_result.htm?"
                 f"tripType=0&depCity={fc}&arrCity={tc}&depDate={day}"
                 f"&depCityName={quote(fn)}&arrCityName={quote(tn)}")
            try:
                response=page.goto(url,wait_until="domcontentloaded",timeout=30000,
                                   referer="https://www.fliggy.com/")
                if (not response or response.status !=200
                    or urlparse(page.url).hostname!="sjipiao.fliggy.com"
                    or day not in page.url
                    or any(x in page.url for x in ("passport","captcha","login"))):
                    return [],"page_unavailable_or_date_mismatch"
                chunks=[]
                for _ in range(4):
                    page.wait_for_timeout(1500)
                    chunks.append(page.inner_text("body",timeout=8000))
                    page.mouse.wheel(0,1200)
                data=FliggyCrawler._parse_pc_text("\n@@@\n".join(chunks),day)
                valid=clean_rows(data,a,d,day)
                return valid,(None if valid else "no_strict_direct_listing")
            except Exception as exc:
                return [],type(exc).__name__
        try:
            data=common.snapshot(config,prior=prior,getter=getter,now=now)
        finally:
            b.close()
    data["source"]=SOURCE
    data["baggage_verified"]=False
    data["cabin_verified"]=False
    data["taxes_verified"]=False
    data["bookability_verified"]=False
    return data

if __name__=="__main__":
    config=json.loads(CONFIG.read_text(encoding="utf-8"))
    prior=json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    rows=snapshot(config,prior)
    OUTPUT.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    passed=sum(x["status"]=="priced_reference" for x in rows["itineraries"])
    print(f"FlyPig PC independent web listing: {passed}/6, prices unverified, NO alerts.")
