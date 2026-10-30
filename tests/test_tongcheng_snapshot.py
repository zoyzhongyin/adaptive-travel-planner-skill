"""Offline safety regression tests for the supplemental public-listing provider."""
from datetime import datetime, timezone, timedelta
import unittest
from scripts import tongcheng_snapshot as tc

BJT = timezone(timedelta(hours=8))
DAY = "2026-12-09"
RETURN_DAY = "2026-12-14"
CONFIG = {"origin":"TFU","destination":"AAT","direct_only":True,
          "stay_nights":5,"departure_dates":[DAY]}

def item(*, flight="9C6685", dep="TFU", arr="AAT", day=DAY,
         fare=840, stops=0, airline="9C"):
    return {"no":flight, "airline_code":airline,
            "airport_dep":dep, "airport_arr":arr,
            "date":day, "stops":stops, "fare":fare}

class ParsingTests(unittest.TestCase):
    def test_exact_public_airport_day_nonstop_price_accepted_as_unverified(self):
        got = tc.valid_fare(item(), origin="TFU", destination="AAT", day=DAY)
        self.assertEqual(got["price_cny"], "840")
        self.assertEqual(got["airline"], "春秋")
        self.assertNotIn("taxes_verified", got)

    def test_wrong_airport_day_stop_airline_or_price_rejected(self):
        candidates = [
            item(dep="CTU"), item(arr="KJI"), item(day="2026-12-08"),
            item(stops=1), item(fare=-1), item(fare=0), item(fare="¥100"),
            item(fare=bool(True)), item(flight="MU1111",airline="MU"),
            item(airline="CA"), item(flight="9C9999", dep="AAT"),
        ]
        for case in candidates:
            self.assertIsNone(tc.valid_fare(case,origin="TFU",destination="AAT",day=DAY))

    def test_cheapest_is_real_exact_leg_not_wrong_airport_or_connecting(self):
        winner, accepted = tc.cheapest([
            item(flight="9C6685",fare=850),
            item(flight="3U6573",airline="3U",fare=820),
            item(flight="CA2505",airline="CA",fare=50,stops=1),
            item(flight="CA2505",airline="CA",fare=40,arr="CTU"),
        ], origin="TFU",destination="AAT",day=DAY)
        self.assertEqual(len(accepted),2)
        self.assertEqual(winner["flight"],"3U6573")
        self.assertEqual(winner["price_cny"],"820")

    def test_config_does_not_expand_to_other_airports_or_dates(self):
        self.assertEqual(tc.validate_config(CONFIG),[(DAY,RETURN_DAY)])
        for broken in [
            dict(CONFIG,origin="CTU"),
            dict(CONFIG,destination="FYN"),
            dict(CONFIG,stay_nights=4),
            dict(CONFIG,direct_only=False),
            dict(CONFIG,departure_dates=[]),
            dict(CONFIG,departure_dates=[DAY,DAY]),
        ]:
            with self.assertRaises(ValueError):tc.validate_config(broken)

    def test_livescan_preserves_missing_return_as_gap_never_alert(self):
        calls=[]
        def fake(origin,destination,date):
            calls.append((origin,destination,date))
            if origin=="TFU":
                return [item()], None
            return [], "provider_unavailable"
        result=tc.run_snapshot(CONFIG,getter=fake,
            now=datetime(2026,10,30,20,0,tzinfo=BJT))
        self.assertEqual(calls,[("TFU","AAT",DAY),("AAT","TFU",RETURN_DAY)])
        rec=result["itineraries"][0]
        self.assertEqual(rec["status"],"incomplete")
        self.assertIsNone(rec["total_cny"])
        self.assertFalse(result["bookability_verified"])
        self.assertFalse(result["cabin_verified"])

    def test_complete_roundtrip_is_unverified_sum_and_retains_last_valid(self):
        def fake(origin,destination,date):
            return ([item()] if origin=="TFU" else
                    [item(flight="9C6686",dep="AAT",arr="TFU",day=RETURN_DAY,
                          fare=900)]), None
        state=tc.run_snapshot(CONFIG,getter=fake,
            now=datetime(2026,10,30,20,0,tzinfo=BJT))
        q=state["itineraries"][0]
        self.assertEqual(q["total_cny"],"1740")
        self.assertEqual(q["status"],"priced_reference")
        self.assertEqual(q["carrier_prices"]["return"]["9C"],"900")
        def failure(*_args):
            return [], "http_error"
        new=tc.run_snapshot(CONFIG,prior=state,getter=failure,
            now=datetime(2026,10,30,20,0,tzinfo=BJT))
        cur=new["itineraries"][0]
        self.assertEqual(cur["status"],"incomplete")
        self.assertIsNone(cur["total_cny"])
        self.assertEqual(cur["last_valid"]["total_cny"],"1740")

if __name__ == "__main__":
    unittest.main()
