#!/usr/bin/env python3
"""Icarus 12 units and boot rejection for the active SLH-only core."""
from pathlib import Path
import hashlib,json,re,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from autonomous_flow import logic,logic_id

identity=logic()
OUT=ROOT/'manifests/experiments/unified_hbs_v4.1/slh_only/unit'/logic_id(identity)
BUILD=ROOT/'build/v4.1/slh_only/unit'
OUT.mkdir(parents=True,exist_ok=True);BUILD.mkdir(parents=True,exist_ok=True)
rtl=(ROOT/'manifests/unified_sources.txt').read_text().splitlines()
records={}

def one(name,top,files,params=(),runs=((),)):
    assert logic()==identity
    binary=BUILD/(name+'.vvp')
    with (OUT/(name+'.log')).open('w') as log:
        subprocess.run(['iverilog','-g2012','-s',top,*params,'-o',str(binary),*files],
                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        for options in runs:
            subprocess.run(['vvp',str(binary),*options],cwd=ROOT,stdout=log,
                           stderr=subprocess.STDOUT,check=True)
    records[name]=hashlib.sha256((OUT/(name+'.log')).read_bytes()).hexdigest()
    print('SLH_UNIT_PASS',name,flush=True)

one('endpoint_68','tb_uhbs_value_store',
    ['rtl/memory/uhbs_value_store.sv','tb/unit/tb_uhbs_value_store.sv'],
    ['-Ptb_uhbs_value_store.DEPTH=68'])
one('fors_roots','tb_uhbs_root_store',
    ['rtl/memory/uhbs_root_store.sv','tb/unit/tb_uhbs_root_store.sv'])
one('program','tb_uhbs_program_bounds',
    ['rtl/sequencer/uhbs_event_scoreboard.sv','rtl/sequencer/uhbs_program_sequencer.sv',
     'tb/unit/tb_uhbs_program_bounds.sv'])
one('sponge','tb_uhbs_compact_shake_context_lane',
    ['rtl/hash_lane/uhbs_keccak.sv','rtl/hash_lane/uhbs_compact_shake_context_lane.sv',
     'tb/unit/tb_uhbs_compact_shake_context_lane.sv'])
for p in range(3):
    one('recipe_'+str(p),'tb_uhbs_recipe_lane',
        ['rtl/hash_lane/uhbs_keccak.sv','rtl/hash_lane/uhbs_compact_shake_context_lane.sv',
         'rtl/hash_lane/uhbs_recipe_lane.sv','tb/unit/tb_uhbs_recipe_lane.sv'],
        [f'-Ptb_uhbs_recipe_lane.PROFILE={p}'])
slh='manifests/experiments/unified_hbs_v4.1/slh_only/images/slh_128f'
legacy='manifests/experiments/unified_hbs_v4.1/images'
runs=[[f'+IMAGE={slh}',f'+BAD={bad}'] for bad in (1,2,3,11,23,24,25,26,27,28,29,30)]
runs += [[f'+IMAGE={legacy}/{name}','+BAD=22'] for name in
         ('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4')]
one('boot_reject','tb_uhbs_autonomous',rtl+['tb/integration/tb_uhbs_autonomous.sv'],runs=runs)
assert logic()==identity
(OUT/'results.json').write_text(json.dumps({'passed':True,'logic_sha256':identity,
    'tool':subprocess.check_output(['iverilog','-V'],text=True,stderr=subprocess.DEVNULL).splitlines()[0],
    'logs':records},indent=2)+'\n')
