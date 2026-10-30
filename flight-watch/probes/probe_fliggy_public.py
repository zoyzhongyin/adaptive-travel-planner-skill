"""One-time FlyPig public-page probe; no login or challenge bypass."""
import json, sys
from datetime import datetime, timezone
from urllib.parse import quote
from playwright.sync_api import sync_playwright
sys.path.insert(0, "/tmp/ticket")
from crawlers.fliggy import FliggyCrawler
LEGS=[("TFU","AAT","2026-12-09"),("AAT","TFU","2026-12-14")]
def report(leg,status,rows,detail,url):
 print("PROBE_JSON "+json.dumps({"source":"fliggy_public_pc","date":leg[2],"origin":leg[0],"destination":leg[1],"checked_at_utc":datetime.now(timezone.utc).isoformat(),"status":status,"match_count":len(rows),"matches":rows[:8],"detail":detail[:150],"page_url":url[:140],"taxes_verified":False,"bookability_verified":False},ensure_ascii=False),flush=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(locale="zh-CN",viewport={"width":1440,"height":900})
 for leg in LEGS:
  ori,dst,date=leg
  fc,tc=("CTU" if ori=="TFU" else ori),("CTU" if dst=="TFU" else dst)
  fn,tn=("成都" if ori=="TFU" else "阿勒泰"),("成都" if dst=="TFU" else "阿勒泰")
  url=f"https://sjipiao.fliggy.com/flight_search_result.htm?tripType=0&depCity={fc}&arrCity={tc}&depDate={date}&depCityName={quote(fn)}&arrCityName={quote(tn)}"
  try:
   page.goto(url,wait_until="domcontentloaded",timeout=30000,referer="https://www.fliggy.com/")
   chunks=[]
   for _ in range(4):
    page.wait_for_timeout(1500)
    chunks.append(page.inner_text("body",timeout=8000))
    if any(t in page.url for t in ("captcha","passport","login.taobao")):break
    page.mouse.wheel(0,1200)
   if any(t in page.url for t in ("captcha","passport","login.taobao")):
    report(leg,"login_or_verification",[],"Redirected to verification/login",page.url);continue
   data=FliggyCrawler._parse_pc_text("\n@@@\n".join(chunks),date)
   valid=[]
   for r in data:
    dep,arr=str(r.get("depAirport") or ""),str(r.get("arrAirport") or "")
    good_dep=("天府" in dep) if ori=="TFU" else (("阿勒泰" in dep) or ("雪都" in dep))
    good_arr=("天府" in arr) if dst=="TFU" else (("阿勒泰" in arr) or ("雪都" in arr))
    if not good_dep or not good_arr or not r.get("code") or r.get("transCity") or r.get("stopover") or "/" in str(r["code"]):continue
    try:price=float(r.get("price") or 0)
    except:continue
    if price>0:valid.append({"flight":r["code"],"price_cny_reference":price,"dep_time":r.get("depTime"),"dep_airport":dep,"arr_airport":arr,"cabin":r.get("cabin") or "unknown"})
   valid.sort(key=lambda x:x["price_cny_reference"])
   report(leg,"priced_reference" if valid else "no_verified_match",valid,f"parsed_rows={len(data)},len={sum(map(len,chunks))}",page.url)
  except Exception as e:report(leg,"query_error",[],f"{type(e).__name__}: {str(e)[:100]}",page.url)
 browser.close()
