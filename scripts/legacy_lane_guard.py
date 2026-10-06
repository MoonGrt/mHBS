"""Prevent historical multi-lane runners from modifying current-source evidence."""
from pathlib import Path
import re

def require_legacy_lanes():
    root=Path(__file__).resolve().parents[1]
    if not re.search(r'\bLANES\s*=', (root/'rtl/top/mhbs_hbs.sv').read_text()):
        raise SystemExit('Historical multi-lane driver: use its frozen source snapshot. Current RTL has one fixed lane; use run_pu_cycle_synth_matrix.py or verify_single_lane.py.')
