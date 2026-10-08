"""Snapshot capture must work on simulation-only hosts and reject stale inputs."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import v42_external_flow as flow


class ExternalFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.base = self.root / 'manifests/external'
        self.base.mkdir(parents=True)
        (self.base / 'software_gate.json').write_text('{"passed": true}\n')
        (self.root / 'rtl').mkdir()
        (self.root / 'rtl/core.sv').write_text('module core; endmodule\n')
        (self.root / 'manifests/v42_sources.txt').write_text('rtl/core.sv\n')
        for name in ('Makefile', 'README.md', 'manifests/unified_sources.txt',
                     'docs/Architecture.md', 'docs/Job_Interface.md', 'docs/Verification.md'):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text('fixture\n')
        for name, value in (('ROOT', self.root), ('BASE', self.base), ('BUILD', self.root / 'build')):
            patcher = patch.object(flow, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def simulation_tools_only(command, **kwargs):
        if command[0] != 'verilator':
            raise FileNotFoundError(command[0])
        return command[0] + ' test-version\n'

    def test_capture_without_vivado(self):
        with patch.object(flow.subprocess, 'check_output', side_effect=self.simulation_tools_only) as run:
            folder = flow.capture('simulation_only')
        inputs = json.loads((folder / 'inputs.json').read_text())
        self.assertEqual(set(inputs['tool_versions']), {'verilator'})
        self.assertEqual(run.call_count, 1)
        self.assertEqual(flow.sha(folder / 'source_snapshot.tar.gz'), inputs['snapshot_sha256'])
        self.assertIn('manifests/unified_sources.txt', inputs['source_sha256'])
        self.assertIn('docs/Verification.md', inputs['source_sha256'])

    def test_reuse_requires_identical_sources(self):
        with patch.object(flow.subprocess, 'check_output', side_effect=self.simulation_tools_only):
            folder = flow.capture('fixed')
            self.assertEqual(flow.capture('fixed'), folder)
            (self.root / 'rtl/core.sv').write_text('module changed; endmodule\n')
            with self.assertRaisesRegex(AssertionError, 'fresh tag'):
                flow.capture('fixed')

    def test_missing_or_broken_required_tool(self):
        for error in (FileNotFoundError(), subprocess.CalledProcessError(1, ['verilator'])):
            with self.subTest(error=type(error).__name__):
                with patch.object(flow.subprocess, 'check_output', side_effect=error):
                    with self.assertRaisesRegex(RuntimeError, 'verilator is required'):
                        flow.tool_version('verilator', '--version')

    def test_tag_cannot_escape_build_directory(self):
        for tag in ('../outside', '/tmp/outside', '.', '..', ''):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                flow.capture(tag)


if __name__ == '__main__':
    unittest.main()
