"""Safety and resume gates for the detached LUT search (no FPGA tools needed)."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'scripts/optimize_lut21k.py'
spec=importlib.util.spec_from_file_location('lut_driver',SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class DriverTests(unittest.TestCase):
    def fixture(self,base):
        run=base/'run';run.mkdir();work=base/'work';work.mkdir()
        c=dict(tag='test',label='bank',mask=1,workspace=str(work),code_sha256={})
        cfg=dict(candidates=[c],root=str(base),head='old',source_guard={},pointer_sha256='old')
        m.atomic(run/'config.json',cfg)
        m.atomic(run/'state.json',dict(status='prepared',candidates={'test':dict(status='pending',stages={},core=None)},completed=0))
        return m.Driver(run),c

    def test_stage_receipt_skips_execution(self):
        with tempfile.TemporaryDirectory() as t:
            d,c=self.fixture(Path(t))
            command=[m.PYTHON,'-c',"from pathlib import Path; p=Path('count'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"]
            d.stage(c,'normal',command);d.stage(c,'normal',command)
            self.assertEqual((Path(c['workspace'])/'count').read_text(),'1')
            self.assertEqual(d.state['candidates']['test']['stages']['normal']['status'],'passed')

    def test_failed_stage_cannot_pass(self):
        with tempfile.TemporaryDirectory() as t:
            d,c=self.fixture(Path(t))
            with self.assertRaises(RuntimeError):d.stage(c,'bad',[m.PYTHON,'-c','raise SystemExit(3)'])
            self.assertEqual(d.state['candidates']['test']['stages']['bad']['status'],'failed')

    def test_stop_kills_stage_group_and_resume_runs_interrupted_stage(self):
        with tempfile.TemporaryDirectory() as t:
            d,c=self.fixture(Path(t));real_sleep=m.time.sleep
            def trigger(seconds):
                d.signal_stop();real_sleep(.02)
            with patch.object(m.time,'sleep',side_effect=trigger):
                with self.assertRaises(m.Stopped):d.stage(c,'long',[m.PYTHON,'-c','import time;time.sleep(90)'])
            self.assertIsNone(d.state['child'])
            self.assertEqual(d.state['candidates']['test']['stages']['long']['status'],'interrupted')
            d.stop=False;d.stage(c,'long',[m.PYTHON,'-c','pass'])
            self.assertEqual(d.state['candidates']['test']['stages']['long']['attempts'],2)

    def test_source_change_blocks_execution(self):
        with tempfile.TemporaryDirectory() as t:
            d,c=self.fixture(Path(t));p=Path(c['workspace'])/'a.sv';p.write_text('before');c['code_sha256']={'a.sv':m.sha(p)};p.write_text('after')
            with self.assertRaises(AssertionError):d.stage(c,'normal',[m.PYTHON,'-c','pass'])

    def test_concurrent_change_blocks_promotion(self):
        with tempfile.TemporaryDirectory() as t:
            base=Path(t);d,c=self.fixture(base)
            pointer=base/m.BASE/'current_core.json';m.atomic(pointer,{'candidate':'user_change'})
            with patch.object(m.subprocess,'check_output',return_value='new\n'):d.promote(c)
            self.assertEqual(d.state['promotion'],'blocked_by_concurrent_changes')
            self.assertEqual(m.read(pointer)['candidate'],'user_change')

if __name__=='__main__':unittest.main()
