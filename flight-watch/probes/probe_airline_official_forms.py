"""Inspect official airline public booking forms only; no login, payment or bypass."""
import argparse, json, re
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

SITES = {
 "spring": "https://www.ch.com/flights/",
 "sichuan": "https://flights.sichuanair.com/3uair/ibe/common/flightSearch.do",
 "airchina": "https://www.airchina.com.cn/",
}
p=argparse.ArgumentParser();p.add_argument("--airline",choices=sorted(SITES),required=True);a=p.parse_args()
def emit(**kw): print("OFFICIAL_DIAG "+json.dumps(dict(airline=a.airline,at_utc=datetime.now(timezone.utc).isoformat(),**kw),ensure_ascii=False),flush=True)
with sync_playwright() as pw:
 b=pw.chromium.launch(headless=True)
 page=b.new_page(locale="zh-CN",viewport={"width":1440,"height":980})
 try:
  resp=page.goto(SITES[a.airline],wait_until="domcontentloaded",timeout=30000)
  page.wait_for_timeout(3800)
  info=page.evaluate("""() => ({
    title:document.title,
    inputs:[...document.querySelectorAll('input,select')].filter(e=>e.getBoundingClientRect().width>0).slice(0,45).map(e=>({tag:e.tagName,type:e.type,id:e.id,name:e.name,placeholder:e.placeholder,cls:String(e.className).slice(0,100),outer:e.outerHTML.slice(0,180)})),
    buttons:[...document.querySelectorAll('button, [role=button],a')].filter(e=>e.getBoundingClientRect().width>0&&/查询|搜索|立即|预订|订票|往返|单程/.test(e.innerText||'')).slice(0,45).map(e=>({tag:e.tagName,txt:(e.innerText||'').trim().slice(0,60),id:e.id,cls:String(e.className).slice(0,110),href:e.getAttribute('href')})),
    body:(document.body.innerText||'').slice(0,2200)
   })""")
  emit(status="form_visible",http_status=resp.status if resp else None,url=page.url,info=info)
 except Exception as e:emit(status="error",error=f"{type(e).__name__}: {str(e)[:270]}",url=page.url)
 finally:b.close()
