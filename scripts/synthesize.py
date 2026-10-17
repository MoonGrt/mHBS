#!/usr/bin/env python3
"""Freeze and synthesize the imported SHAKE K1U1 common at 100 MHz."""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,subprocess,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,data):Path(p).write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
def resources(path):
    text=Path(path).read_text(); result={}
    for key,label in [('LUT','Slice LUTs'),('FF','Slice Registers'),('BRAM','Block RAM Tile'),('DSP','DSPs')]:
        match=re.search(r'^\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d.,]+)',text,re.M)
        if not match:raise ValueError('Missing resource '+label)
        result[key]=float(match[1].replace(',',''))
    result['equivalent_slices']=result['LUT']/4+result['FF']/8
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build/synth/image_chain_K1U1')
    args=parser.parse_args()
    if os.environ.get('HASH_BACKEND','shake')!='shake':parser.error('this source branch supports SHAKE only')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    frozen=out/'source'; frozen.mkdir()
    paths=(ROOT/'sources.txt').read_text().split()+['sources.txt','rtl/executor/instructions.svh','scripts/synth.tcl','scripts/synthesize.py']
    for name in paths:
        target=frozen/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    identity={name:sha(frozen/name) for name in paths}
    inputs=dict(source_sha256=identity,part='xc7a200tffg1156-3',LANES=1,UNROLL=1,PROFILE_ENABLE=False,threads=2,clock_period_ns=10.0,routed_frequency_measured=False)
    write(out/'SOURCE.json',inputs)
    with tarfile.open(out/'rtl.tar.gz','w:gz') as archive:
        for name in paths:archive.add(frozen/name,arcname=name)
    started=time.monotonic()
    try:
        command=[os.environ.get('VIVADO','vivado'),'-mode','batch','-nolog','-nojournal','-source','scripts/synth.tcl','-tclargs',str(out)]
        with (out/'vivado.log').open('w') as log:subprocess.run(command,cwd=frozen,stdout=log,stderr=subprocess.STDOUT,check=True)
        area=resources(out/'utilization.rpt')
        write(out/'results.json',dict(passed=True,area=area,timing=json.loads((out/'timing.json').read_text()),elapsed_seconds=time.monotonic()-started,source_sha256=identity,routed_frequency_measured=False))
        print('MHBS_COMMON_SYNTH_PASS',out,area,flush=True)
    except Exception as error:
        write(out/'failure.json',dict(passed=False,error=str(error),elapsed_seconds=time.monotonic()-started));raise
if __name__=='__main__':main()
