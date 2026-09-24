#!/usr/bin/env python3
"""Small v4.1 units on Icarus 12, full algorithms on Verilator 5.008."""
from pathlib import Path
import subprocess,json,hashlib,concurrent.futures
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'manifests/experiments/unified_hbs_v4.1/unit';OUT.mkdir(parents=True,exist_ok=True)
BUILD=ROOT/'build/v4.1/unit';BUILD.mkdir(parents=True,exist_ok=True)
rtl=(ROOT/'manifests/unified_sources.txt').read_text().splitlines()
def execute(name,top,files,params=(),runs=((),)):
    binary=BUILD/(name+'.vvp');log=OUT/(name+'.log')
    with log.open('w') as f:
        subprocess.run(['iverilog','-g2012','-s',top,*params,'-o',str(binary),*files],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
        for options in runs:subprocess.run(['vvp',str(binary),*options],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    print('UNIT_PASS',name,flush=True)
    return name,hashlib.sha256(log.read_bytes()).hexdigest()
records={}
for name,top,files in [('store','tb_uhbs_value_store',['rtl/memory/uhbs_value_store.sv']),('guard','tb_uhbs_stateful_index_guard',['rtl/control/uhbs_stateful_index_guard.sv']),('program','tb_uhbs_program_bounds',['rtl/sequencer/uhbs_event_scoreboard.sv','rtl/sequencer/uhbs_program_sequencer.sv']),('compact','tb_uhbs_compact_shake_context_lane',['rtl/hash_lane/uhbs_keccak.sv','rtl/hash_lane/uhbs_compact_shake_context_lane.sv'])]:
    records.update([execute(name,top,files+[f'tb/unit/{top}.sv'])])
def recipe(p):return execute('recipe_'+str(p),'tb_uhbs_recipe_lane',['rtl/hash_lane/uhbs_keccak.sv','rtl/hash_lane/uhbs_compact_shake_context_lane.sv','rtl/hash_lane/uhbs_recipe_lane.sv','tb/unit/tb_uhbs_recipe_lane.sv'],[f'-Ptb_uhbs_recipe_lane.PROFILE={p}'])
with concurrent.futures.ThreadPoolExecutor(4) as pool:records.update(pool.map(recipe,range(7)))
records.update([execute('boot','tb_uhbs_autonomous',rtl+['tb/integration/tb_uhbs_autonomous.sv'],runs=[['+IMAGE=manifests/experiments/unified_hbs_v4.1/images/xmss_omega4',f'+BAD={b}'] for b in range(1,15)])])
(OUT/'results.json').write_text(json.dumps(dict(pass_all=True,tool=subprocess.check_output(['iverilog','-V'],text=True,stderr=subprocess.DEVNULL).splitlines()[0],logic_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in rtl},logs=records),indent=2)+'\n')
