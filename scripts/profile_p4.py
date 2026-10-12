#!/usr/bin/env python3
"""Profile the three P4 targets without modifying the DUT or production harness."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INSTRUMENT = r'''
 longint states[0:127], returns[0:127], recipes[0:15], live[0:4];
 initial begin
  for(integer i=0;i<128;i++)begin states[i]=0;returns[i]=0;end
  for(integer i=0;i<16;i++)recipes[i]=0;
  for(integer i=0;i<5;i++)live[i]=0;
 end
 always @(posedge clk)if(!rst && dut.core.state!=0 && dut.core.state!=32)begin
  states[dut.core.state]++;
  if(dut.core.state==23)begin returns[dut.core.continuation]++;recipes[dut.core.task_recipe[59:56]]++;end
  if(dut.core.pipe_mode)live[$countones(dut.core.lane.stage_valid)]++;
 end
 final begin
  for(integer i=0;i<128;i++)if(states[i])$display("PROFILE_STATE %0d %0d",i,states[i]);
  for(integer i=0;i<128;i++)if(returns[i])$display("PROFILE_RETURN %0d %0d",i,returns[i]);
  for(integer i=0;i<16;i++)if(recipes[i])$display("PROFILE_RECIPE %0d %0d",i,recipes[i]);
  for(integer i=0;i<5;i++)$display("PROFILE_LIVE %0d %0d",i,live[i]);
 end
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, default=ROOT/'build/p4_profile')
    parser.add_argument('--stateful-operation',choices=('sign','keygen'),default='keygen')
    args = parser.parse_args();source=args.source.resolve();out=args.output.resolve();out.mkdir(parents=True, exist_ok=True)
    harness=(source/'tb/tb.sv').read_text();(out/'tb.sv').write_text(harness.rsplit('endmodule', 1)[0]+INSTRUMENT+'\nendmodule\n')
    enum=re.search(r'typedef enum logic \[\d+:0\] \{(.*?)\} state_t;', (source/'rtl/executor/executor.sv').read_text(), re.S)[1]
    enum=re.sub(r'//[^\n]*', '', enum);names={};value=0
    for entry in enum.split(','):
        fields=entry.strip().split('=');name=fields[0].strip()
        if len(fields)>1:value=int(fields[1])
        names[value]=name;value+=1
    (out/'state_names.json').write_text(json.dumps(names, indent=2)+'\n')
    sources=[str(source/p) for p in (source/'sources.txt').read_text().splitlines()]
    command=[os.environ.get('VERILATOR','verilator'),'--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb','-GPIPELINE=4','-GUNROLL=1','--Mdir',str(out/'obj'),*sources,str(out/'tb.sv')]
    with (out/'compile.log').open('w') as log:subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    results={}
    for profile,op in (('slh_128f','sign'),('xmss_h10',args.stateful_operation),('lms_h10',args.stateful_operation)):
        key=f'{profile}_{op}'
        with (out/f'{key}.log').open('w') as log:subprocess.run([str(out/'obj/Vtb'),f'+VECTOR={ROOT}/tb/vectors/{profile}/{op}'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        text=(out/f'{key}.log').read_text();results[key]={}
        for kind in ('STATE','RETURN','RECIPE','LIVE'):
            records={int(i):int(n) for i,n in re.findall(rf'PROFILE_{kind} (\d+) (\d+)',text)}
            results[key][kind.lower()]=records
        match=re.search(r'STATEFUL_PASS .*?cycles=(\d+).*?hashes=(\d+) permutations=(\d+)',text)
        if not match:raise ValueError(f'missing pass: {key}')
        results[key]['cycles'],results[key]['hashes'],results[key]['permutations']=map(int,match.groups())
        print(key,results[key]['cycles'],flush=True)
    (out/'profile.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':main()
