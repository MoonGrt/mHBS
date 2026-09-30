#!/usr/bin/env python3
"""Recompute routed metrics and validate all six archived implementations."""
import json
import math
from v42_external_flow import BASE, ROOT, sha
from v42_external_route import resources, audit_timing, audit_rom

final = json.loads((BASE / 'routed_final.json').read_text())
latest = json.loads((BASE / 'final.json').read_text())
assert latest['candidate'] == final['candidate'] and latest['post_route_pass']
assert latest['route_result_sha256'] == final['route_result_sha256']
assert math.isclose(latest['frequency_mhz'], final['common_frequency_mhz'])
candidate = BASE / 'candidates' / final['candidate']
assert final['post_route_pass'] and sha(candidate / 'route/result.json') == final['route_result_sha256']
routed = json.loads((candidate / 'route/result.json').read_text())
synth = json.loads((candidate / 'result.json').read_text())
assert routed['passed'] and routed['rtl_sha256'] == synth['rtl_sha256']
assert routed['source_snapshot_sha256'] == synth['source_snapshot_sha256'] == sha(candidate / 'source_snapshot.tar.gz')
for path, digest in json.loads((candidate / 'evidence_sha256.json').read_text()).items():
    assert sha(candidate / path) == digest, path
assert set(routed['tops']) == set(synth['tops']) and len(routed['tops']) in (6,12)
for name, row in routed['tops'].items():
    folder = candidate / 'route' / name
    assert row['passed'] and row['wns_ns'] >= .0999 and row['whs_ns'] >= 0
    assert math.isclose(row['frequency_mhz'], 1000/row['period_ns'])
    audit_timing(folder)
    audit_rom(folder / 'initialized_rom.tsv', candidate / 'images' / name.rsplit('_', 1)[0])
    for key, value in resources(folder / 'utilization.rpt').items():
        assert math.isclose(value, row[key]), (name, key)
    assert math.isclose(row['area_time_product'], row['equivalent_slice'] * row['operation_cycles'] * row['period_ns'] / 1e6)
assert math.isclose(final['common_frequency_mhz'], min(r['frequency_mhz'] for r in routed['tops'].values()))
print('EXTERNAL_ROUTE_REPRODUCE_PASS', final['candidate'], final['common_frequency_mhz'])
