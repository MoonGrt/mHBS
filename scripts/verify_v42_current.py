#!/usr/bin/env python3
"""Audit a complete current-source functional run, without claiming measured PPA."""
import argparse
import json
import tarfile
import hashlib

from v42_external_flow import ROOT, BASE, NAMES, capture, identity, sha, write


def audit(tag):
    folder = capture(tag)  # Reject changed source, test drivers, images or vectors.
    inputs = json.loads((folder / 'inputs.json').read_text())
    assert sha(folder / 'source_snapshot.tar.gz') == inputs['snapshot_sha256']
    with tarfile.open(folder / 'source_snapshot.tar.gz') as snapshot:
        for path, digest in inputs['source_sha256'].items():
            assert hashlib.sha256(snapshot.extractfile(path).read()).hexdigest() == digest, path

    software = json.loads((BASE / 'software_gate.json').read_text())
    assert software['passed'] and software['layout_revision'] == 3
    assert set(software['profiles']) == {n + '/' + op for n in NAMES for op in ('keygen', 'sign')}
    for path, digest in software['source_sha256'].items():
        assert sha(ROOT / path) == digest, path
    for name, row in software['profiles'].items():
        for filename, digest in row['files'].items():
            assert sha(BASE / 'vectors' / name / filename) == digest, (name, filename)

    unit = json.loads((BASE / 'unit/results.json').read_text())
    assert unit['passed'] and unit['rtl_sha256'] == identity()
    for path, digest in unit['boot_sources'].items():
        assert sha(ROOT / path) == digest, path
    for path, digest in unit['logs'].items():
        assert sha(BASE / 'unit' / path) == digest, path
    macro_file = BASE / 'unit/macro_hash/results.json'
    assert sha(macro_file) == unit['macro_hash_gate_sha256']
    macro = json.loads(macro_file.read_text())
    assert macro['passed'] and macro['logic_sha256'] == identity()
    for path, digest in macro['test_source_sha256'].items():
        assert sha(ROOT / path) == digest, path

    normal_names = {n + '_' + op for n in NAMES for op in ('keygen', 'sign')}
    extended_names = {n + '_' + label for n in NAMES for label in (
        'root_transfer', 'stall', 'replay', 'keygen_replay',
        'message_1', 'message_7', 'message_8', 'message_9', 'message_87', 'message_87_stall')}
    groups = {}
    for filename, expected in (
        ('simulation.json', normal_names), ('extended.json', extended_names),
        ('simulation_partition.json', {name + '_partition' for name in normal_names}),
    ):
        group = json.loads((folder / filename).read_text())
        assert group['passed'] and group['rtl_sha256'] == identity(), filename
        assert set(group['cases']) == expected, filename
        for name, row in group['cases'].items():
            assert row['passed'], name
            assert sha(folder / 'logs' / (name + '.log')) == row['log_sha256'], name
            assert sha(folder / 'logs' / (name + '.actual.mem')) == row['output_sha256'], name
        groups[filename] = group['cases']

    for name, row in groups['simulation_partition.json'].items():
        original = groups['simulation.json'][name.removesuffix('_partition')]
        for key in ('boot_cycles', 'keygen_cycles', 'sign_cycles', 'hashes',
                    'permutations', 'total_cycles', 'output_sha256'):
            assert row[key] == original[key], (name, key)

    pruning=json.loads((folder/'pruning_verification.json').read_text())
    assert pruning['passed'] and pruning['rtl_sha256']==identity()
    for path,digest in pruning['evidence_sha256'].items():
        assert sha(folder/path)==digest,path
    verify_file = folder / 'verify/results.json'
    verify = json.loads(verify_file.read_text())
    assert verify['passed'] and not verify['quick']
    assert verify['source_snapshot_sha256'] == inputs['snapshot_sha256']
    assert set(verify['profiles']) == set(NAMES)
    for profile, cases in verify['profiles'].items():
        expected_cases = {'normal', 'randomizer', 'fors_secret', 'fors_auth',
            'wots', 'xmss_auth', 'last_auth', 'message', 'root', 'stall',
            'reset_replay', 'truncated_wait_reset', 'no_profile', 'partition', 'fault', 'node_padding', 'second_node_delay', 'poison_reset'}
        if not profile.startswith('slh_128'):expected_cases.add('root_middle')
        if profile.startswith('slh_256'):expected_cases.add('root_upper')
        else:expected_cases.add('root_padding')
        assert set(cases)==expected_cases
        assert all(cases['normal']['coverage'].values())
        for label, row in cases.items():
            assert row['passed']
            assert sha(folder / 'verify' / profile / (label + '.log')) == row['log_sha256']
    evidence = [folder / name for name in ('inputs.json', 'simulation.json',
                'extended.json', 'simulation_partition.json', 'pruning_verification.json')]
    evidence += [BASE / 'software_gate.json', BASE / 'unit/results.json', verify_file]
    receipt = dict(
        passed=True, scope='current-source functional verification', tag=tag,
        rtl_sha256=identity(), source_snapshot_sha256=inputs['snapshot_sha256'],
        software_cases=len(software['profiles']), macro_units=len(macro['logs']), boot_units=1,
        normal_cases=len(normal_names), extended_cases=len(extended_names), partition_cases=len(normal_names),
        partition_equivalence_pass=True, verify_node_cases=sum(len(x) for x in verify['profiles'].values()),
        verify_nodes_pass=True, post_synth_measured=False, post_route_measured=False,
        evidence_sha256={str(path.relative_to(ROOT)): sha(path) for path in evidence},
    )
    write(folder / 'verification.json', receipt)
    print('CURRENT_VERIFICATION_PASS', tag, f"{len(software['profiles'])} model / {len(macro['logs'])+1} unit / {len(normal_names)} RTL / {len(extended_names)} extended / {len(normal_names)} partition / statistics-off + faults / {receipt['verify_node_cases']} verify-node cases")
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    audit(parser.parse_args().tag)
