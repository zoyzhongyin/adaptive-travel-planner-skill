"""No-network test for Google CNY visibility and privacy."""
import unittest,json
from scripts import build_fare_dashboard as pub

D="2026-12-09";R="2026-12-14"
CONF={"rest_windows":[{"id":"w","start":D,"end":D}],
      "departure_dates":[D],"stay_nights":5,
      "alert_price_cny":1500,"ideal_price_cny":1200}

def sample(*,currency="CNY",total="1900"):
 return {"source":"google_flights_public_cny","schema_version":1,
         "currency":currency,"currency_requested":"CNY",
         "generated_at_bjt":"2026-10-31T10:10:00+08:00",
         "taxes_verified":False,"cabin_verified":False,"bookability_verified":False,
         "itineraries":[{"departure":D,"return_date":R,
           "status":"priced_reference","checked_at_bjt":"2026-10-31T10:10:00+08:00",
           "total_cny":total,"outbound":{"flight":"9C6685","airline":"春秋","price_cny":"920"},
           "return":{"flight":"9C6686","airline":"春秋","price_cny":"980"},
           "internal_detail":"SHOULD_NOT_LEAK"}]}
class GoogleDashboard(unittest.TestCase):
 def test_valid_cny_only(self):
  r=pub.snapshot(CONF,{},google=sample())
  x=r["itineraries"][0]["other_sources"][0]
  self.assertEqual(x["source"],"Google Flights（CNY）")
  self.assertEqual(x["total_cny"],"1900")
  self.assertFalse(x["taxes_verified"]);self.assertFalse(x["bookability_verified"])
  self.assertNotIn("SHOULD_NOT_LEAK",json.dumps(r))
 def test_wrong_currency_or_sum_rejected(self):
  for x in (sample(currency="USD"),sample(total="500")):
   self.assertEqual(pub.snapshot(CONF,{},google=x)["itineraries"][0]["other_sources"],[])
if __name__=="__main__":unittest.main()
