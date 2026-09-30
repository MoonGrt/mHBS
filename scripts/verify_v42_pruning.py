#!/usr/bin/env python3
"""Compare K2U2 pruning with the sealed baseline and statistics-disabled RTL."""
import argparse
import concurrent.futures
import json

from v42_external_flow import BASE, NAMES, build_binary, capture, identity, run, sha, simulate_case, write


def verify(tag, baseline='current_complete_20260927_v2', node_output=False):
    folder = capture(tag)
    normal = json.loads((folder / 'simulation.json').read_text())
    old_file = BASE / 'candidates' / baseline / 'simulation.json'
    old = json.loads(old_file.read_text())
    assert normal['passed'] and normal['rtl_sha256'] == identity()
    keys = ('boot_cycles', 'keygen_cycles', 'sign_cycles', 'hashes',
            'permutations', 'total_cycles', 'output_sha256')
    assert set(normal['cases']) == {n+'_'+op for n in NAMES for op in ('keygen','sign')}
    assert set(old['cases']) <= set(normal['cases'])
    for name, row in normal['cases'].items():
        if name not in old['cases']:continue
        reference=old['cases'][name]
        n=len(bytes.fromhex(row['config']['secret_seed']))
        vector=BASE/'vectors'/row['config']['profile']/('sign' if row['config']['operation'] else 'keygen')
        byte_count=int((vector/'metadata.mem').read_text().split()[0],16)
        # R's old output overlapped up to three sequencer cycles; one remains.
        overlap=max(min(n//8,3)-1,0) if row['config']['operation'] else 0
        saved=(byte_count//n)*(n//8-1)-overlap if node_output else 0
        for key in keys:
            expected=reference[key]
            if key in ('total_cycles', 'sign_cycles' if row['config']['operation'] else 'keygen_cycles'):
                expected-=saved
            assert row[key]==expected,(name,key,row[key],expected)

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
        cycle_equivalence_pass=not node_output, node_output_cycle_formula_pass=node_output,
        statistics_equivalence_pass=True,
        baseline_cases=len(old['cases']), statistics_disabled_cases=4*len(NAMES), statistics_disabled_extended=2,
        fault_cases=2*len(NAMES), evidence_sha256=evidence))
    print('PRUNING_VERIFICATION_PASS', tag, 'node-output cycle formula / statistics off / faults' if node_output else 'same cycles / statistics off / faults', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--baseline', default='current_complete_20260927_v2')
    parser.add_argument('--node-output', action='store_true', help='expect one beat per node instead of 64-bit serialization')
    args = parser.parse_args()
    verify(args.tag, args.baseline, args.node_output)
