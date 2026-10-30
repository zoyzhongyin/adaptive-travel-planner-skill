"""One-off read-only Qunar H5 via a normal browser, no challenge bypass."""
import sys,json
from datetime import datetime,timezone
from urllib.parse import quote
from playwright.sync_api import sync_playwright
sys.path.insert(0,"/tmp/ticket")
from crawlers.qunar import QunarCrawler
def emit(route,status,rows,info,url):
 print("PROBE_JSON "+json.dumps(dict(source="qunar_h5",route=route,status=status,matches=rows[:7],count=len(rows),detail=info[:180],url=url[:120],checked_at=datetime.now(timezone.utc).isoformat(),taxes_verified=False,bookability_verified=False),ensure_ascii=False),flush=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page(locale="zh-CN",viewport={"width":1000,"height":950})
 for o,d,day in [("TFU","AAT","2026-12-09"),("AAT","TFU","2026-12-14")]:
  a="成都" if o=="TFU" else "阿勒泰"
  b="成都" if d=="TFU" else "阿勒泰"
  url=f"https://m.flight.qunar.com/ncs/page/flightlist?depCity={quote(a)}&arrCity={quote(b)}&goDate={day}&from=touch_index_search&child=0&baby=0&cabinType=0"
  seen=[]
  def capture(res):
   if "touchInnerList" in res.url:
    try:seen.append((res.status,res.text()))
    except Exception:seen.append((0,""))
  page.on("response",capture)
  try:
   page.goto(url,wait_until="domcontentloaded",timeout=30000)
   for _ in range(7):
    page.wait_for_timeout(1500)
    if seen:break
   if any(v in (403,429,451) or '"code":1999' in z.replace(" ","") for v,z in seen):
    emit(day,"access_limited",[],f"API blocked; count={len(seen)}",page.url);break
   raw=[]
   for _,body in seen:raw.extend(QunarCrawler._parse_response_flights(body))
   rows=[]
   for f in raw:
    if str(f.get("depAirportCode") or "").upper()!=o or str(f.get("arrAirportCode") or "").upper()!=d or str(f.get("depDate") or "")[:10]!=day or f.get("transCity") or f.get("stopover") or "/" in str(f.get("code") or ""):continue
    try:val=float(f.get("price") or 0)
    except:continue
    if val>0:rows.append(dict(flight=f.get("code"),price_cny_reference=val,dep=f.get("depAirport"),arr=f.get("arrAirport")))
   rows.sort(key=lambda x:x["price_cny_reference"])
   emit(day,"priced_reference" if rows else "no_valid_match",rows,f"responses={len(seen)},parsed={len(raw)}",page.url)
  except Exception as e:emit(day,"query_error",[],f"{type(e).__name__}: {str(e)[:120]}",page.url)
  finally:page.remove_listener("response",capture)
 browser.close()
