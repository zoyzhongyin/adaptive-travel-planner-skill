"""Recheck Meituan public flight result pages and passive in-browser responses.
No login, private API replay, booking, account data, or evasion.
"""
import json
from datetime import datetime,timezone
from urllib.parse import quote,urlparse
from playwright.sync_api import sync_playwright
BASE="https://i.meituan.com/awp/hfe/hfe-dianping-flight/list/index.html"
ROUTES=[
 ("TFU","AAT","2026-12-09","CTU","AAT","成都","阿勒泰"),
 ("AAT","TFU","2026-12-14","AAT","CTU","阿勒泰","成都"),
 ("TFU","AAT","2026-12-18","CTU","AAT","成都","阿勒泰"),
]
def emit(row,**data):
 print("MEITUAN_LIST "+json.dumps({"checked_utc":datetime.now(timezone.utc).isoformat(),
  "leg":{"origin":row[0],"dest":row[1],"date":row[2]},
  **data},ensure_ascii=False),flush=True)
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 for row in ROUTES:
  a,d,date,ca,cd,an,dn=row
  url=(f"{BASE}?h5_source=meituan&date={date}&arrive={cd}&depart={ca}"
       f"&from={quote(an)}&to={quote(dn)}&h5=1")
  ctx=b.new_context(viewport={"width":390,"height":844},locale="zh-CN",is_mobile=True,has_touch=True)
  page=ctx.new_page()
  events=[]
  def listener(resp):
   up=urlparse(resp.url)
   if "meituan" not in up.hostname and "dianping" not in up.hostname:return
   path=up.path.lower()
   if not any(t in path for t in ("flight","search","ticket","price","list")):return
   event={"path":up.path[:120],"status":resp.status,
      "type":resp.headers.get("content-type","")[:70]}
   if "getflightwiththreecode" in path or "getlowpricecalendar" in path:
    try:
     doc=resp.json()
     if isinstance(doc,dict):
      event["keys"]=list(doc)[:14]
      event["error_fields"]={k:str(doc[k])[:90] for k in ("code","status","msg","message","success","errorCode") if k in doc and isinstance(doc[k],(str,int,bool))}
      node=doc.get("data")
      event["data_type"]=type(node).__name__
      if isinstance(node,dict):
       event["data_keys"]=list(node)[:18]
       event["data_list_counts"]={k:len(v) for k,v in node.items() if isinstance(v,list)}
      elif isinstance(node,list):event["data_list_count"]=len(node)
    except Exception as exc:event["parse_error"]=type(exc).__name__
   events.append(event)
  page.on("response",listener)
  try:
   res=page.goto(url,wait_until="domcontentloaded",timeout=22000)
   page.wait_for_timeout(9600)
   body=page.inner_text("body",timeout=7000)[:2300]
   emit(row,status="page_inspected",http=res.status if res else None,
        final_url=page.url,body=body,
        observed_responses=events[:14],flight_verified=False,
        taxes_verified=False,bookability_verified=False)
  except Exception as e:
   emit(row,status="error",detail=f"{type(e).__name__}: {str(e)[:130]}",flight_verified=False)
  finally:ctx.close()
 b.close()
