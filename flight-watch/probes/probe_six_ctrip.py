"""One-time scan of the six user-approved Altay date pairs from the validated Ctrip browser source."""
import importlib.util
from pathlib import Path

probe_path = Path(__file__).with_name("probe_two_date_sources.py")
spec = importlib.util.spec_from_file_location("altay_src_probe", probe_path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

probe.LEGS = [
    ("TFU", "AAT", "2026-12-08"),
    ("AAT", "TFU", "2026-12-13"),
    ("TFU", "AAT", "2026-12-09"),
    ("AAT", "TFU", "2026-12-14"),
    ("TFU", "AAT", "2026-12-17"),
    ("AAT", "TFU", "2026-12-22"),
    ("TFU", "AAT", "2026-12-18"),
    ("AAT", "TFU", "2026-12-23"),
    ("TFU", "AAT", "2026-12-26"),
    ("AAT", "TFU", "2026-12-31"),
    ("TFU", "AAT", "2026-12-27"),
    ("AAT", "TFU", "2027-01-01"),
]
probe.run_ctrip()
