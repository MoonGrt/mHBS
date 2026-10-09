#!/usr/bin/env python3
"""Rebuild the P4 comparison from archived reports; fail acceptance closed."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ('slh_128f_sign', 'xmss_omega4_keygen', 'lms_omega4_keygen')

def resources(path):
    text=path.read_text()
    def used(label):
        m=re.search(r'^\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.]+)\s*\|', text, re.M)
        if not m:raise ValueError(f'missing {label}: {path}')
        return float(m[1])
    result=dict(lut=used('Slice LUTs'),ff=used('Slice Registers'),lutram=used('LUT as Memory'),bram36=used('Block RAM Tile'),dsp=used('DSPs'))
    result['equivalent_slices']=result['lut']/4+result['ff']/8+232.4*result['bram36']+102.4*result['dsp']
    return result

def run(path):
    text=path.read_text();matches=re.findall(r'STATEFUL_PASS P4U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+) tamper=0',text)
    if len(matches)!=1 or '%Error' in text:raise ValueError(f'bad benchmark: {path}')
    op,cycles,total,hashes,permutations=map(int,matches[0])
    return dict(operation=op,cycles=cycles,total_cycles=total,hashes=hashes,permutations=permutations)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',type=Path,default=ROOT/'docs/manifests/experiments/p4_joint_20261013')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/report/P4U1_Redundancy_Performance_ATP_20261013')
    args=parser.parse_args();exp=args.experiment.resolve();out=args.output.resolve()
    spec=json.loads((exp/'index.json').read_text());variants={};rows=[]
    for variant in ('original','current','candidate'):
        folder=exp/variant
        synth=resources(folder/'synth/utilization.rpt');routed=resources(folder/'closed/utilization.rpt')
        result=dict(line.split('=',1) for line in (folder/'closed/result.txt').read_text().splitlines())
        period=float(result['period_ns']);wns=float(result['wns_ns']);whs=float(result['whs_ns'])
        if wns<0 or whs<0:raise ValueError(f'STA not closed: {variant}')
        status=(folder/'closed/route_status.rpt').read_text()
        counts={}
        for label in ('routable nets','fully routed nets','nets with routing errors'):
            match=re.search(r'# of '+re.escape(label)+r'\.*\s*:\s*(\d+)',status,re.I)
            if not match:raise ValueError(f'missing route status {label}: {variant}')
            counts[label]=int(match[1])
        if counts['nets with routing errors'] or counts['routable nets']!=counts['fully routed nets']:
            raise ValueError(f'incomplete route: {variant}')
        variants[variant]=dict(synthesis=synth,routed=routed,period_ns=period,sta_mhz=1000/period,wns_ns=wns,whs_ns=whs)
        for target in TARGETS:
            benchmark=run(folder/f'runs/{target}.log')
            rows.append(dict(target=target,variant=variant,**benchmark,synthesis_slices=synth['equivalent_slices'],routed_slices=routed['equivalent_slices'],period_ns=period,sta_mhz=1000/period,atp_150_slices_ms=synth['equivalent_slices']*benchmark['cycles']/150000,atp_sta_slices_ms=routed['equivalent_slices']*benchmark['cycles']*period/1e6))
    gates={};by_target={t:{r['variant']:r for r in rows if r['target']==t} for t in TARGETS}
    gates['synthesis_area_below_original_9485_5']=variants['candidate']['synthesis']['equivalent_slices']<9485.5
    for target,limit in zip(TARGETS,(764628,26802110,7515151)):
        group=by_target[target];candidate=group['candidate'];gates[f'{target}_cycles']=candidate['cycles']<limit
        for base in ('original','current'):
            a,b=group[base],candidate
            if (a['hashes'],a['permutations'])!=(b['hashes'],b['permutations']):raise ValueError(f'workload changed: {target}')
            gates[f'{target}_sta_atp_vs_{base}']=b['atp_sta_slices_ms']<a['atp_sta_slices_ms']
            candidate[f'atp_sta_delta_vs_{base}_pct']=100*(b['atp_sta_slices_ms']/a['atp_sta_slices_ms']-1)
            candidate[f'cycles_delta_vs_{base}_pct']=100*(b['cycles']/a['cycles']-1)
    evidence={str(p.relative_to(exp)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(exp.rglob('*')) if p.is_file()}
    result=dict(schema='mhbs.p4_joint_optimization.v1',date='2026-10-13',configuration='P4U1',scope='common OOC, single physical hash lane, all ten profiles and three operations',keccak_mapping='generic',part='xc7a200tffg1156-3',vivado='2025.2',statistics_enabled=False,area_formula='LUT/4 + FF/8 + 232.4*BRAM36 + 102.4*DSP',sta_basis='setup/hold on a frozen physical route; clock period swept in 0.1 ns increments from 6.666667 ns',variants=variants,rows=rows,acceptance=gates,accepted=all(gates.values()),steps=spec['steps'],validation=spec['validation'],source_and_evidence_sha256=evidence,checkpoint_archive=spec['checkpoint_archive'])
    out.parent.mkdir(parents=True,exist_ok=True)
    out.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with out.with_suffix('.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print('P4_REPORT_ACCEPTED' if result['accepted'] else 'P4_REPORT_REJECTED',gates)
    if not result['accepted']:raise SystemExit(1)

if __name__=='__main__':main()
