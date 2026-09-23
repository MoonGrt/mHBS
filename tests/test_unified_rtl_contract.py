import json
from pathlib import Path
import re
import unittest

from model.unified_hbs import compile_image
from model.profiles import PROFILES

ROOT=Path(__file__).resolve().parents[1]


class UnifiedRtlContractTests(unittest.TestCase):
    def test_all_products_share_core_without_job_ports(self):
        for name in PROFILES:
            source=(ROOT/f"rtl/top/uhbs_{name}_top.sv").read_text()
            ports=source.split(") (",1)[1].split(");",1)[0]
            self.assertNotRegex(ports,r"\bjob_\w+")
            self.assertIn("uhbs_hbs #",source)
            self.assertNotIn("uhbs_stateless_hbs",source)
            self.assertNotIn("uhbs_stateful_hbs",source)
            self.assertRegex(ports,r"input wire clk, rst_n, start")
        sources=(ROOT/"manifests/unified_sources.txt").read_text()
        self.assertNotIn("uhbs_stateless_hbs",sources)
        self.assertNotIn("uhbs_stateful_hbs",sources)

    def test_roms_and_static_recipe_capabilities_match_compiler(self):
        manifest=json.loads((ROOT/"manifests/experiments/unified_hbs_v4/model_gate.json").read_text())
        for name in PROFILES:
            image=compile_image(name)
            for kind in ("tokens","templates","descriptors"):
                actual=tuple(int(w,16) for w in (ROOT/f"rtl/microcode/uhbs_{name}_{kind}.mem").read_text().split())
                self.assertEqual(actual,getattr(image,kind))
            mask=sum(1<<shape for shape in {((w>>56)&15) for w in image.descriptors if w>>60==1})
            self.assertEqual(manifest["profiles"][name]["recipe_mask"],mask)
            module=name
            source=(ROOT/f"rtl/top/uhbs_{module}_top.sv").read_text()
            self.assertIn(f".RECIPE_MASK(16'h{mask:04x})",source)
            chain_mask=sum(1<<shape for shape in {
                (image.descriptors[(word>>shift)&255]>>56)&15
                for word in image.descriptors if word>>60==4 for shift in (52,44)})
            self.assertEqual(manifest["profiles"][name]["chain_recipe_mask"],chain_mask)
            self.assertIn(f".CHAIN_RECIPE_MASK(16'h{chain_mask:04x})",source)
            self.assertIn(".MAX_MESSAGE_BYTES(MESSAGE_BYTES)",source)


if __name__=="__main__": unittest.main()
