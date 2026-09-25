#!/usr/bin/env python3
"""Seal the software gate before changing the SLH-only RTL."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.autonomous_hbs import ProgramImage
from model.slh_only import SLHMachine, SLH_PROFILES, admit
from model.unified_hbs import Machine, compile_image
from tests.test_unified_hbs import default_job

OUT = ROOT/'manifests/experiments/unified_hbs_v4.1/slh_only'
IMAGES = ROOT/'manifests/experiments/unified_hbs_v4.1/images'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    records = {}
    for name in SLH_PROFILES:
        directory = IMAGES/name
        image = ProgramImage.read(directory)
        logical, job, message = admit(image)
        independent_job, independent_message = default_job(name)
        assert (job, message) == (independent_job, independent_message)
        reference = Machine(compile_image(name), independent_job)
        expected_kg = reference.run(False)
        kg_stats = (reference.hashes, reference.permutations)
        expected_sg = reference.run(True, independent_message)
        sg_stats = (reference.hashes, reference.permutations)
        machine = SLHMachine(image)
        kg, sg = machine.run()
        assert (kg, sg) == (expected_kg, expected_sg)
        assert machine.stats == {'keygen': kg_stats, 'sign': sg_stats}
        for operation, result in (('keygen', kg), ('sign', sg)):
            frozen = bytes(int(x, 16) for x in (directory/(operation+'.mem')).read_text().split())
            assert result == frozen, (name, operation)
        try:
            machine.run()
            raise AssertionError('completed machine restarted')
        except ValueError:
            pass
        def rejected(changed, label):
            try: admit(changed)
            except ValueError: pass
            else: raise AssertionError(label+' admitted')
        d = list(image.descriptors)
        d[1] = (d[1] & ~(7 << 56)) | (2 << 56)
        rejected(replace(image, descriptors=tuple(d)), 'XMSS family')
        d = list(image.descriptors)
        d[1] = (d[1] & ~(7 << 56)) | (3 << 56)
        rejected(replace(image, descriptors=tuple(d)), 'LMS family')
        d = list(image.descriptors)
        d[120] = (1 << 60) | (5 << 56) | (32 << 32) | (1 << 24)
        rejected(replace(image, descriptors=tuple(d)), 'stateful recipe')
        d = list(image.descriptors)
        d[17] = (d[17] & ~(255 << 20)) | (68 << 20)
        rejected(replace(image, descriptors=tuple(d)), '68-chain image')
        d = list(image.descriptors)
        d[20] |= 1 << 31
        rejected(replace(image, descriptors=tuple(d)), 'tree cache mode')
        p = list(image.program);p[41] |= 5
        rejected(replace(image, program=tuple(p)), 'nonzero q')
        p = list(image.program);p[40] = 1
        rejected(replace(image, program=tuple(p)), 'identifier')
        t = list(image.templates);t[0] |= 1 << 78
        rejected(replace(image, templates=tuple(t)), 'stateful macro flag')
        records[name] = {'keygen_sha256': hashlib.sha256(kg).hexdigest(),
                         'sign_sha256': hashlib.sha256(sg).hexdigest(),
                         'keygen_counts': kg_stats, 'sign_counts': sg_stats,
                         'image_sha256': {p.name: sha(p) for p in directory.glob('*.mem')}}
    sources = {str(p.relative_to(ROOT)): sha(p) for p in
               [ROOT/'model/slh_only.py', ROOT/'model/autonomous_hbs.py',
                ROOT/'model/unified_hbs.py', ROOT/'model/profiles.py', Path(__file__)]}
    record = {'version': 'v4.1', 'abi_version': 4, 'passed': True,
              'profiles': records, 'source_sha256': sources}
    (OUT/'software_gate.json').write_text(json.dumps(record, indent=2)+'\n')
    print('SLH_ONLY_SOFTWARE_PASS', len(records))


if __name__ == '__main__':
    run()
