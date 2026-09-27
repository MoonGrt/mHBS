#!/usr/bin/env python3
"""Compare K2U2 pruning with the sealed baseline and statistics-disabled RTL."""
import argparse
import concurrent.futures
import json

from v42_external_flow import BASE, NAMES, build_binary, capture, identity, run, sha, simulate_case, write


def verify(tag, baseline='current_complete_20260927_v2'):
    folder = capture(tag)
    normal = json.loads((folder / 'simulation.json').read_text())
    old_file = BASE / 'candidates' / baseline / 'simulation.json'
    old = json.loads(old_file.read_text())
    assert normal['passed'] and normal['rtl_sha256'] == identity()
    keys = ('boot_cycles', 'keygen_cycles', 'sign_cycles', 'hashes',
            'permutations', 'total_cycles', 'output_sha256')
    assert set(normal['cases']) == set(old['cases']) and len(normal['cases']) == 6
    for name, row in normal['cases'].items():
        for key in keys:
            assert row[key] == old['cases'][name][key], (name, key)

    evidence = {}
    for partitioned in (False, True):
        suffix = '_partition_no_profile' if partitioned else '_no_profile'
        def one(case):
            name, operation = case
            key, row = simulate_case(folder, name+'_'+operation+suffix,
                                     BASE/'vectors'/name/operation,
                                     partitioned=partitioned, profile_enable=False)
            reference = normal['cases'][name+'_'+operation]
            for field in keys:
                assert row[field] == reference[field], (key, field)
            return key, row
        with concurrent.futures.ThreadPoolExecutor(3) as pool:
            cases = dict(pool.map(one, [(n, op) for n in NAMES for op in ('keygen', 'sign')]))
        path = folder / ('simulation'+suffix+'.json')
        write(path, dict(passed=True, profile_enable=False, rtl_sha256=identity(), cases=cases))
        evidence[path.name] = sha(path)

    # Exercise idle periods and reset recovery with counters compiled out.
    for label, options in [('stall', ('+STALL=1', '+TAIL_NOISE=1')),
                           ('replay', ('+INTERRUPT=1', '+REPLAYS=2'))]:
        name, row = simulate_case(folder, 'slh_128f_'+label+'_no_profile',
                                 BASE/'vectors/slh_128f/sign', options=options, profile_enable=False)
        assert row['sign_cycles']-row['wait_cycles'] == normal['cases']['slh_128f_sign']['sign_cycles']
        evidence['logs/'+name+'.json'] = sha(folder/'logs'/(name+'.json'))

    faults = {}
    def fault_case(case):
        name, mode = case
        vector = BASE/'vectors'/name/'sign'
        cfg = json.loads((vector/'job.json').read_text())
        binary = build_binary(folder, cfg, profile_enable=False)
        log = folder/'logs'/f'{name}_fault_{mode}.log'
        run([str(binary), '+IMAGE='+str(BASE/'images'/name), '+VECTOR='+str(vector),
             f'+FAULT={mode}'], log)
        assert f'V42_FAULT_PASS mode={mode}' in log.read_text()
        return name+'_'+str(mode), dict(passed=True, log_sha256=sha(log))
    with concurrent.futures.ThreadPoolExecutor(3) as pool:
        faults = dict(pool.map(fault_case, [(n, mode) for n in NAMES for mode in (1, 2)]))
    write(folder/'faults.json', dict(passed=True, rtl_sha256=identity(), cases=faults))
    evidence['faults.json'] = sha(folder/'faults.json')
    write(folder/'pruning_verification.json', dict(
        passed=True, rtl_sha256=identity(), baseline=baseline, baseline_sha256=sha(old_file),
        cycle_equivalence_pass=True, statistics_equivalence_pass=True,
        baseline_cases=6, statistics_disabled_cases=12, statistics_disabled_extended=2,
        fault_cases=6, evidence_sha256=evidence))
    print('PRUNING_VERIFICATION_PASS', tag, 'same cycles / statistics off / faults', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--baseline', default='current_complete_20260927_v2')
    args = parser.parse_args()
    verify(args.tag, args.baseline)
