"""Read-only experimental source probes: Google Flights (explicit CNY) and China Southern calendar.

No login, hidden-cookie replay, fingerprint changes, booking or alerts.
"""
import json
from datetime import datetime,timezone

LEGS=[("TFU","AAT","2026-12-09"),("AAT","TFU","2026-12-14")]

def out(source,leg,status,rows=None,info=""):
 print("SOURCE_TEST "+json.dumps({"source":source,"origin":leg[0],"destination":leg[1],"date":leg[2],
 "checked_at_utc":datetime.now(timezone.utc).isoformat(),"status":status,"rows":(rows or [])[:12],
 "count":len(rows or []),"detail":str(info)[:220],"bookability_verified":False},ensure_ascii=False),flush=True)

def google():
 from fli.models import Airport,FlightSearchFilters,FlightSegment,MaxStops,PassengerInfo,SeatType,SortBy,TripType
 from fli.search import SearchFlights
 for a,b,day in LEGS:
  leg=(a,b,day)
  try:
   filters=FlightSearchFilters(
     passenger_info=PassengerInfo(adults=1),
     flight_segments=[FlightSegment(
       departure_airport=[[Airport[a],0]],
       arrival_airport=[[Airport[b],0]],travel_date=day)],
     seat_type=SeatType.ECONOMY,stops=MaxStops.NON_STOP,
     sort_by=SortBy.CHEAPEST,trip_type=TripType.ONE_WAY)
   # This is essential: pricing source specifies curr=CNY explicitly.
   flights=SearchFlights().search(filters,currency="CNY",country="CN",language="zh-CN")
   valid=[]
   for f in (flights or []):
    legs=getattr(f,"legs",[]) or []
    if len(legs)!=1 or getattr(f,"stops",None)!=0:continue
    seg=legs[0]
    o=getattr(getattr(seg,"departure_airport",None),"name","")
    d=getattr(getattr(seg,"arrival_airport",None),"name","")
    depart=str(getattr(seg,"departure_datetime","") or "")
    if (o,d)!=(a,b) or depart[:10]!=day:continue
    airline=getattr(getattr(seg,"airline",None),"name","")
    fn=airline.lstrip("_")+str(getattr(seg,"flight_number",""))
    amount=getattr(f,"price",None)
    if not isinstance(amount,(float,int)) or amount<=0:continue
    valid.append({"flight":fn,"price_cny_google_claim":amount,"currency_requested":"CNY",
       "departure":depart,"origin":o,"destination":d,"stops":0})
   valid.sort(key=lambda x:x["price_cny_google_claim"])
   out("google_flights_fli_CNY",leg,"priced_reference" if valid else "no_verified_match",valid,
       f"raw_results={len(flights or [])},CNY explicitly requested")
  except Exception as e:out("google_flights_fli_CNY",leg,"query_error",[],f"{type(e).__name__}: {str(e)[:145]}")

def csair():
 import urllib.request,re,json
 url="https://b2c.csair.cn/portal/minPrice/queryMinPriceInAirLines?jsoncallback=getMinPrice&inter=N&callback=getMinPrice"
 try:
  req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (price-calendar verification; one public GET)"})
  with urllib.request.urlopen(req,timeout=18) as res:
   body=res.read(2_000_000).decode("utf-8","replace")
   http=res.status
  m=re.match(r"^\s*\w+\((.*)\)\s*;?\s*$",body,re.S)
  if not m:
   out("csair_public_calendar",LEGS[0],"non_jsonp_response",[],f"http={http},bytes={len(body)},starts={body[:65]!r}");return
  data=json.loads(m.group(1))
  matches=[]
  for ff in data.get("FROMOFLIGHTS",[]):
   if not isinstance(ff,dict) or ff.get("DEPCITY") not in ("CTU","TFU"):continue
   for it in ff.get("FLIGHT",[]) or []:
    if not isinstance(it,dict) or it.get("ARCITY")!="AAT":continue
    day=str(it.get("DEPDATE") or "")
    if day not in ("2026-12-08","2026-12-09","2026-12-17","2026-12-18","2026-12-26","2026-12-27"):continue
    try: val=float(it.get("MINPRICE") or 0)
    except (TypeError,ValueError):continue
    if val>0:matches.append({"date":day,"price":val,"market":"CZ city-level calendar; no airport/flight verified","origin_city":ff["DEPCITY"],"dest_city":"AAT"})
  out("csair_public_calendar",LEGS[0],"date_price_lead_only" if matches else "no_route_calendar_price",
       matches,f"http={http},bytes={len(body)},rows={len(data.get('FROMOFLIGHTS',[]))}; not a specific flight")
 except Exception as e:out("csair_public_calendar",LEGS[0],"query_error",[],f"{type(e).__name__}: {str(e)[:180]}")

if __name__=="__main__":
 import sys
 (google if len(sys.argv)>1 and sys.argv[1]=="google" else csair)()
