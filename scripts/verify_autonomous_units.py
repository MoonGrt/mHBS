#!/usr/bin/env python3
"""Small v4.1 units on Icarus 12, full algorithms on Verilator 5.008."""
from pathlib import Path
import subprocess,json,hashlib,concurrent.futures
ROOT=Path(__file__).resolve().parents[1]
from autonomous_flow import logic,logic_id
verified_logic=logic()
OUT=ROOT/'manifests/experiments/unified_hbs_v4.1/unit'/logic_id(verified_logic);OUT.mkdir(parents=True,exist_ok=True)
BUILD=ROOT/'build/v4.1/unit';BUILD.mkdir(parents=True,exist_ok=True)
rtl=(ROOT/'manifests/unified_sources.txt').read_text().splitlines()
def execute(name,top,files,params=(),runs=((),)):
    assert logic()==verified_logic,'RTL changed during unit verification; rerun from a stable source snapshot'
    binary=BUILD/(name+'.vvp');log=OUT/(name+'.log')
    with log.open('w') as f:
        subprocess.run(['iverilog','-g2012','-s',top,*params,'-o',str(binary),*files],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
        for options in runs:subprocess.run(['vvp',str(binary),*options],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    print('UNIT_PASS',name,flush=True)
    return name,hashlib.sha256(log.read_bytes()).hexdigest()
records={}
for name,top,files in [('roots','tb_mhbs_root_store',['rtl/memory/mhbs_root_store.sv']),('store','tb_mhbs_value_store',['rtl/memory/mhbs_value_store.sv']),('program','tb_mhbs_program_bounds',['rtl/sequencer/mhbs_event_scoreboard.sv','rtl/sequencer/mhbs_program_sequencer.sv']),('compact','tb_mhbs_compact_shake_context_lane',['rtl/hash_lane/mhbs_keccak.sv','rtl/hash_lane/mhbs_compact_shake_context_lane.sv'])]:
    records.update([execute(name,top,files+[f'tb/unit/{top}.sv'])])
def recipe(p):return execute('recipe_'+str(p),'tb_mhbs_recipe_lane',['rtl/hash_lane/mhbs_keccak.sv','rtl/hash_lane/mhbs_compact_shake_context_lane.sv','rtl/hash_lane/mhbs_recipe_lane.sv','tb/unit/tb_mhbs_recipe_lane.sv'],[f'-Ptb_mhbs_recipe_lane.PROFILE={p}'])
with concurrent.futures.ThreadPoolExecutor(4) as pool:records.update(pool.map(recipe,range(7)))
records.update([execute('boot','tb_mhbs_autonomous',rtl+['tb/integration/tb_mhbs_autonomous.sv'],runs=[['+IMAGE=manifests/experiments/unified_hbs_v4.1/images/xmss_omega4',f'+BAD={b}'] for b in range(1,15)]+[['+IMAGE=manifests/experiments/unified_hbs_v4.1/images/'+p,'+BAD=3'] for p in ('xmss_omega2','lms_omega2','lms_omega4')])])
records.update([execute('boot_drain','tb_mhbs_boot_drain',rtl+['tb/integration/tb_mhbs_autonomous.sv','tb/unit/tb_mhbs_boot_drain.sv'],runs=[['+IMAGE=manifests/experiments/unified_hbs_v4.1/images/xmss_omega4',f'+BAD={b}'] for b in (15,16,17)])])
assert logic()==verified_logic,'RTL changed during unit verification'
(OUT/'results.json').write_text(json.dumps(dict(pass_all=True,index_policy='fixed_q_no_guard',bench_sha256=hashlib.sha256((ROOT/'tb/integration/tb_mhbs_autonomous.sv').read_bytes()).hexdigest(),test_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'tb/unit').glob('*.sv')},tool=subprocess.check_output(['iverilog','-V'],text=True,stderr=subprocess.DEVNULL).splitlines()[0],logic_sha256=verified_logic,logs=records),indent=2)+'\n')
