#!/usr/bin/env python3
"""Single-date versus interval fallback probe. Diagnostic only, no alerts."""
import json, os, subprocess, time
from collections import Counter
if not os.environ.get("FLYAI_API_KEY"):
    raise SystemExit("Missing FLYAI_API_KEY")
ranges=[("dec23_overlap","2026-12-22","2026-12-23"),("dec31_overlap","2026-12-30","2026-12-31")]
with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as summary:
    summary.write("## Two-day return-date interval diagnostics (not an alert)\n\n")
    for label,start,end in ranges:
        cmd=["flyai","search-flight","--origin","AAT","--destination","TFU",
             "--dep-date-start",start,"--dep-date-end",end,"--sort-type","3"]
        try:
            proc=subprocess.run(cmd,text=True,capture_output=True,timeout=25)
            obj=json.loads(proc.stdout)
            raw=(obj.get("data") or {}).get("itemList") if isinstance(obj.get("data"),dict) else []
            if not isinstance(raw,list):raw=[]
            dated=[]
            for item in raw:
                if not isinstance(item,dict):continue
                journeys=item.get("journeys") or []
                if journeys and isinstance(journeys[0],dict):
                    segments=journeys[0].get("segments") or []
                    if segments and isinstance(segments[0],dict):
                        dated.append(str(segments[0].get("depDateTime") or "")[:10])
            counts=dict(Counter(dated))
            data={"label":label,"api_status":obj.get("status"),"message":str(obj.get("message") or "")[:100],
                  "raw_offer_count":len(raw),"flight_days_in_payload":counts,"cli_exit":proc.returncode}
        except (ValueError, subprocess.TimeoutExpired) as exc:
            data={"label":label,"error_type":type(exc).__name__}
        print(json.dumps(data,ensure_ascii=False),flush=True)
        summary.write("- "+label+": "+json.dumps(data,ensure_ascii=False)+"\n")
        time.sleep(1)
    summary.write("\nRange search results are global Top 10 across days; any missing date is a data gap, not no flights.\n")
