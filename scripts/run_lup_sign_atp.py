#!/usr/bin/env python3
"""Reproducible L2U1P1-P4 common-core area/time sweep; no place/route."""
from legacy_lane_guard import require_legacy_lanes
require_legacy_lanes()
from pathlib import Path
import argparse,csv,hashlib,json,re,shutil,subprocess,sys,tarfile,time
from v42_external_flow import ROOT,BASE,simulate_case,sha,write,rtl
from v42_common_partition import partition
PART='xc7a200tffg1156-3'
FREQ=150.0

def area(path):
 text=path.read_text();a={}
 for label,key in [('Slice LUTs','lut'),('Slice Registers','ff'),('LUT as Memory','lutram'),('Block RAM Tile','bram36'),('DSPs','dsp')]:
  m=re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',text);assert m,label;a[key]=float(m[1].replace(',',''))
 a['equivalent_slice']=a['lut']/4+a['ff']/8+232.4*a['bram36']+102.4*a['dsp'];return a

def prepare_baseline(out):
 archive=out/'baseline.tar.gz'
 if not archive.exists():
  frozen=ROOT/'manifests/experiments/lup_shared_128f_20261007_v1/baseline.tar.gz'
  shutil.copy2(frozen,archive)
 ws=ROOT/'build/lup_shared_baseline';ws.mkdir(parents=True,exist_ok=True)
 with tarfile.open(archive) as t:t.extractall(ws,filter='data')
 hbs=ws/'rtl/top/mhbs_hbs.sv'
 hbs.write_text(hbs.read_text().replace('LANES!=2 || UNROLL!=2','LANES!=2 || (UNROLL!=1 && UNROLL!=2)'))
 tb=ws/'tb/integration/tb_mhbs_external.sv'
 tb.write_text(tb.read_text().replace('parameter integer SWAP=0;','parameter integer SWAP=0,UNROLL=2;').replace('.OPERATION(OPERATION),.PROFILE_ENABLE','.OPERATION(OPERATION),.UNROLL(UNROLL),.PROFILE_ENABLE').replace('round_index+2>=24','round_index+UNROLL>=24'))
 vector=BASE/'vectors/slh_128f/sign';cfg=json.loads((vector/'job.json').read_text())
 params=[f"-G{k.upper()}=256'h{int.from_bytes(bytes.fromhex(cfg[k]),'little'):064x}" for k in ('secret_seed','secret_prf','public_seed','randomizer','public_root')]
 for u in (1,2):
  d=ROOT/f'build/lup_shared_baseline_result/U{u}';d.mkdir(parents=True,exist_ok=True)
  # Source-bound compile cache, with a fresh run on every invocation.
  manifest={'baseline':sha(archive),'testbench':sha(tb),'unroll':u}
  binary=d/'obj/Vtb_mhbs_external'
  if not binary.exists() or not (d/'inputs.json').exists() or json.loads((d/'inputs.json').read_text())!=manifest:
   cmd=['verilator','--binary','--timing','-O3','-j','8','-Wno-fatal','--top-module','tb_mhbs_external',f'-GUNROLL={u}',*params,'--Mdir',str(d/'obj'),*(ws/'manifests/v42_sources.txt').read_text().splitlines(),'tb/integration/tb_mhbs_external.sv']
   with (d/'compile.log').open('w') as f:subprocess.run(cmd,cwd=ws,stdout=f,stderr=subprocess.STDOUT,check=True)
   write(d/'inputs.json',manifest)
  with (d/'run.log').open('w') as f:subprocess.run([str(binary),f'+IMAGE={BASE/"images/slh_128f"}',f'+VECTOR={vector}',f'+DUMP={d/"actual.mem"}'],cwd=ws,stdout=f,stderr=subprocess.STDOUT,check=True)
  print('FROZEN_BASELINE_PASS',f'L2U{u}P1',flush=True)

def baseline(u):
 d=ROOT/f'build/lup_shared_baseline_result/U{u}'
 s=(d/'run.log').read_text();m=re.search(r'EXTERNAL_PASS boot=(\d+) keygen=(\d+) sign=(\d+) hashes=(\d+) permutations=(\d+).*total=(\d+)',s);assert m
 return {'sign_cycles':int(m[3]),'hashes':int(m[4]),'permutations':int(m[5]),'total_cycles':int(m[6]),'output_sha256':sha(d/'actual.mem')}

def check_same(result,ref,cycles=True):
 for k in ('output_sha256','hashes','permutations')+(('sign_cycles','total_cycles') if cycles else ()):
  assert result[k]==ref[k],(k,result[k],ref[k])

def snapshot(out):
 paths=set(rtl()+['manifests/v42_sources.txt','manifests/unified_sources.txt','Makefile','README.md','docs/Architecture.md','docs/Verification.md'])
 for directory in ('scripts','tb','model','tests','experiments/v4.2'):
  paths.update(str(p.relative_to(ROOT)) for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in ('.sv','.svh','.py','.tcl','.mem','.json'))
 for directory in ('images/slh_128f','vectors/slh_128f/sign'):
  paths.update(str(p.relative_to(ROOT)) for p in (BASE/directory).rglob('*') if p.is_file())
 identity={p:sha(ROOT/p) for p in sorted(paths)}
 if (out/'inputs.json').exists():assert json.loads((out/'inputs.json').read_text())['source_sha256']==identity,'Source changed: use fresh experiment tag'
 else:
  with tarfile.open(out/'source_snapshot.tar.gz','w:gz') as t:
   for p in identity:t.add(ROOT/p,arcname=p)
  write(out/'inputs.json',dict(git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_sha256=identity,snapshot_sha256=sha(out/'source_snapshot.tar.gz'),part=PART,clock_period_ns=6.666667,frequency_mhz_assumed=FREQ,profile_enable_synthesis=False,scope='common core',operation='128f sign',routed=False))
 return identity

def synth(out,p,ws,lanes=2,point=None):
 point=point or f'L{lanes}U1P{p}'
 d=out/point;d.mkdir(exist_ok=True)
 common,_=partition((ws/'rtl/top/mhbs_top.sv').read_text(),stub=True)
 (d/'mhbs_common.sv').write_text(common)
 lines=['set_param general.maxThreads 8',f'create_project -in_memory -part {PART}']
 lines += [f'read_verilog -sv {{{ws/f}}}' for f in (ws/'manifests/v42_sources.txt').read_text().splitlines() if f!='rtl/top/mhbs_top.sv']
 (d/'clock.xdc').write_text('create_clock -name clk -period 6.666667 [get_ports clk]\n')
 lines += [f'read_verilog -sv {{{d/"mhbs_common.sv"}}}',f'read_xdc {{{d/"clock.xdc"}}}',f'synth_design -top mhbs_common -part {PART} -mode out_of_context -flatten_hierarchy rebuilt -max_dsp 0 -generic LANES={lanes} -generic UNROLL=1 -generic PIPELINE={p} -generic PROFILE_ENABLE=0',f'report_utilization -file {{{d/"core_utilization.rpt"}}}',f'report_utilization -hierarchical -file {{{d/"core_hierarchical.rpt"}}}',f'report_timing_summary -file {{{d/"core_timing.rpt"}}}',
 'set bad {}', 'foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {', ' if {[string match FD* [get_property REF_NAME $c]] && [regexp {(cycles|hash_count|permutation_count|hash_base|permutation_base)_reg} $c]} {lappend bad $c}', '}', 'if {[llength $bad]} {error "Statistics registers remain: $bad"}',f'set f [open {{{d/"pruning_audit.json"}}} w]', 'puts $f {{"passed":true,"profile_enable":false,"statistics_registers":0}}','close $f',f'write_checkpoint -force {{{d/"post_synth.dcp"}}}',f'puts "LUP_COMMON_SYNTH_PASS {point}"','exit']
 (d/'synth.tcl').write_text('\n'.join(lines)+'\n');start=time.time()
 with (d/'vivado.log').open('w') as f:subprocess.run(['vivado','-mode','batch','-nolog','-nojournal','-source',str(d/'synth.tcl')],cwd=ws,stdout=f,stderr=subprocess.STDOUT,check=True)
 assert f'LUP_COMMON_SYNTH_PASS {point}' in (d/'vivado.log').read_text()
 a=area(d/'core_utilization.rpt');write(d/'synthesis.json',dict(passed=True,area=a,elapsed_seconds=time.time()-start,profile_enable=False,routed=False));print('LUP_SYNTH_PASS',point,int(a['lut']),int(a['ff']),flush=True);return a

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--tag',default='lup_shared_128f_20261007_v2');ap.add_argument('--sim-only',action='store_true');args=ap.parse_args()
 assert re.fullmatch('[a-zA-Z0-9_-]+',args.tag)
 out=ROOT/'manifests/experiments'/args.tag;out.mkdir(parents=True,exist_ok=True)
 build=ROOT/'build'/args.tag;build.mkdir(parents=True,exist_ok=True)
 identity=snapshot(out);prepare_baseline(out);ref=baseline(1);ref2=baseline(2);vector=BASE/'vectors/slh_128f/sign'
 def sim(name,p,**kw):return simulate_case(build,name,vector,unroll=kw.pop('unroll',1),pipeline=p,**kw)[1]
 sims={};checks={}
 for p in (1,2,3,4):
  s=sim(f'L2U1P{p}',p);check_same(s,ref,cycles=p==1);sims[p]=s
  off=sim(f'L2U1P{p}_stats_off',p,profile_enable=False);check_same(off,s);checks[f'P{p}_stats_off']=off
 default=sim('L2U2P1_default',1,unroll=2);check_same(default,ref2);checks['default_unchanged']=default
 for p in (2,3,4):
  replay=sim(f'P{p}_replay_stall',p,options=('+REPLAYS=2','+STALL=1','+INTERRUPT=1','+TAIL_NOISE=1'));assert (replay['hashes'],replay['permutations'])==(sims[p]['hashes'],sims[p]['permutations']);checks[f'P{p}_replay_stall']=replay
 checks['P3_swapped']=sim('P3_swapped',3,swap=1);check_same(checks['P3_swapped'],sims[3])
 checks['P4_partition']=sim('P4_partition',4,partitioned=True);check_same(checks['P4_partition'],sims[4])
 # Error injection reuses the normal binary, retaining the existing halt checks.
 from v42_external_flow import build_binary,run
 cfg=json.loads((vector/'job.json').read_text())
 binary=build_binary(build,cfg,unroll=1,pipeline=4)
 for mode in (1,2):
  log=build/'logs'/f'P4_fault_{mode}.log';run([str(binary),f'+IMAGE={BASE/"images/slh_128f"}',f'+VECTOR={vector}',f'+FAULT={mode}'],log);assert 'V42_FAULT_PASS' in log.read_text()
  checks[f'P4_fault_{mode}']={'passed':True,'log_sha256':sha(log)}
 write(out/'simulation.json',{'points':sims,'checks':checks,'baseline_u1':ref,'baseline_u2':ref2})
 shutil.copytree(build/'logs',out/'simulation',dirs_exist_ok=True)
 for folder in ('lup_shared_units','lup_shared_baseline_result'):
  dest=out/folder;dest.mkdir(exist_ok=True)
  for src in (ROOT/'build'/folder).rglob('*'):
   if src.is_file() and src.suffix in ('.log','.json','.mem') and 'obj' not in src.parts:
    target=dest/src.relative_to(ROOT/'build'/folder);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
 if args.sim_only:return
 ws=build/'synth_source';ws.mkdir(exist_ok=True)
 with tarfile.open(out/'source_snapshot.tar.gz') as t:t.extractall(ws,filter='data')
 for path,h in identity.items():assert sha(ws/path)==h,path
 rows=[]
 for p in (1,2,3,4):
  a=synth(out,p,ws);s=sims[p];ms=s['sign_cycles']/(FREQ*1000)
  row=dict(point=f'L2U1P{p}',**a,compute_cycles=s['sign_cycles'],total_cycles=s['total_cycles'],hashes=s['hashes'],permutations=s['permutations'],assumed_mhz=FREQ,time_ms=ms,atp_slice_ms=a['equivalent_slice']*ms)
  rows.append(row);write(out/f'L2U1P{p}'/'result.json',row)
 for r in rows:r['speedup']=rows[0]['compute_cycles']/r['compute_cycles'];r['relative_atp']=r['atp_slice_ms']/rows[0]['atp_slice_ms']
 write(out/'results.json',{'scope':'128f sign common core','frequency_basis':'assumed 150 MHz; no place/route','points':rows})
 with (out/'results.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
 text='# L2U1P1–P4：128f sign 共同核 ATP\n\n150 MHz 为统一假定频率，未经布局布线验证。面积包含流水寄存器、上下文及结果暂存，不包含顶层签名存储。LUT 已包含 LUTRAM。\n\n'
 text+='| 配置 | LUT | FF | LUTRAM | BRAM36 | 等效 Slice | 计算周期 | 总周期 | 时间 ms | ATP Slice·ms | 相对 ATP |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n'
 for r in rows:text+=f"| {r['point']} | {r['lut']:.0f} | {r['ff']:.0f} | {r['lutram']:.0f} | {r['bram36']:g} | {r['equivalent_slice']:.3f} | {r['compute_cycles']} | {r['total_cycles']} | {r['time_ms']:.6f} | {r['atp_slice_ms']:.3f} | {r['relative_atp']:.4f} |\n"
 text+='\n所有点的签名字节、Hash/置换次数一致：104937 / 105641。P1 与冻结旧 U1 的输出和周期一致，默认 L2U2P1 同样与旧实现一致。统计关闭、输入停顿、复位重放、lane 交换、共同核等价及故障退出检查通过。单元测试包含 U2P2、三种节点宽度、96 组独立 SHAKE 链向量和多上下文回压。\n\nATP = 等效 Slice × 计算周期 / 150000；新实验以 L 表示 lane，历史 K 与 L 同义，历史证据未改写。\n\n源码、配置和原始报告：`manifests/experiments/'+args.tag+'/`。各点的 `core_hierarchical.rpt` 是分层面积报告。本轮未测实际频率。\n'
 (out/'report.md').write_text(text);(ROOT/'docs/v4.2/LUP_128f_Sign_ATP.md').write_text(text)
 write(out/'evidence_sha256.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json' and p.suffix!='.dcp'})
 print('LUP_SWEEP_PASS',str(out/'report.md'),flush=True)
if __name__=='__main__':main()
