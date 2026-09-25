#!/usr/bin/env python3
"""Select a routed area candidate using the fixed per-profile cycle budget."""
import argparse
import json
from autonomous_flow import BASE, sha, write
from reproduce_autonomous import audit_physical, audit_frozen, audit_functional, check


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('candidates', nargs='+')
    args = parser.parse_args()
    reference = json.loads((BASE/'area_baseline.json').read_text())
    baseline_path = BASE/'candidates'/reference['candidate']/'ppa.json'
    check(sha(baseline_path) == reference['ppa_sha256'], 'baseline changed')
    baseline = json.loads(baseline_path.read_text())
    results = {}
    eligible = []
    for tag in args.candidates:
        folder = BASE/'candidates'/tag
        ppa = json.loads((folder/'ppa.json').read_text())
        inputs = json.loads((folder/'inputs.json').read_text())
        check(ppa['stage'] == 'post_route', 'selection requires completed routing')
        check(inputs['lanes'] == 2 and inputs['unroll'] == 2, 'U2 dual-lane constraint')
        check(inputs['index_policy'] == 'fixed_q_no_guard', 'index policy')
        audit_physical(folder)
        audit_functional(inputs)
        cycles_ok = all(p['sign_cycles']*100 <= reference['profiles'][name]['sign_cycles']*105
                        for name, p in ppa['profiles'].items())
        area_ok = ppa['equivalent_slice'] < baseline['equivalent_slice']
        atp_ok = ppa['worst_ratio'] < baseline['worst_ratio']
        keep = cycles_ok and area_ok and atp_ok
        if keep:
            check((folder/'frozen/evidence.tsv').exists(), 'retained candidate requires seven INIT variants')
            audit_frozen(folder, inputs)
        results[tag] = dict(ppa_sha256=sha(folder/'ppa.json'), cycle_limit_pass=cycles_ok,
            area_improves=area_ok, worst_atp_ratio_improves=atp_ok, eligible=keep,
            area_change_percent=100*(ppa['equivalent_slice']/baseline['equivalent_slice']-1),
            worst_atp_change_percent=100*(ppa['worst_ratio']/baseline['worst_ratio']-1),
            equivalent_slice=ppa['equivalent_slice'], frequency_mhz=ppa['frequency_mhz'],
            worst_ratio=ppa['worst_ratio'])
        if keep: eligible.append((ppa['equivalent_slice'], ppa['worst_ratio'], tag))
    selected = min(eligible)[2] if eligible else reference['candidate']
    result = dict(version='v4.1', baseline=reference['candidate'],
        baseline_sha256=reference['ppa_sha256'], selected=selected, candidates=results,
        performance_pass=False, rule='each Sign <=105% and routed worst ATP ratio improves baseline; then minimum area, ATP ratio breaks ties')
    write(BASE/'area_selection.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
