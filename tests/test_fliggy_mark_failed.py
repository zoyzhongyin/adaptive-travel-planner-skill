import unittest
from datetime import datetime, timezone, timedelta
from scripts import fliggy_snapshot as f
from scripts import build_fare_dashboard as b

class MarkFailed(unittest.TestCase):
    def test_failure_is_explicit_and_old_price_not_current(self):
        # The checked-in latest file is runtime state and may already be incomplete.
        # This contract uses a priced prior so a later state commit cannot erase it.
        prior={
            "schema_version":1,
            "source":"fliggy_pc_public_listing",
            "generated_at_bjt":"2026-11-03T06:29:47+08:00",
            "itineraries":[{
                "departure":"2026-12-08","return_date":"2026-12-13",
                "status":"priced_reference","checked_at_bjt":"2026-11-03T06:29:47+08:00",
                "total_cny":"1790.0",
                "outbound":{"flight":"9C6685","airline":"春秋","price_cny":"900"},
                "return":{"flight":"9C6686","airline":"春秋","price_cny":"890"},
            }],
        }
        now=datetime(2026,11,3,16,40,43,tzinfo=timezone(timedelta(hours=8)))
        got=f.mark_failed(prior,"parser_install","41604992633",now)
        self.assertEqual(got["source_status"],"failed"); self.assertTrue(got["stale"])
        self.assertEqual(got["failure_stage"],"parser_install")
        self.assertEqual(got["last_success_generated_at_bjt"],prior["generated_at_bjt"])
        for row in got["itineraries"]:
            self.assertEqual(row["status"],"source_failed"); self.assertIsNone(row["total_cny"])
            self.assertTrue(row["error_types"][0].startswith("data_source_failed"))
        self.assertEqual(got["itineraries"][0]["last_valid"]["total_cny"],prior["itineraries"][0]["total_cny"])
        again=f.mark_failed(got,"parser_install","41604992634",now)
        self.assertEqual(again["last_success_generated_at_bjt"],prior["generated_at_bjt"])
        self.assertEqual(again["itineraries"][0]["last_valid"]["total_cny"],prior["itineraries"][0]["total_cny"])
        r=got["itineraries"][0]
        alt=b.public_alternate(r,r["departure"],r["return_date"],"飞猪网页")
        self.assertIsNotNone(alt); self.assertEqual(alt["status"],"incomplete"); self.assertIsNone(alt["total_cny"])
        self.assertEqual(alt["last_valid"]["total_cny"],b.clean_money(prior["itineraries"][0]["total_cny"]))

    def test_already_incomplete_file_keeps_its_historical_total(self):
        prior={
            "schema_version":1,
            "generated_at_bjt":"2026-11-08T16:06:17+08:00",
            "itineraries":[{
                "departure":"2026-12-08","return_date":"2026-12-13",
                "status":"incomplete","total_cny":None,
                "last_valid":{"checked_at_bjt":"2026-11-03T06:29:47+08:00","total_cny":"1790.0"},
            }],
        }
        now=datetime(2026,11,8,16,40,tzinfo=timezone(timedelta(hours=8)))
        got=f.mark_failed(prior,"parser_install","41604992633",now)
        self.assertIsNone(got["itineraries"][0]["total_cny"])
        self.assertEqual(got["itineraries"][0]["last_valid"]["total_cny"], "1790.0")
        self.assertNotEqual(got["itineraries"][0]["status"], "priced_reference")

if __name__=="__main__": unittest.main()
