"""One-off Tuniu public-page fare test. Does not bypass access controls."""
import json, re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

LEGS = [("TFU", "AAT", "2026-12-09"), ("AAT", "TFU", "2026-12-14")]
JS = """() => [...document.querySelectorAll('.J-flightlist')].map(el => {
 const t=s=>{const e=el.querySelector(s);return e?(e.innerText||'').trim():''};
 return {fn:t('.flihtnumber'),airline:t('.aircom'),
 dep:t('.fl-departInf .hours'),depAir:t('.fl-departInf .airport'),
 arr:t('.fl-arriveInf .hours'),arrAir:t('.fl-arriveInf .airport'),
 price:t('.price'),duration:t('.durationTime'),
 row:(el.innerText||'').slice(0,280)};
})"""

def emit(channel, leg, status, matches=None, detail="", page_url=""):
 print("PROBE_JSON "+json.dumps(dict(channel=channel,origin=leg[0],destination=leg[1],
  date=leg[2],status=status,checked_at_utc=datetime.now(timezone.utc).isoformat(),
  count=len(matches or []),matches=(matches or [])[:12],detail=detail[:200],
  page_url=page_url[:200],taxes_verified=False,bookability_verified=False),
  ensure_ascii=False),flush=True)

def check(row, leg):
 dep_air,arr_air = row.get("depAir",""),row.get("arrAir","")
 o,d,date=leg
 match_from=("天府" in dep_air) if o=="TFU" else ("雪都" in dep_air or "阿勒泰" in dep_air)
 match_to=("天府" in arr_air) if d=="TFU" else ("雪都" in arr_air or "阿勒泰" in arr_air)
 fn=re.search(r"([A-Z0-9]{2}\d{3,4})",row.get("fn",""))
 price=re.search(r"[￥¥]\s*([\d,]+(?:\.\d+)?)",row.get("price",""))
 t=re.search(r"^\d{2}:\d{2}",row.get("dep",""))
 return bool(match_from and match_to and fn and price and t and not re.search(r"中转|经停",row.get("row","")))

def desktop(browser,leg):
 o,d,date=leg
 a="CTU" if o=="TFU" else "AAT"
 b="CTU" if d=="TFU" else "AAT"
 url=f"https://flight.tuniu.com/domestic/list/{a}_{b}_ST_1_0_0/?start={date}"
 page=browser.new_page(locale="zh-CN",viewport={"width":1366,"height":900})
 try:
  resp=page.goto(url,wait_until="domcontentloaded",timeout=35000)
  page.wait_for_timeout(4200)
  raw=page.evaluate(JS) or []
  if not raw:
   page.mouse.wheel(0,1400);page.wait_for_timeout(1700)
   raw=page.evaluate(JS) or []
  body=page.inner_text("body",timeout=6000)[:1500]
  if re.search("验证码|人机验证|滑动验证|安全验证|请登录",body):
   emit("tuniu_pc",leg,"login_or_verification",detail=f"HTTP {resp.status if resp else '?'}; cards={len(raw)}",page_url=page.url);return False
  good=[]
  for r in raw:
   if not check(r,leg):continue
   number=re.search(r"([A-Z0-9]{2}\d{3,4})",r["fn"]).group(1)
   fare=float(re.search(r"[￥¥]\s*([\d,]+(?:\.\d+)?)",r["price"]).group(1).replace(",",""))
   if fare<100 or fare>50000:continue
   good.append({"flight":number,"price_cny_reference":fare,"dep_airport":r["depAir"],
     "arr_airport":r["arrAir"],"dep_time":r["dep"][:5],"fare_label":r["price"][:90]})
  good.sort(key=lambda x:x["price_cny_reference"])
  date_ok=date in page.url
  status="priced_reference" if good and date_ok else ("date_not_verified" if good else "no_verified_match")
  emit("tuniu_pc",leg,status,good,
    f"HTTP {resp.status if resp else '?'}; rendered_cards={len(raw)}; date_in_url={date_ok}; page_title={page.title()[:60]}",
    page.url)
  return bool(good and date_ok)
 except Exception as e:
  emit("tuniu_pc",leg,"query_error",detail=f"{type(e).__name__}: {str(e)[:130]}",page_url=page.url)
  return False
 finally:page.close()

def mobile(browser,leg):
 o,d,date=leg
 a="CTU" if o=="TFU" else "AAT"
 b="CTU" if d=="TFU" else "AAT"
 url=f"https://m.tuniu.com/flight/domestic/new/{a}_{b}_OW_1_0_0?deptDate={date}&isGo=0"
 ctx=browser.new_context(viewport={"width":390,"height":844},locale="zh-CN",is_mobile=True,has_touch=True)
 page=ctx.new_page()
 samples=[]
 def on_resp(response):
  if "listFlight" in response.url:
   try:
    obj=response.json()
    payload=obj.get("data",{}) if isinstance(obj,dict) else {}
    samples.append({"http":response.status,"success":obj.get("success") if isinstance(obj,dict) else None,
      "code":obj.get("errorCode",obj.get("code")) if isinstance(obj,dict) else None,
      "fare_count":len(payload.get("fareList") or []) if isinstance(payload,dict) else 0})
   except Exception as exc:samples.append({"http":response.status,"error":type(exc).__name__})
 page.on("response",on_resp)
 try:
  resp=page.goto(url,wait_until="domcontentloaded",timeout=30000)
  page.wait_for_timeout(7000)
  body=page.inner_text("body",timeout=5000)[:1000]
  blocked=bool(re.search("验证码|人机验证|滑块验证|安全验证|请登录",body))
  emit("tuniu_h5_page",leg,"login_or_verification" if blocked else "no_verified_priced_flights",
    detail=f"HTTP {resp.status if resp else '?'}; responses={samples[:3]}; page_title={page.title()[:50]}",page_url=page.url)
 except Exception as exc:
  emit("tuniu_h5_page",leg,"query_error",detail=f"{type(exc).__name__}: {str(exc)[:125]}",page_url=page.url)
 finally:ctx.close()

with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 for leg in LEGS:
  passed=desktop(b,leg)
  if not passed:
   mobile(b,leg)
 b.close()
