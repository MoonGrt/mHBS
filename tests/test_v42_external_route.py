"""Acceptance must reject incomplete routes, unconstrained timing and corrupt ROMs."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from v42_external_route import audit_timing, audit_rom
from v42_external_flow import BASE


class ExternalRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        (self.folder / 'timing_summary.rpt').write_text('All user specified timing constraints are met.\n')
        (self.folder / 'check_timing.rpt').write_text('\n'.join(
            'checking ' + name + ' (0)' for name in ('no_clock', 'unconstrained_internal_endpoints',
            'no_input_delay', 'no_output_delay', 'partial_input_delay', 'partial_output_delay')))
        (self.folder / 'route_status.rpt').write_text(
            '# of routable nets..................... : 100 :\n'
            '# of fully routed nets................. : 100 :\n'
            '# of nets with routing errors.......... : 0 :\n')

    def test_complete_route_without_unrouted_line(self):
        self.assertTrue(audit_timing(self.folder))

    def test_reject_incomplete_route(self):
        path = self.folder / 'route_status.rpt'
        path.write_text(path.read_text().replace(': 100 :', ': 99 :', 1))
        with self.assertRaises(AssertionError):
            audit_timing(self.folder)

    def test_reject_unconstrained_endpoints(self):
        path = self.folder / 'check_timing.rpt'
        path.write_text(path.read_text().replace('unconstrained_internal_endpoints (0)', 'unconstrained_internal_endpoints (1)'))
        with self.assertRaises(AssertionError):
            audit_timing(self.folder)

    def test_reject_timing_failure(self):
        (self.folder / 'timing_summary.rpt').write_text('Timing constraints are not met.\n')
        with self.assertRaises(AssertionError):
            audit_timing(self.folder)

    def test_rom_truth_table_and_corruption(self):
        images = BASE / 'images/slh_128f'
        lines = []
        for kind in ('program', 'template', 'descriptor'):
            data = [int(x, 16) for x in (images / (kind + '.mem')).read_text().split()]
            bits = 4 if kind in ('program', 'template') else 5
            for port in range(2 if kind == 'descriptor' else 1):
                for bit in range(64):
                    # Reverse address pin order to model a legal LUT pin permutation.
                    truth = ''.join(str((data[int(f'{address:0{bits}b}'[::-1], 2)] >> bit) & 1)
                                    for address in reversed(range(1 << bits)))
                    pins = ','.join(map(str, reversed(range(bits))))
                    lines.append(f"{kind}\t{port}\t{bit}\t{kind}_{port}_{bit}\t{bits}\t{pins}\t{1<<bits}'h{int(truth, 2):x}")
        path = self.folder / 'rom.tsv'
        path.write_text('\n'.join(lines))
        self.assertTrue(audit_rom(path, images)['passed'])
        fields = lines[0].split('\t')
        fields[-1] = "32'h" + format(int(fields[-1].split("'h")[1], 16) ^ 1, 'x')
        lines[0] = '\t'.join(fields)
        path.write_text('\n'.join(lines))
        with self.assertRaises(AssertionError):
            audit_rom(path, images)


if __name__ == '__main__':
    unittest.main()
