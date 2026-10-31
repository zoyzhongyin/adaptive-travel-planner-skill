"""Independent Google Flights source, explicitly quoted in CNY.

Public Google Flights search via MIT fli library; no APIs requiring keys,
account login, payment or booking. Fares are unverified reference prices.
"""
import json,os,sys,re
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from scripts import ctrip_snapshot as common

ROOT=Path(__file__).resolve().parent.parent
CONFIG=ROOT/"flight-watch/config.json"
OUTPUT=ROOT/"flight-watch/google-flights-latest.json"
SOURCE="google_flights_public_cny"
BJT=timezone(timedelta(hours=8))
CARRIERS={"CA":"国航","3U":"川航","9C":"春秋","CZ":"南航","MU":"东航",
          "MF":"厦航","G5":"华夏","EU":"成都航空"}

def strict_google_offers(raw,origin,dest,day):
    found={}
    for item in raw:
        try:
            legs=item.legs
            if not legs or len(legs)!=1 or item.stops!=0:continue
            s=legs[0]
            orig=s.departure_airport.name
            end=s.arrival_airport.name
            stamp=str(s.departure_datetime)
            if (orig,end)!=(origin,dest) or stamp[:10]!=day:continue
            code=s.airline.name.lstrip("_")
            flight=code+str(s.flight_number)
            if not re.fullmatch(r"[A-Z0-9]{2}\d{3,5}",flight):continue
            val=item.price
            if isinstance(val,bool):continue
            amount=Decimal(str(val))
            if not amount.is_finite() or not (0<amount<50000):continue
            carrier=flight[:2]
            if carrier not in CARRIERS:continue
            entry={"flight":flight,"carrier":carrier,"airline":CARRIERS[carrier],
                   "price_cny":str(amount),"departure_time":stamp,
                   "operating_flight":flight}
            key=(flight,stamp)
            if key not in found or amount<Decimal(found[key]["price_cny"]):
                found[key]=entry
        except (AttributeError,TypeError,InvalidOperation,ValueError):continue
    return sorted(found.values(),key=lambda x:Decimal(x["price_cny"]))

def scan(config,prior=None,now=None):
    from fli.models import Airport,FlightSearchFilters,FlightSegment,MaxStops,PassengerInfo,SeatType,SortBy,TripType
    from fli.search import SearchFlights
    def getter(a,b,d):
        try:
            filters=FlightSearchFilters(
                passenger_info=PassengerInfo(adults=1),
                flight_segments=[FlightSegment(
                    departure_airport=[[Airport[a],0]],
                    arrival_airport=[[Airport[b],0]],travel_date=d)],
                seat_type=SeatType.ECONOMY,stops=MaxStops.NON_STOP,
                sort_by=SortBy.CHEAPEST,trip_type=TripType.ONE_WAY)
            raw=SearchFlights().search(filters,currency="CNY",country="CN",language="zh-CN")
            valid=strict_google_offers(raw or [],a,b,d)
            print("Google CNY",d,a,b,len(valid),"valid matching flight rows",flush=True)
            return valid,(None if valid else "no_matching_CNY_listing")
        except Exception as e:
            print("Google source error",d,type(e).__name__,flush=True)
            return [],type(e).__name__
    out=common.snapshot(config,prior=prior,getter=getter,now=now)
    out["source"]=SOURCE
    out["currency"]="CNY"
    out["currency_requested"]="CNY"
    out["taxes_verified"]=False
    out["baggage_verified"]=False
    out["cabin_verified"]=False
    out["bookability_verified"]=False
    return out

if __name__=="__main__":
    conf=json.loads(CONFIG.read_text(encoding="utf-8"))
    old=json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    data=scan(conf,old)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    ok=sum(r["status"]=="priced_reference" for r in data["itineraries"])
    print(f"Independent Google Flights CNY: {ok}/6 complete; unverified bookability, no alerts.",flush=True)
    for r in data["itineraries"]:
        print("GOOGLE_CNY_PAIR "+json.dumps({"departure":r["departure"],"return_date":r["return_date"],"status":r["status"],"total_cny_reference":r["total_cny"],"outbound":r["outbound"],"return":r["return"]},ensure_ascii=False),flush=True)
