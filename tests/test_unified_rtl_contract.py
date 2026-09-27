"""v4.1 structural source contract; functional checks live in RTL simulations."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class UnifiedRtlContractTests(unittest.TestCase):
    def test_only_clock_reset_inputs(self):
        top=(ROOT/'rtl/top/mhbs_top.sv').read_text()
        ports=top.split(')(',1)[1].split(');',1)[0]
        self.assertEqual(ports.count('input wire'),1)
        self.assertIn('input wire clk,rst,',ports)
        self.assertIn('posedge rst',top)
    def test_fixed_roms_and_runtime_configuration(self):
        top=(ROOT/'rtl/top/mhbs_top.sv').read_text()
        self.assertEqual(top.count('mhbs_image_rom #'),3)
        core=(ROOT/'rtl/top/mhbs_hbs.sv').read_text()
        params=core.split(')(',1)[0]
        self.assertNotIn('TOKEN_FILE',params)
        self.assertNotIn('parameter integer N ',params)
        self.assertIn('profile_descriptor[59]',core)
        self.assertNotIn('N==32',core)
    def test_fixed_index_has_no_guard(self):
        sources=(ROOT/'manifests/unified_sources.txt').read_text().splitlines()
        self.assertFalse(any('stateful_index_guard' in p for p in sources))
        for name in ('mhbs_top','mhbs_processor','mhbs_hbs'):
            text=(ROOT/f'rtl/top/{name}.sv').read_text()
            for removed in ('state_next_q','state_commit_','consumed_index','guard_current_q'):
                self.assertNotIn(removed,text)
    def test_production_source_closure(self):
        sources=(ROOT/'manifests/unified_sources.txt').read_text().splitlines()
        self.assertTrue(all((ROOT/p).is_file() for p in sources))
        self.assertEqual([p for p in sources if p.endswith('_top.sv')],['rtl/top/mhbs_top.sv'])
if __name__=='__main__':unittest.main()
