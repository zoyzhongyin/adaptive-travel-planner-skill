"""No-network safety checks for explicit-CNY Google Flights source."""
import unittest
from types import SimpleNamespace as S
from scripts import google_flights_snapshot as g

DAY="2026-12-09"
def flight(*,o="TFU",d="AAT",day=DAY,fn="6685",code="9C",price=920,stops=0,n=1):
 s=S(departure_airport=S(name=o),arrival_airport=S(name=d),
     departure_datetime=day+" 10:05:00",airline=S(name=code),flight_number=fn)
 return S(legs=[s]*n,stops=stops,price=price)

class GoogleCny(unittest.TestCase):
 def test_exact_one_stopless_economy_airport_and_day(self):
  got=g.strict_google_offers([flight(),flight(price=930),flight(code="_3U",fn="6573",price=1000)],"TFU","AAT",DAY)
  self.assertEqual([(x["flight"],x["price_cny"]) for x in got],[("9C6685","920"),("3U6573","1000")])
 def test_wrong_origin_dest_date_stop_and_currency_form(self):
  bad=[flight(o="CTU"),flight(d="KJI"),flight(day="2026-12-08"),flight(stops=1),
       flight(n=2),flight(price=-1),flight(price=float("nan")),
       flight(code="??",fn="invalid")]
  self.assertEqual(g.strict_google_offers(bad,"TFU","AAT",DAY),[])
 def test_opposite_direction(self):
  got=g.strict_google_offers([flight(o="AAT",d="TFU",day="2026-12-14",fn="6686",price=980)],
                             "AAT","TFU","2026-12-14")
  self.assertEqual(got[0]["price_cny"],"980")
if __name__=="__main__":unittest.main()
