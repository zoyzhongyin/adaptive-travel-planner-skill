#!/usr/bin/env python3
"""One-off FlyAI return-leg A/B diagnostic; prints no secrets or booking links.

Only makes six queries, no fare alerts or state mutations. A successful
response is still only a reference fare; it is not an issued ticket.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone, timedelta

BJT=timezone(timedelta(hours=8))
checks=[
  ("return_baseline_economy","AAT","TFU","2026-12-14","3","经济舱",None),
  ("return_baseline_without_cabin","AAT","TFU","2026-12-14","3",None,None),
  ("return_recommended_sort","AAT","TFU","2026-12-14","2",None,None),
  ("return_specific_flight","AAT","TFU","2026-12-14","3",None,"9C6686"),
  ("return_other_date","AAT","TFU","2026-12-23","3",None,None),
  ("outbound_control","TFU","AAT","2026-12-09","3","经济舱",None),
]
def run():
  if not os.environ.get("FLYAI_API_KEY"):
    raise RuntimeError("FLYAI_API_KEY GitHub secret is missing")
  reports=[]
  for label,a,b,day,sort,cabin,flight in checks:
    cmd=["flyai","search-flight","--origin",a,"--destination",b,"--dep-date",day,"--sort-type",sort]
    if cabin: cmd+=["--seat-class-name",cabin]
    if flight: cmd+=["--transport-no",flight]
    try:
      x=subprocess.run(cmd,capture_output=True,text=True,timeout=25,check=False)
      try:
        data=json.loads(x.stdout)
        if not isinstance(data,dict):data={}
      except ValueError: data={}
      records=data.get("data") if isinstance(data.get("data"),dict) else {}
      raw=records.get("itemList") if isinstance(records.get("itemList"),list) else []
      valid=sum(1 for i in raw if isinstance(i,dict) and i.get("ticketPrice"))
      report={"label":label,"date":day,"origin":a,"destination":b,
          "cli_exit":x.returncode,"status":data.get("status"),"message":str(data.get("message") or "")[:90],
          "system_message_present":bool(data.get("systemMessage")),"raw_items":len(raw),"price_items":valid,
          "stderr_nonempty":bool(x.stderr)}
    except (subprocess.TimeoutExpired,FileNotFoundError) as e:
      report={"label":label,"status":"command_failure","error_type":type(e).__name__}
    reports.append(report)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    time.sleep(1)
  result={"measured_at_bjt":datetime.now(BJT).isoformat(timespec="seconds"),"tests":reports,
    "note":"Diagnostic only; no alerts, credentials, bookings, state writes or market-price assumptions."}
  with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf8") as f:
    f.write("# FlyAI 阿勒泰返程 A/B 参数诊断\n\n")
    f.write("| 参数组 | API 状态 | 原始结果 | 有票价条目 |\n|---|---|---:|---:|\n")
    for r in reports:
      f.write("| "+r["label"]+" | "+str(r.get("status"))+" | "+str(r.get("raw_items","—"))+" | "+str(r.get("price_items","—"))+" |\n")
    f.write("\n本实验不能单独确认风控/额度，更不能证明某个航班没有航班库存。\n")
if __name__=="__main__": run()
