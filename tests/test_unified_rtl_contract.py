"""Current layout-3 source/interface contract; behavior is checked by RTL benches."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class UnifiedRtlContractTests(unittest.TestCase):
    def test_external_message_and_synchronous_reset(self):
        top = (ROOT / 'rtl/top/mhbs_top.sv').read_text()
        ports = top.split(')(', 1)[1].split(');', 1)[0]
        declarations = re.findall(
            r'\binput\s+(?:wire|logic)\s+(?:\[[^]]+\]\s*)?'
            r'(.+?)(?=,\s*(?:input|output)|$)', ports, re.S)
        inputs = {name.strip() for group in declarations for name in group.split(',')}
        self.assertEqual(inputs, {'clk', 'rst', 'message_valid', 'message_length', 'message_data'})
        self.assertRegex(ports, r'\[6:0\]\s+message_length')
        self.assertRegex(ports, r'\[63:0\]\s+message_data')
        for path in (ROOT / 'manifests/v42_sources.txt').read_text().split():
            with self.subTest(source=path):
                text = (ROOT / path).read_text()
                self.assertNotRegex(text, r'\b(?:posedge|negedge)\s+rst\b')
                self.assertNotRegex(text, r'\bnegedge\s+clk\b')

    def test_fixed_job_and_separate_images(self):
        top = (ROOT / 'rtl/top/mhbs_top.sv').read_text()
        for name in ('SECRET_SEED', 'SECRET_PRF', 'PUBLIC_SEED', 'RANDOMIZER', 'PUBLIC_ROOT'):
            self.assertRegex(top, rf'parameter\s+\[255:0\]\s+{name}\s*=')
        self.assertRegex(top, r'parameter\s+bit\s+OPERATION\s*=')
        for kind, last in (('program', 31), ('template', 15), ('descriptor', 31)):
            self.assertRegex(top, rf'logic\s+\[63:0\]\s+{kind}_memory\[0:{last}\]')
            self.assertRegex(top, rf'\$readmemh\({kind.upper()}_INIT_FILE,\s*{kind}_memory\)')

    def test_slh_only_source_interface(self):
        for name in ('mhbs_top', 'mhbs_hbs'):
            text = (ROOT / f'rtl/top/{name}.sv').read_text()
            for removed in ('state_next_q', 'state_commit_', 'consumed_index', 'guard_current_q'):
                self.assertNotIn(removed, text)

    def test_production_source_closure(self):
        sources = (ROOT / 'manifests/v42_sources.txt').read_text().split()
        self.assertEqual(len(sources), len(set(sources)))
        self.assertTrue(sources)
        for path in sources:
            with self.subTest(source=path):
                self.assertTrue((ROOT / path).is_file(), path)
        self.assertEqual([p for p in sources if p.endswith('_top.sv')], ['rtl/top/mhbs_top.sv'])
        self.assertEqual((ROOT / 'manifests/unified_sources.txt').read_text().split(), sources)
        self.assertNotIn('rtl/top/mhbs_processor.sv', sources)


if __name__ == '__main__':
    unittest.main()
