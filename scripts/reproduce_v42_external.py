#!/usr/bin/env python3
"""Audit the selected common-core archive without relying on deleted trials."""
import hashlib
import json
import math
import tarfile
from v42_external_flow import BASE, sha

selected = json.loads((BASE / 'current_core.json').read_text())
folder = BASE / 'candidates' / selected['candidate']
result = json.loads((folder / 'result.json').read_text())
assert sha(folder / 'result.json') == selected['result_sha256']
assert result['functional_pass'] and result['core_synthesis_pass']
inputs = json.loads((folder / 'inputs.json').read_text())
assert sha(folder / 'source_snapshot.tar.gz') == inputs['snapshot_sha256']
with tarfile.open(folder / 'source_snapshot.tar.gz') as snapshot:
    for path, digest in inputs['source_sha256'].items():
        assert hashlib.sha256(snapshot.extractfile(path).read()).hexdigest() == digest, path
for path, digest in json.loads((folder / 'evidence_sha256.json').read_text()).items():
    assert sha(folder / path) == digest, path
area = result['core']
assert math.isclose(area['equivalent_slice'], area['lut']/4 + area['ff']/8
                    + area['bram36']*232.4 + area['dsp']*102.4)
audit = json.loads((folder / 'verification.json').read_text())
assert audit['passed'] and audit['rtl_sha256'] == result['rtl_sha256']
assert audit['source_snapshot_sha256'] == inputs['snapshot_sha256']
normal = json.loads((folder / 'simulation.json').read_text())
partition = json.loads((folder / 'simulation_partition.json').read_text())
assert normal['passed'] and partition['passed']
assert len(normal['cases']) == len(partition['cases']) == 12
for name, row in partition['cases'].items():
    original = normal['cases'][name.removesuffix('_partition')]
    for key in ('boot_cycles', 'keygen_cycles', 'sign_cycles', 'hashes',
                'permutations', 'total_cycles', 'output_sha256'):
        assert row[key] == original[key], (name, key)
assert json.loads((folder / 'extended.json').read_text())['passed']
assert json.loads((folder / 'pruning_verification.json').read_text())['passed']
verify = json.loads((folder / 'verify/results.json').read_text())
assert verify['passed'] and not verify['quick']
assert sum(map(len, verify['profiles'].values())) == 130
print('EXTERNAL_REPRODUCE_PASS', selected['candidate'], 'functional + common-core synthesis')
