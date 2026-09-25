#!/usr/bin/env python3
"""Software gate for compact physical images and single-macro scheduling."""
import concurrent.futures
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.autonomous_hbs import AutonomousMachine, ProgramImage
from model.physical_image import PhysicalImage, validate_serial_schedule, pack_template, unpack_template
from model.profiles import PROFILES

BASE = ROOT/'manifests/experiments/unified_hbs_v4.1'
OUT = BASE/'software/area_v1'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def one(name):
    directory = BASE/'images'/name
    logical = ProgramImage.read(directory)
    validate_serial_schedule(logical)
    packed = PhysicalImage.pack(logical)
    restored = packed.unpack()
    assert restored == logical
    packed.write(OUT/'images'/name)
    assert PhysicalImage.read(OUT/'images'/name) == packed
    machine = AutonomousMachine(restored)
    kg, sg = machine.run()
    for kind, result in (('keygen', kg), ('sign', sg)):
        expected = bytes(int(x, 16) for x in (directory/(kind+'.mem')).read_text().split())
        assert result == expected, (name, kind)
    meta = [int(x, 16) for x in (directory/'metadata.mem').read_text().split()]
    assert [*machine.stats['keygen'], *machine.stats['sign']] == meta[2:6]
    try:
        machine.run()
        raise AssertionError('completed machine restarted')
    except ValueError:
        pass
    assert not machine.image.stateful or machine.job.q == (logical.program[41] & 2047)
    return name, dict(passed=True, stats=machine.stats,
        keygen_sha256=hashlib.sha256(kg).hexdigest(), sign_sha256=hashlib.sha256(sg).hexdigest(),
        logical_sha256={p.name:sha(p) for p in directory.glob('*.mem')},
        physical_sha256={p.name:sha(p) for p in (OUT/'images'/name).glob('*.mem')})

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with concurrent.futures.ProcessPoolExecutor(7) as pool:
        profiles = dict(pool.map(one, PROFILES))
    original = ProgramImage.read(BASE/'images/slh_128f')
    packed = PhysicalImage.pack(original)
    failures = []
    def reject(name, operation):
        try: operation()
        except ValueError: failures.append(name)
        else: raise AssertionError('accepted '+name)
    reject('template_lane1', lambda: pack_template(original.templates[0] | (1 << 106)))
    reject('template_coordinate', lambda: pack_template(original.templates[0] | (1 << 52)))
    reject('physical_reserved', lambda: unpack_template(packed.templates[0] | 1))
    reject('physical_capacity', lambda: replace(packed, descriptors=packed.descriptors[:-1]).unpack())
    reject('descriptor_width', lambda: replace(packed, descriptors=(1 << 64,)+packed.descriptors[1:]).unpack())
    descriptors = list(original.descriptors); descriptors[39] = descriptors[40]
    reject('unmapped_descriptor', lambda: PhysicalImage.pack(replace(original, descriptors=tuple(descriptors))))
    templates = list(original.templates); templates[0] |= 1 << 103
    reject('nonzero_event', lambda: validate_serial_schedule(replace(original, templates=tuple(templates))))
    templates = list(original.templates); templates[0] |= 1 << 116
    reject('initial_wait', lambda: validate_serial_schedule(replace(original, templates=tuple(templates))))
    paths = [*sorted((ROOT/'model').glob('*.py')), Path(__file__)]
    result = dict(passed=True, version='v4.1', abi=4, index_policy='fixed_q_no_guard',
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in paths}, profiles=profiles,
        rejected=failures, elapsed_seconds=time.monotonic()-started)
    (OUT/'software_gate.json').write_text(json.dumps(result, indent=2)+'\n')
    print('AREA_SOFTWARE_GATE_PASS',len(profiles),'profiles',len(failures),'errors',flush=True)

if __name__ == '__main__': main()
