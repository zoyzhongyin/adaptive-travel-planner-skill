"""Public dashboard inclusion and privacy guard for Fliggy PC."""
import json,unittest
from scripts import build_fare_dashboard as pub
D="2026-12-09"; R="2026-12-14"
CONFIG={"rest_windows":[{"id":"w","start":D,"end":D}],"departure_dates":[D],
        "stay_nights":5,"alert_price_cny":1500,"ideal_price_cny":1200}
def payload(*,total="1620",code="9C6686",status="priced_reference"):
 return {"schema_version":1,"source":"fliggy_pc_public_listing",
         "generated_at_bjt":"2026-10-31T09:40:00+08:00",
         "taxes_verified":False,"bookability_verified":False,"cabin_verified":False,
         "itineraries":[{"departure":D,"return_date":R,"status":status,
             "checked_at_bjt":"2026-10-31T09:40:00+08:00","total_cny":total,
             "outbound":{"flight":"9C6685","airline":"春秋","price_cny":"780"},
             "return":{"flight":code,"airline":"春秋","price_cny":"840"},
             "private_debug":"MUST_NOT_PUBLISH"}]}
class FliggyDashboard(unittest.TestCase):
 def test_valid_rows_sanitized(self):
  o=pub.snapshot(CONFIG,{},fliggy=payload())
  f=o["itineraries"][0]["other_sources"][0]
  self.assertEqual(f["source"],"飞猪网页")
  self.assertEqual(f["total_cny"],"1620")
  self.assertFalse(f["taxes_verified"])
  self.assertFalse(f["bookability_verified"])
  self.assertNotIn("MUST_NOT_PUBLISH",json.dumps(o))
 def test_invalid_or_incomplete_does_not_claim_bookable(self):
  for x in (payload(total="5"),payload(code="UNKNOWN")):
   o=pub.snapshot(CONFIG,{},fliggy=x)
   self.assertEqual(o["itineraries"][0]["other_sources"],[])
  incomplete=payload(status="incomplete")
  incomplete["itineraries"][0]["total_cny"]=None
  o=pub.snapshot(CONFIG,{},fliggy=incomplete)
  self.assertEqual(o["itineraries"][0]["other_sources"][0]["status"],"incomplete")
  self.assertIsNone(o["itineraries"][0]["other_sources"][0]["total_cny"])
if __name__=="__main__":unittest.main()
