import sys,re,concurrent.futures
sys.path.insert(0,'scripts');import run_lu_p1 as m
from model.profiles import PROFILES
label=sys.argv[1] if len(sys.argv)>1 else 'structure'
def work(point):
 l,u=point;d=m.BUILD/'equiv'/f'L{l}U{u}';d.mkdir(parents=True,exist_ok=True)
 src=m.source(label);old=m.source('baseline')
 files=[old/f for f in (old/'manifests/v42_sources.txt').read_text().split() if f!='rtl/top/mhbs_top.sv']
 common,_=m.module(old/'scripts/v42_common_partition.py','old_partition').partition((old/'rtl/top/mhbs_top.sv').read_text())
 refs='\n'.join(f.read_text() for f in files)+'\n'+common
 names=re.findall(r'\bmodule\s+(\w+)',refs)
 for name in names:refs=re.sub(r'\b'+name+r'\b','frozen_'+name,refs)
 (d/'frozen.sv').write_text(refs)
 tb=(src/'tb/integration/tb_mhbs_stateful.sv').read_text()
 outputs=['program_address','template_address','descriptor_addresses','message_ready','verify_ready','verify_pass','out_valid','out_data','out_bytes','result_kind','busy','done','keygen_done','error','error_code','boot_cycles','keygen_cycles','sign_cycles','hash_count','permutation_count']
 widths=[4,4,10,1,1,1,1,256,6,2,1,1,1,1,16,32,32,32,32,32]
 declarations='\n'.join(f'wire [{w-1}:0] ref_{name};' for name,w in zip(outputs,widths))
 instance='frozen_mhbs_common #(.LANES(LANES),.UNROLL(UNROLL),.PROFILE_ENABLE(1)) reference_core('+','.join('.'+n+'(ref_'+n+')' for n in outputs)+',.*);'
 # compare addresses, handshakes and statistics every cycle; output payload only when valid.
 checks='\n'.join(f'if({n}!==ref_{n}) $fatal(1,"equivalence {n}");' for n in outputs if n not in ['out_data','out_bytes','result_kind'])
 inject=declarations+'\n'+instance+'\n always @(negedge clk) if(!rst)begin '+checks+'\nif(out_valid && {out_data,out_bytes,result_kind}!=={ref_out_data,ref_out_bytes,ref_result_kind})$fatal(1,"output equivalence");end\n'
 tb=tb.replace(' logic read_enable=0;',inject+' logic read_enable=0;');(d/'tb.sv').write_text(tb)
 common,_=m.module(src/'scripts/v42_common_partition.py','new_partition').partition((src/'rtl/top/mhbs_top.sv').read_text());(d/'mhbs_common.sv').write_text(common)
 files=[src/f for f in (src/'manifests/v42_sources.txt').read_text().split() if f!='rtl/top/mhbs_top.sv']+[d/'mhbs_common.sv',d/'frozen.sv',d/'tb.sv']
 logdir=m.OUT/'equivalence';logdir.mkdir(exist_ok=True)
 m.run(['verilator','--binary','--timing','-j','2','-O3','-Wno-fatal','-Wno-WIDTH','--top-module','tb_mhbs_stateful',f'-GLANES={l}',f'-GUNROLL={u}','--Mdir',d/'obj',*files],logdir/f'L{l}U{u}_compile.log')
 for profile in PROFILES:
  for op in range(3):m.run([d/'obj/Vtb_mhbs_stateful',f'+VECTOR={m.OUT/"vectors"/profile/str(op)}'],logdir/f'L{l}U{u}_{profile}_{op}.log')
 print('EQUIV_PASS',l,u,flush=True)
with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(work,[(1,1),(1,2),(2,1),(2,2)]))
