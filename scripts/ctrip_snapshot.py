"""Ctrip public flight-listing reference; no booking or alerts."""
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import os
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.tongcheng_snapshot import validate_config

ROOT=Path(__file__).resolve().parent.parent
CONFIG=ROOT/"flight-watch/config.json"
OUTPUT=ROOT/"flight-watch/ctrip-latest.json"
BJT=timezone(timedelta(hours=8))
SOURCE="ctrip_browser_public_listing"

def offers(raw, origin, destination, day):
    found={}
    for f in raw:
        try:
            if len(f.segments)!=1 or str(f.cabin).upper() not in ("Y","ECONOMY","经济舱"):
                continue
            seg=f.segments[0]
            if (seg.departure_airport_code,seg.arrival_airport_code,str(seg.departure_time)[:10])!=(origin,destination,day):
                continue
            flight=str(seg.flight_no or "").upper()
            if not re.fullmatch(r"[A-Z0-9]{2}\d{3,5}",flight):continue
            v=f.adult_price
            if isinstance(v,bool):continue
            fare=Decimal(str(v))
            if not fare.is_finite() or not (0<fare<50000):continue
            carrier=flight[:2]
            row={"flight":flight,"carrier":carrier,
                 "airline":{"CA":"国航","3U":"川航","9C":"春秋","CZ":"南航","MU":"东航","MF":"厦航","G5":"华夏","EU":"成都航空"}.get(carrier,carrier),
                 "price_cny":str(fare),"departure_time":str(seg.departure_time),
                 "operating_flight":str(seg.operate_flight_no or flight)}
            key=(flight,str(seg.departure_time))
            if key not in found or fare<Decimal(found[key]["price_cny"]):found[key]=row
        except (AttributeError,TypeError,ValueError,InvalidOperation):
            continue
    return sorted(found.values(),key=lambda x:Decimal(x["price_cny"]))

def live_getter(crawler,origin,dest,day):
    error="no_valid_listing"
    for city in ([origin,"CTU"] if origin=="TFU" else [origin]):
        try:
            res=crawler.search(city,dest,day,include_transfer=False,include_shared=True,timeout_ms=22000)
            rows=offers(res.flights or [],origin,dest,day)
            if rows:return rows,None
            error=str(getattr(res,"error",None) or error)[:80]
        except Exception as exc:error=type(exc).__name__
    return [],error

def snapshot(config,prior=None,getter=None,now=None):
    pairs=validate_config(config)
    prior_map={x.get("departure"):x for x in (prior or {}).get("itineraries",[]) if isinstance(x,dict)}
    now=now or datetime.now(BJT)
    result=[]
    def run():
        for dep,ret in pairs:
            stamp=datetime.now(BJT).isoformat(timespec="seconds")
            legs=[];errors=[]
            for a,b,day in (("TFU","AAT",dep),("AAT","TFU",ret)):
                if dep<now.date().isoformat(): rows,err=[],"departure_in_past"
                else:rows,err=getter(a,b,day)
                # Even custom/fixture getters are never trusted without checks.
                safe=[]
                for row in rows or []:
                    try:
                        flight=row["flight"];amount=Decimal(str(row["price_cny"]))
                        if not (re.fullmatch(r"[A-Z0-9]{2}\d{3,5}",flight)
                                and 0<amount<50000 and amount.is_finite()
                                and str(row["departure_time"]).startswith(day)):continue
                        safe.append(row)
                    except (KeyError,TypeError,InvalidOperation,ValueError):pass
                safe.sort(key=lambda x:Decimal(str(x["price_cny"])))
                legs.append(safe)
                if not safe:errors.append(err or "no_valid_listing")
            out,back=legs
            total=Decimal(str(out[0]["price_cny"]))+Decimal(str(back[0]["price_cny"])) if out and back else None
            result.append({"departure":dep,"return_date":ret,
                "checked_at_bjt":stamp,"status":"priced_reference" if total is not None else "incomplete",
                "total_cny":str(total) if total is not None else None,
                "outbound":out[0] if out else None,"return":back[0] if back else None,
                "last_valid":({"checked_at_bjt":stamp,"total_cny":str(total)} if total is not None
                              else (prior_map.get(dep) or {}).get("last_valid")),
                "error_types":errors})
    if getter is None:
        sys.path.insert(0,os.environ.get("CTRIP_CRAWLER_PATH","/tmp/ctrip-ticket-crawler/browser_automation"))
        from flight_crawler import FlightCrawler
        with FlightCrawler(headless=True) as crawler:
            getter=lambda a,b,day:live_getter(crawler,a,b,day)
            run()
    else:run()
    return {"schema_version":1,"source":SOURCE,
        "generated_at_bjt":datetime.now(BJT).isoformat(timespec="seconds"),
        "taxes_verified":False,"cabin_verified":False,
        "baggage_verified":False,"bookability_verified":False,"itineraries":result}

if __name__=="__main__":
    c=json.loads(CONFIG.read_text(encoding="utf-8"))
    old=json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    data=snapshot(c,old)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    count=sum(i["status"]=="priced_reference" for i in data["itineraries"])
    print(f"Ctrip independent public fare: {count}/6 complete. Tax/booking unverified. NO alerts.")
