"""Offline tests for Fliggy PC price safety."""
import unittest
from scripts import fliggy_snapshot as f
def raw(**kw):
 d=dict(code="9C6685",depAirport="天府机场",arrAirport="雪都机场",depTime="10:05",price=780)
 d.update(kw)
 return d
class TestFliggyPc(unittest.TestCase):
 def test_real_direct_airports(self):
  rows=f.clean_rows([raw(),raw(price=810),raw(code="3U6573",price=820)],"TFU","AAT","2026-12-09")
  self.assertEqual([(x["flight"],x["price_cny"]) for x in rows],[("9C6685","780"),("3U6573","820")])
  self.assertEqual(rows[0]["departure_time"],"2026-12-09 10:05")
 def test_do_not_confuse_shuangliu_transfer_cabin_or_wrong_city(self):
  candidates=[raw(depAirport="双流机场"),raw(arrAirport="喀纳斯机场"),
              raw(transfer=True),raw(transCity="乌鲁木齐"),raw(stopover=True),
              raw(cabin="公务舱"),raw(price=0),raw(price="NaN"),raw(code="BAD/123")]
  self.assertEqual(f.clean_rows(candidates,"TFU","AAT","2026-12-09"),[])
 def test_reverse_airports(self):
  r=f.clean_rows([raw(code="9C6686",depAirport="雪都机场",arrAirport="天府机场")],
                 "AAT","TFU","2026-12-14")
  self.assertEqual(len(r),1)
if __name__=="__main__":unittest.main()
