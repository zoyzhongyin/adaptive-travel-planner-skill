"""Multi-OTA dashboard price and privacy integration tests, no network."""
import json
import unittest
from scripts import build_fare_dashboard as pub

DEP="2026-12-09"
RET="2026-12-14"
CONFIG={"rest_windows":[{"id":"dec08","start":"2026-12-08","end":"2026-12-13"}],
        "departure_dates":[DEP],"stay_nights":5,
        "alert_price_cny":1500,"ideal_price_cny":1200}
STATE={"last_scan_results":{}}
def ctrip(*,price="1620",return_day=RET,flight="9C6686",source="ctrip_browser_public_listing"):
    return {"source":source,"schema_version":1,
            "generated_at_bjt":"2026-10-31T09:00:00+08:00",
            "taxes_verified":False,"bookability_verified":False,"cabin_verified":False,
            "private_note":"TOP_SECRET_MUST_NOT_PUBLISH",
            "itineraries":[{"departure":DEP,"return_date":return_day,
              "status":"priced_reference","checked_at_bjt":"2026-10-31T09:00:00+08:00",
              "total_cny":price,
              "outbound":{"flight":"9C6685","airline":"春秋","price_cny":"780"},
              "return":{"flight":flight,"airline":"春秋","price_cny":"840"},
              "secret":"TOP_SECRET_MUST_NOT_PUBLISH"}]}
class TestMultiSourceDashboard(unittest.TestCase):
 def test_ctrip_shows_under_other_sources_only(self):
    obj=pub.snapshot(CONFIG,STATE,ctrip=ctrip())
    row=obj["itineraries"][0]
    self.assertIsNone(row["alternate"])
    self.assertEqual(row["other_sources"][0]["source"],"携程公开页面")
    self.assertEqual(row["other_sources"][0]["total_cny"],"1620")
    self.assertIs(row["other_sources"][0]["taxes_verified"],False)
    self.assertIs(row["other_sources"][0]["bookability_verified"],False)
    self.assertNotIn("TOP_SECRET_MUST_NOT_PUBLISH",json.dumps(obj))
 def test_invalid_route_sum_flight_or_unapproved_data_never_published(self):
    for obj in [ctrip(price="20"),ctrip(return_day="2026-12-15"),
                ctrip(flight="NOT_A_FLIGHT"),ctrip(source="unrecognized")]:
        s=pub.snapshot(CONFIG,STATE,ctrip=obj)
        self.assertEqual(s["itineraries"][0]["other_sources"],[])
 def test_missing_ctrip_keeps_previous_dashboard_contract(self):
    s=pub.snapshot(CONFIG,STATE)
    self.assertEqual(s["itineraries"][0]["other_sources"],[])
    self.assertIsNone(s["ctrip_generated_at_bjt"])
if __name__=="__main__":unittest.main()
