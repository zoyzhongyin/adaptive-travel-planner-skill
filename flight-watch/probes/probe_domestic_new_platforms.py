"""Read-only entry accessibility check for independent domestic flight platforms.
Only ordinary browser requests, no account, API replay, evasions, or booking.
"""
import json
from datetime import datetime,timezone
from playwright.sync_api import sync_playwright

SITES={
 "meituan_ticket_h5":"https://i.meituan.com/awp/hfe/hfe-dianping-flight/index/index.html?h5_source=meituan&h5=1",
 "meituan_ticket_promo":"https://i.meituan.com/awp/hfe/block/4324/index.html",
 "meituan_home":"https://www.meituan.com/",
 "zhixing_h5":"https://m.suanya.com/h5/index.html",
 "umetrip_direct_official":"https://m.umetrip.com/n/lFOI2I",
}
def emit(name,**k):
 print("ENTRY_PROBE "+json.dumps({"source":name,"checked_at_utc":datetime.now(timezone.utc).isoformat(),**k},ensure_ascii=False),flush=True)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 for name,url in SITES.items():
  ctx=browser.new_context(viewport={"width":390,"height":844},locale="zh-CN",is_mobile=True,has_touch=True)
  page=ctx.new_page()
  try:
   response=page.goto(url,wait_until="domcontentloaded",timeout=26000)
   page.wait_for_timeout(4300)
   data=page.evaluate("""() => ({
     title:document.title,
     body:(document.body?.innerText||'').slice(0,1800),
     links:[...document.querySelectorAll('a')].filter(e=>/机票|航班|预订|买票|flight/i.test((e.innerText||'')+' '+(e.getAttribute('href')||''))).slice(0,18).map(e=>({text:(e.innerText||'').slice(0,65),href:(e.href||'').slice(0,160)})),
     inputs:[...document.querySelectorAll('input')].filter(e=>e.getBoundingClientRect().width>0).slice(0,16).map(e=>({p:e.placeholder||'',type:e.type,value:String(e.value||'').slice(0,30)}))
   })""")
   emit(name,status="page_inspected",http_status=response.status if response else None,
       final_url=page.url,details=data,
       fare_found=False,bookability_verified=False)
  except Exception as exc:emit(name,status="access_error",error=f"{type(exc).__name__}: {str(exc)[:180]}",fare_found=False)
  finally:ctx.close()
 browser.close()
