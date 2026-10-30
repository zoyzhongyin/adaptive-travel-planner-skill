"""Safety contract for sanitized multi-source dashboard; no web or provider calls."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from scripts import build_fare_dashboard as pub

ROOT = Path(__file__).resolve().parent.parent

def supplement(total="1740", carrier="9C", dest="2026-12-14"):
    return {
        "schema_version":1,
        "source":"tongcheng_public_listing",
        "generated_at_bjt":"2026-10-30T20:24:00+08:00",
        "taxes_verified":False,"bookability_verified":False,"cabin_verified":False,
        "private_unrelated_note":"DO-NOT-PUBLISH-SECRET",
        "itineraries":[{"departure":"2026-12-09","return_date":dest,
            "status":"priced_reference","checked_at_bjt":"2026-10-30T20:24:00+08:00",
            "total_cny":total,
            "outbound":{"flight":"9C6685","airline":"春秋","price_cny":"840"},
            "return":{"flight":"9C6686","airline":"春秋","price_cny":"900"},
            "diagnostic":{"cookie":"DO-NOT-PUBLISH-SECRET"}}]
    }

class PublicSnapshotTests(unittest.TestCase):
    def test_valid_source_is_sanitized_and_never_implies_bookability(self):
        config={"rest_windows":[{"id":"dec08","start":"2026-12-08","end":"2026-12-13"}],
                "departure_dates":["2026-12-09"],"stay_nights":5,
                "alert_price_cny":1500,"ideal_price_cny":1200}
        state={"last_scan_results":{"2026-12-09":{
            "status":"incomplete_no_reliable_roundtrip_price",
            "checked_at_bjt":"2026-10-30T20:07:00+08:00",
            "return_date":"2026-12-14"
        }}}
        output=pub.snapshot(config,state,supplement())
        row=output["itineraries"][0]
        self.assertEqual(row["status"],"incomplete")
        self.assertIsNone(row["total_cny"])
        alt=row["alternate"]
        self.assertEqual(alt["status"],"priced_reference")
        self.assertEqual(alt["total_cny"],"1740")
        self.assertEqual(alt["source"],"同程公开页面")
        self.assertIs(alt["bookability_verified"],False)
        self.assertIs(alt["taxes_verified"],False)
        self.assertNotIn("DO-NOT-PUBLISH-SECRET",json.dumps(output))

    def test_invalid_source_route_or_sum_is_not_published(self):
        original=supplement()
        bad_total=supplement(total="100")
        self.assertIsNone(pub.public_alternate(bad_total["itineraries"][0],
                        "2026-12-09","2026-12-14"))
        bad_route=supplement(dest="2026-12-15")
        self.assertIsNone(pub.public_alternate(bad_route["itineraries"][0],
                        "2026-12-09","2026-12-14"))
        bad_carrier=supplement()
        bad_carrier["itineraries"][0]["outbound"]["airline"]="国航"
        self.assertIsNone(pub.public_alternate(bad_carrier["itineraries"][0],
                        "2026-12-09","2026-12-14"))

    @unittest.skipUnless(shutil.which("node"),"Node not installed")
    def test_dashboard_inline_javascript_syntax(self):
        html=(ROOT/"flight-watch/dashboard/index.html").read_text(encoding="utf-8")
        self.assertIn("同程独立参考",html)
        self.assertIn("不触发微信低价提醒",html)
        start=html.index("<script>")+len("<script>")
        end=html.index("</script>",start)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"dashboard.js"
            path.write_text(html[start:end],encoding="utf-8")
            done=subprocess.run(["node","--check",str(path)],
                capture_output=True,text=True,timeout=10)
        self.assertEqual(done.returncode,0,done.stderr)

if __name__=="__main__":
    unittest.main()
