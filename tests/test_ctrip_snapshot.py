"""Offline regression for Ctrip alternative-source integration."""
import unittest
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from scripts import ctrip_snapshot as c

DATE="2026-12-09"
BACK="2026-12-14"
BJT=timezone(timedelta(hours=8))
CONF={"origin":"TFU","destination":"AAT","direct_only":True,
      "stay_nights":5,"departure_dates":[DATE]}

def fare(*,a="TFU",b="AAT",day=DATE,code="9C6685",amount=780,cabin="Y",n=1):
    seg=NS(departure_airport_code=a,arrival_airport_code=b,
           departure_time=day+" 10:05:00",flight_no=code,operate_flight_no="")
    return NS(segments=[seg]*n,cabin=cabin,adult_price=amount)

class TestCtripSnapshot(unittest.TestCase):
 def test_accept_direct_economy_exacts(self):
    x=c.offers([fare(),fare(amount=800),fare(code="3U6573",amount=840)],"TFU","AAT",DATE)
    self.assertEqual([a["price_cny"] for a in x],["780","840"])
    self.assertEqual(x[0]["flight"],"9C6685")
 def test_reject_wrong_airport_stop_cabin_date_price(self):
    bad=[fare(a="CTU"),fare(b="KJI"),fare(day=BACK),fare(n=2),
         fare(cabin="C"),fare(amount=0),fare(amount=float("nan")),fare(code="FAKE")]
    self.assertEqual(c.offers(bad,"TFU","AAT",DATE),[])
 def test_missing_return_preserves_only_historical_and_never_triggers(self):
    prior={"itineraries":[{"departure":DATE,
                           "last_valid":{"checked_at_bjt":"old","total_cny":"1700"}}]}
    def getter(a,b,d):
        if a=="TFU":return c.offers([fare()],"TFU","AAT",DATE),None
        return [],"temporary_failure"
    x=c.snapshot(CONF,prior=prior,getter=getter,now=datetime(2026,10,31,tzinfo=BJT))
    r=x["itineraries"][0]
    self.assertEqual(r["status"],"incomplete")
    self.assertIsNone(r["total_cny"])
    self.assertEqual(r["last_valid"]["total_cny"],"1700")
    self.assertFalse(x["taxes_verified"])
    self.assertFalse(x["bookability_verified"])
 def test_complete_roundtrip_sum(self):
    def getter(a,b,d):
        if a=="TFU":return c.offers([fare()],"TFU","AAT",DATE),None
        return c.offers([fare(a="AAT",b="TFU",day=BACK,code="9C6686",amount=840)],"AAT","TFU",BACK),None
    x=c.snapshot(CONF,getter=getter,now=datetime(2026,10,31,tzinfo=BJT))
    self.assertEqual(x["itineraries"][0]["total_cny"],"1620")
 def test_never_expand_dates_or_airports(self):
    for kw in ({"origin":"CTU"},{"stay_nights":4},{"direct_only":False}):
        with self.assertRaises(ValueError):c.snapshot(dict(CONF,**kw),getter=lambda *args:([],None))
if __name__=="__main__":unittest.main()
