#!/usr/bin/env python3
"""Read current frozen common-core measurements and report K1U1 ATP at 100 MHz."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def area(folder):
    folder=Path(folder)
    report=folder/'utilization.rpt'
    if not report.exists():report=folder/'core_utilization.rpt'
    text=report.read_text()
    result={}
    for name,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36','Block RAM Tile'),('dsp','DSPs')]:
        found=re.search(r'^\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',text,re.M)
        if not found:raise ValueError('Missing utilization field: '+label)
        result[name]=float(found[1].replace(',',''))
    result['equivalent_slices']=result['lut']/4+result['ff']/8+232.4*result['bram36']+102.4*result['dsp']
    timing=folder/'timing.json'
    result['timing_diagnostic']=json.loads(timing.read_text()) if timing.exists() else None
    return result


def render(result):
    rows=['# Common-core synthesis and ATP','',
          'Fixed K1U1; xc7a200tffg1156-3; 100 MHz OOC synthesis, two threads, PROFILE_ENABLE=0. '
          'The core excludes program ROM and signature cache. No placement or routing was performed.','',
          '| Backend | LUT | FF | BRAM36 | DSP | Equivalent Slice | Status |',
          '|---|---:|---:|---:|---:|---:|---|']
    a=result.get('resources')
    if a:
        rows.append(f'| {result["hash_backend"]} | {a["lut"]:,.0f} | {a["ff"]:,.0f} | {a["bram36"]:g} | {a["dsp"]:g} | {a["equivalent_slices"]:,.3f} | {result["status"]} |')
    else:rows.append(f'| {result["hash_backend"]} | | | | | | {result["status"]} |')
    if result.get('relative_delta'):
        rows+=['',f'SHAKE source-area comparison: LUT {100*result["relative_delta"]["lut"]:+.4f}%, FF {100*result["relative_delta"]["ff"]:+.4f}%. '
               'The source-import 1% gate does not apply after adding XMSS/LMS.']
    if result.get('analysis_deferred'):rows+=['','Analysis deferred after 600 seconds; the synthesis process continues.']
    if result.get('error'):rows+=['','Error: '+result['error']]
    if result.get('performance'):
        rows+=['','ATP uses assumed 100 MHz, not a routed frequency.','',
               '| Profile / operation | Cycles | Time ms | ATP Slice·ms |','|---|---:|---:|---:|']
        for name,p in result['performance'].items():rows.append(f'| {name} | {p["cycles"]:,} | {p["time_ms"]:.6f} | {p["atp_slice_ms"]:.6f} |')
    rows+=['',f'Run logs: `{result["run_root"]}`. Frozen RTL and checksums accompany this report.','']
    return '\n'.join(rows)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--regression',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args();state=json.loads((args.run/'status.json').read_text())
    if args.regression:
        validation=json.loads((args.regression/'rtl.json').read_text())
        if not validation.get('passed'):raise ValueError('RTL regression did not pass')
        if state['hash_backend']!='shake':raise ValueError('ABI3 source supports SHAKE only')
        if state.get('status') not in ('passed','measured'):raise ValueError('Synthesis must pass first')
        # The actual source-flow receipt binds its observed cases directly to production RTL.
        synth_files=json.loads((args.run/'SOURCE.json').read_text())['files']
        reg_files=validation['source_sha256']
        for name,value in synth_files.items():
            if name.startswith('rtl/') and reg_files.get(name)!=value:raise ValueError('Synthesis/regression source differs: '+name)
        state['performance']={k:dict(cycles=v['cycles'],time_ms=v['cycles']/100000,
            atp_slice_ms=state['resources']['equivalent_slices']*v['cycles']/100000)
            for k,v in validation['cases'].items() if '/' in k and v.get('passed') and 'cycles' in v}
        state['regression_source_sha256']=reg_files
        state['regression_receipt_sha256']=digest(args.regression/'rtl.json')
    output=args.output or args.run/'reports/ATP';output.parent.mkdir(parents=True,exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(state,indent=2,sort_keys=True)+'\n')
    output.with_suffix('.md').write_text(render(state))
    print(output.with_suffix('.md'))


if __name__=='__main__':main()
