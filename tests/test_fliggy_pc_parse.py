"""Vendored Fliggy PC parser: checksum, cabin, and pre-tax price."""
import hashlib
from pathlib import Path
import unittest

from scripts import fliggy_snapshot as snap
from scripts.vendor.lll151_ticket.fliggy_pc_parse import parse_pc_text

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = """春秋9C6685
中型机 737
10:05
14:20
天府国际机场T2
雪都机场
经济舱
¥780
"""
NO_CABIN = """春秋9C6685
中型机 737
10:05
14:20
天府国际机场T2
雪都机场
¥780
"""


class VendoredParserTests(unittest.TestCase):
    def test_checksum_matches_pinned_excerpt(self):
        listed = (ROOT / "scripts/vendor/lll151_ticket/SHA256SUMS").read_text(encoding="utf-8").split()
        digest, rel = listed[0], listed[1]
        payload = (ROOT / rel).read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), digest)

    def test_economy_row_is_base_fare_and_missing_cabin_is_dropped(self):
        rows = parse_pc_text(SAMPLE, "2026-12-09")
        self.assertEqual(rows[0]["code"], "9C6685")
        self.assertEqual(rows[0]["cabin"], "经济舱")
        self.assertEqual(rows[0]["price"], 780.0)
        kept = snap.clean_rows(rows, "TFU", "AAT", "2026-12-09")
        self.assertEqual(kept[0]["base_fare_cny"], "780.0")
        self.assertIsNone(kept[0]["tax_inclusive_cny"])
        self.assertEqual(snap.clean_rows(parse_pc_text(NO_CABIN, "2026-12-09"), "TFU", "AAT", "2026-12-09"), [])


if __name__ == "__main__":
    unittest.main()
