#!/usr/bin/env python3
"""Verilator units for the trusted-image SLH-only core."""
from pathlib import Path
import hashlib,json,re,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
def logic():
    return {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in (ROOT/'manifests/v42_sources.txt').read_text().split()}
def logic_id(x):return hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()[:16]

identity=logic()
OUT=ROOT/'manifests/experiments/unified_hbs_v4.2/unit'/logic_id(identity)
BUILD=ROOT/'build/v4.2/unit'/logic_id(identity)
OUT.mkdir(parents=True,exist_ok=True);BUILD.mkdir(parents=True,exist_ok=True)
rtl=(ROOT/'manifests/v42_sources.txt').read_text().splitlines()
refs=['tb/reference/mhbs_shake_pre_direct_ref.sv','tb/reference/mhbs_recipe_pre_direct_ref.sv']
legacy=BUILD/'mhbs_recipe_lane_value_narrow_ref.sv'
legacy.write_text((ROOT/'tb/reference/mhbs_recipe_lane_value_narrow_ref.sv').read_text().replace('mhbs_compact_shake_context_lane','mhbs_shake_pre_direct_ref'))
records={}
used_sources=set()

def one(name,top,files,params=(),runs=((),)):
    assert logic()==identity
    files=list(dict.fromkeys(files+refs))
    used_sources.update(files)
    obj=BUILD/name
    binary=obj/('V'+top)
    params=[re.sub(r'^-P'+re.escape(top)+r'\.', '-G', p) for p in params]
    with (OUT/(name+'.log')).open('w') as log:
        subprocess.run(['verilator','--binary','--timing','-j','2','-Wno-fatal','-Wno-WIDTH','--top-module',top,*params,'--Mdir',str(obj),*files],
                       cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        for options in runs:
            subprocess.run([str(binary),*options],cwd=ROOT,stdout=log,
                           stderr=subprocess.STDOUT,check=True)
    records[name]=hashlib.sha256((OUT/(name+'.log')).read_bytes()).hexdigest()
    print('SLH_UNIT_PASS',name,flush=True)

one('signature_store','tb_mhbs_signature_store',
    ['rtl/memory/mhbs_signature_store.sv','tb/unit/tb_mhbs_signature_store.sv'])

one('s_parameters','tb_mhbs_s_parameters',rtl+['tb/unit/tb_mhbs_s_parameters.sv'])
one('address_width','tb_mhbs_address_width',rtl+['tb/unit/tb_mhbs_address_width.sv'])

# Compare the consumed fixed blocks against the frozen pre-specialization
# implementation for both production masks and the generic compatibility path.
for mask in (0x101e,0x0006,0xffff):
    one('slh_fixed_block_'+format(mask,'04x'),'tb_mhbs_slh_fixed_block',
        ['rtl/hash_lane/mhbs_keccak.sv',
         'rtl/hash_lane/mhbs_recipe_lane.sv',str(legacy.relative_to(ROOT)),
         'tb/unit/tb_mhbs_slh_fixed_block.sv'],
        [f'-Ptb_mhbs_slh_fixed_block.MASK={mask}'])

one('endpoint_68','tb_mhbs_value_store',
    ['rtl/memory/mhbs_value_store.sv','tb/unit/tb_mhbs_value_store.sv'],
    ['-Ptb_mhbs_value_store.DEPTH=68'])
one('endpoint_68_single_read','tb_mhbs_value_store',
    ['rtl/memory/mhbs_value_store.sv','tb/unit/tb_mhbs_value_store.sv'],
    ['-Ptb_mhbs_value_store.DEPTH=68','-Ptb_mhbs_value_store.SINGLE_READ=1'])
one('slh64_sequencer','tb_mhbs_slh64_sequencer',
    ['rtl/sequencer/mhbs_program_sequencer.sv','tb/unit/tb_mhbs_slh64_sequencer.sv'])
for p in range(3):
    one('recipe_'+str(p),'tb_mhbs_v42_recipe_lane',
        ['rtl/hash_lane/mhbs_keccak.sv',
         'rtl/hash_lane/mhbs_recipe_lane.sv','tb/unit/tb_mhbs_v42_recipe_lane.sv'],
        [f'-Ptb_mhbs_v42_recipe_lane.PROFILE={p}'])
# Independent SHAKE vectors alternate compact and ordinary feedback chains,
# including first/middle/final captures and backpressured consecutive requests.
for profile,n in enumerate((16,24,32)):
    vectors=[]
    for steps,capture in ((0,0),(1,0),(1,1),(15,0),(15,7),(15,15)):
        for shape in (1,2):
            seed=(shape<<56)|((6 if shape==1 else 0)<<48)|(1<<40)
            step=(2<<56)|(1<<40)
            public=bytes(range(64,64+n));secret=bytes(range(n))
            value=bytes(range(160,160+n));captured=None
            for iteration in range(steps+1):
                domain=6 if shape==1 and iteration==0 else 0
                b=7 if iteration==0 else iteration-1
                address=b''.join(x.to_bytes(4,'big') for x in (0,0,0,0,domain,5,3,b))
                payload=public+address+(secret if shape==1 and iteration==0 else value)
                digest=hashlib.shake_256(payload).digest(49)
                value=digest[:n]
                if iteration==capture:captured=value
            vectors.append((seed<<960)|(step<<896)|(1<<895)|(steps<<890)|(capture<<885)|
                           (3<<877)|(7<<845)|(n<<839)|
                           (int.from_bytes(digest,'little')<<256)|int.from_bytes(captured,'little'))
    path=OUT/f'chain_capture_{profile}.mem'
    path.write_text(''.join(f'{v:0256x}\n' for v in vectors))
    one('chain_capture_'+str(profile),'tb_mhbs_v42_recipe_lane',
        ['rtl/hash_lane/mhbs_keccak.sv',
         'rtl/hash_lane/mhbs_recipe_lane.sv','tb/unit/tb_mhbs_v42_recipe_lane.sv'],
        [f'-Ptb_mhbs_v42_recipe_lane.PROFILE={profile}',
         '-Ptb_mhbs_v42_recipe_lane.MASK=6',f'-Ptb_mhbs_v42_recipe_lane.CASES={len(vectors)}'],
        runs=((f'+VECTORS={path.relative_to(ROOT)}',),))
# Independent hashlib vectors exercise padding on both sides of the rate
# boundary and change the cached request fields between consecutive hashes.
padding=[]
for n,shape,m in [(16,4,87),(32,3,72),(24,4,65),(32,4,39),(24,4,64),
                  (32,3,73),(24,4,63),(32,4,41),(32,3,71),(32,4,40)]:
    prf=bytes(range(32,32+n));seed=bytes(range(64,64+n))
    randomizer=bytes(range(96,96+n));root=bytes(range(128,128+n))
    payload=(prf+randomizer if shape==3 else randomizer+seed+root)+bytes(range(m))
    digest=hashlib.shake_256(payload).digest(49)
    padding.append((n<<442)|(shape<<438)|(m<<431)|((len(payload)//136+1)<<423)|
                   int.from_bytes(digest,'little'))
padding_file=OUT/'recipe_padding.mem'
padding_file.write_text(''.join(f'{v:0112x}\n' for v in padding))
one('recipe_padding','tb_mhbs_recipe_padding',
    ['rtl/hash_lane/mhbs_keccak.sv',
     'rtl/hash_lane/mhbs_recipe_lane.sv','tb/unit/tb_mhbs_recipe_padding.sv'],
    runs=((f'+VECTORS={padding_file.relative_to(ROOT)}',),))
assert logic()==identity
(OUT/'results.json').write_text(json.dumps({'passed':True,'logic_sha256':identity,
    'test_source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                          for p in sorted(used_sources)},
    'tool':subprocess.check_output(['verilator','--version'],text=True,stderr=subprocess.DEVNULL).splitlines()[0],
    'logs':records},indent=2)+'\n')
