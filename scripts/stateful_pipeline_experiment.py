#!/usr/bin/env python3
"""Frozen single-lane XMSS/LMS pipeline experiments; Verilator and OOC synthesis."""
from pathlib import Path
import argparse
import concurrent.futures
import csv
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'manifests/experiments/stateful_pipeline_20261012'
BUILD=ROOT/'build/stateful_pipeline_20261012'
POINTS=[(p,u) for p in (1,4,12) for u in (1,2)]
PROFILES=('xmss_omega2','xmss_omega4','lms_omega2','lms_omega4')
VECTORS=ROOT/'manifests/experiments/fixed_p4u2_20261009/vectors/jobs'
SOURCE_LOCK=threading.Lock()

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    temporary=p.with_suffix(p.suffix+'.tmp');temporary.write_text(json.dumps(x,indent=2)+'\n');temporary.replace(p)
def freeze(label):
    d=OUT/label;d.mkdir(parents=True,exist_ok=True)
    if (d/'inputs.json').exists():return d
    names=(ROOT/'manifests/v42_sources.txt').read_text().split()
    names+=['manifests/v42_sources.txt','scripts/v42_common_partition.py','scripts/stateful_pipeline_experiment.py','scripts/run_stateful_keygen_pu13.py','tb/integration/tb_mhbs_stateful.sv']
    names+=list(str(f.relative_to(ROOT)) for f in (ROOT/'tb/unit').glob('*'))
    names+=list(str(f.relative_to(ROOT)) for f in (ROOT/'tb/reference').glob('*') if f.is_file())
    names+=list(str(f.relative_to(ROOT)) for f in VECTORS.rglob('*') if f.is_file())
    with tarfile.open(d/'source_snapshot.tar.gz','w:gz') as t:
        for name in sorted(set(names)):t.add(ROOT/name,arcname=name)
    patch=subprocess.check_output(['git','diff','HEAD','--','rtl','tb','scripts'])
    for name in subprocess.check_output(['git','ls-files','--others','--exclude-standard','scripts','tb'],text=True).splitlines():
        patch+=subprocess.run(['git','diff','--no-index','--','/dev/null',name],capture_output=True).stdout
    (d/'source.patch').write_bytes(patch)
    write(d/'inputs.json',dict(git_head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),source_sha256={n:sha(ROOT/n) for n in names},archive_sha256=sha(d/'source_snapshot.tar.gz'),points=POINTS))
    return d
def source(label):
    d=OUT/label;info=json.loads((d/'inputs.json').read_text());assert sha(d/'source_snapshot.tar.gz')==info['archive_sha256']
    s=BUILD/label/'source'
    with SOURCE_LOCK:
        if not s.exists():
            s.mkdir(parents=True)
            with tarfile.open(d/'source_snapshot.tar.gz') as t:t.extractall(s,filter='data')
    for n,h in info['source_sha256'].items():assert sha(s/n)==h,n
    return s
def tool(cmd,log,cwd):
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as f:subprocess.run(list(map(str,cmd)),cwd=cwd,stdout=f,stderr=subprocess.STDOUT,check=True)
def build(label,p,u,stats=1):
    s=source(label);d=OUT/label/f'P{p}U{u}_stats{stats}';d.mkdir(parents=True,exist_ok=True)
    work=BUILD/label/d.name;binary=work/'obj/Vtb_mhbs_stateful'
    if binary.exists():return binary
    work.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('partition_'+label,s/'scripts/v42_common_partition.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    common,_=mod.partition((s/'rtl/top/mhbs_top.sv').read_text(),stub=True)
    (d/'mhbs_common.sv').write_text(common)
    files=[s/n for n in (s/'manifests/v42_sources.txt').read_text().split() if n!='rtl/top/mhbs_top.sv']
    tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_mhbs_stateful',f'-GPIPELINE={p}',f'-GUNROLL={u}',f'-GPROFILE_ENABLE={stats}','--Mdir',work/'obj',*files,d/'mhbs_common.sv',s/'tb/integration/tb_mhbs_stateful.sv'],d/'compile.log',s)
    return binary
def run(label,p,u,name,op,stats=1,options=(),suffix='',vector=None):
    binary=build(label,p,u,stats);d=OUT/label/f'P{p}U{u}_stats{stats}'
    v=vector or VECTORS/name/str(op);log=d/f'{name}_{op}{suffix}.log';result=log.with_suffix('.json')
    if result.exists():
        row=json.loads(result.read_text())
        assert row['log_sha256']==sha(log),log
        observed=re.search(r'BATCH_OBSERVED requests=(\d+) returns=(\d+) max_live=(\d+)',log.read_text())
        if observed:row.update(batch_requests=int(observed[1]),batch_returns=int(observed[2]),max_live=int(observed[3]))
        row.update(binary_sha256=sha(binary),vector_sha256={f.name:sha(f) for f in v.glob('*.mem')},options=list(options))
        write(result,row);return row
    tool([binary,f'+VECTOR={v}',*options],log,ROOT)
    match=re.search(r'STATEFUL_PASS .*?op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+)',log.read_text())
    if not match:
        assert any(x in log.read_text() for x in ('STATEFUL_FAULT_PASS','INDEX_REJECT_PASS')),log
        row=dict(profile=name,p=p,u=u,stats=stats,operation=op,passed=True)
    else:
        row=dict(profile=name,p=p,u=u,stats=stats,operation=int(match[1]),compute_cycles=int(match[2]),total_cycles=int(match[3]),hashes=int(match[4]),permutations=int(match[5]))
    observed=re.search(r'BATCH_OBSERVED requests=(\d+) returns=(\d+) max_live=(\d+)',log.read_text())
    if observed:row.update(batch_requests=int(observed[1]),batch_returns=int(observed[2]),max_live=int(observed[3]))
    row.update(log_sha256=sha(log),binary_sha256=sha(binary),vector_sha256={f.name:sha(f) for f in v.glob('*.mem')},options=list(options))
    write(result,row);print('PASS',label,d.name,name,op,row.get('compute_cycles'),flush=True);return row
def matrix(label):
    def point(pu):
        p,u=pu
        return [run(label,p,u,n,op) for n in PROFILES for op in (0,1,2)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        rows=sum(list(pool.map(point,POINTS)),[])
    write(OUT/label/'matrix.json',rows)

def unit_vectors():
    d=OUT/'unit_vectors';d.mkdir(parents=True,exist_ok=True)
    h=lambda x:hashlib.shake_256(x).digest(32)
    be=lambda x,n=4:x.to_bytes(n,'big')
    secret=bytes(range(32));public=bytes(range(64,96));identifier=bytes(range(16))
    rows=[]
    for i in range(72):
        kind=1+i%2;no_seed=(i//2)%2;start=(i//4)%16 if no_seed else 0
        steps=(0,15-start,min(3,15-start))[i%3]
        cap=(start,start+steps,start+steps//2,31)[(i//3)%4];enabled=i%5!=0
        a=(0,66,132)[(i//5)%3];q=(0,1,1023)[(i//7)%3]
        initial=h(be(i));value=initial
        addr=lambda j:bytes(12)+be(0)+be(q)+be(a)+be(j)
        if not no_seed:
            value=h(be(4,32)+secret+public+addr(0)+be(0)) if kind==1 else h(identifier+be(q)+be(a,2)+b'\xff'+secret)
        capture=value if enabled and cap==start else bytes(32)
        for j in range(start,start+steps):
            if kind==1:
                key=h(be(3,32)+public+addr(j)+be(0));mask=h(be(3,32)+public+addr(j)+be(1))
                value=h(bytes(32)+key+bytes(a^b for a,b in zip(value,mask)))
            else:value=h(identifier+be(q)+be(a,2)+be(j,1)+value)
            if enabled and cap==j+1:capture=value
        req=kind|(no_seed<<2)|(start<<4)|(steps<<8)|(cap<<16)|(enabled<<21)|(a<<24)|(q<<32)|(int.from_bytes(initial,'little')<<256)
        rows.append((req,int.from_bytes(value,'little'),int.from_bytes(capture,'little')))
    for k,name,width in ((0,'requests',128),(1,'results',64),(2,'captures',64)):
        (d/f'{name}.mem').write_text(''.join(f'{r[k]:0{width}x}\n' for r in rows))
    return d

def unit(label,p,u):
    s=source(label);v=unit_vectors();d=OUT/label/f'unit_P{p}U{u}';d.mkdir(parents=True,exist_ok=True)
    work=BUILD/label/d.name;work.mkdir(parents=True,exist_ok=True);binary=work/'obj/Vtb_mhbs_stateful_pipeline'
    if not binary.exists():
        files=[s/n for n in (s/'manifests/v42_sources.txt').read_text().split() if n.startswith('rtl/hash_lane/')]
        tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_mhbs_stateful_pipeline',f'-GPIPELINE={p}',f'-GUNROLL={u}','--Mdir',work/'obj',*files,s/'tb/unit/tb_mhbs_stateful_pipeline.sv'],d/'compile.log',s)
    tool([binary,f'+VECTORS={v}'],d/'run.log',s)
    assert 'STATEFUL_PIPE_UNIT_PASS' in (d/'run.log').read_text()
    print('UNIT_PASS',p,u,flush=True)

def synthesis(label):
    s=source(label)
    spec=importlib.util.spec_from_file_location('synth_helper',s/'scripts/run_stateful_keygen_pu13.py')
    sys.path.insert(0,str(s/'scripts'));helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    def point(pu):
        p,u=pu;name=f'P{p}U{u}';(OUT/label/name).mkdir(parents=True,exist_ok=True)
        area=helper.synth(OUT/label,s,name,p,u);print('SYNTH_PASS',name,area,flush=True);return dict(p=p,u=u,**area)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:rows=list(pool.map(point,POINTS))
    write(OUT/label/'area.json',rows)

def units(label):
    points=[(p,1) for p in (2,3,4,6,8,12)]+[(p,2) for p in (2,3,4,6,12)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(lambda pu:unit(label,*pu),points))
    write(OUT/label/'units.json',dict(passed=True,points=points,cases_per_point=72,p1='ordinary path checked by normal matrix'))

def regression(label):
    # The same frozen ROMs and vectors must produce the same SLH cycles.
    names=('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s')
    rows=[]
    for n in names:
        for op in (0,1,2):
            old=run('baseline',4,1,n,op);new=run(label,4,1,n,op)
            for k in ('compute_cycles','total_cycles','hashes','permutations'):assert old[k]==new[k],(n,op,k)
            rows.append(new)
    for p,u in POINTS:
        old=run('baseline',p,u,'slh_128f',1);new=run(label,p,u,'slh_128f',1)
        assert old['compute_cycles']==new['compute_cycles']
        assert (new['hashes'],new['permutations'])==(104937,105641)
        rows.append(new)
    write(OUT/label/'slh_regression.json',rows)

def edges(label):
    rows=[];p,u=4,1
    for n in PROFILES:
        for t in range(1,6):rows.append(run(label,p,u,n,2,options=(f'+TAMPER={t}',),suffix=f'_tamper{t}'))
        for name,options in [('stall_reset',('+STALL=1','+REPLAYS=2','+INTERRUPT=1')),('cut',('+CUT=3',)),('fault',('+FAULT=2',)),('invalid',('+Q=1024','+INVALID=1'))]:
            rows.append(run(label,p,u,n,2,options=options,suffix='_'+name))
        for q in (1,1023):
            for op in (1,2):
                v=ROOT/f'manifests/experiments/stateful_20261008/vectors/{n}/q{q}_m1/{op}'
                rows.append(run(label,p,u,n,op,vector=v,suffix=f'_q{q}'))
        for size in (7,8,9,87):
            v=ROOT/f'manifests/experiments/stateful_20261008/vectors/{n}/q0_m{size}/2'
            rows.append(run(label,p,u,n,2,vector=v,suffix=f'_m{size}',options=('+STALL=1',)))
        for op in (0,1,2):
            ref=run(label,p,u,n,op);off=run(label,p,u,n,op,stats=0)
            for key in ('compute_cycles','hashes','permutations'):assert ref[key]==off[key],(n,op,key)
            rows.append(off)
    write(OUT/label/'edges.json',rows)

def partition_checks(label):
    s=source(label);rows=[]
    for n in PROFILES:
        d=OUT/label/('partition_'+n);d.mkdir(parents=True,exist_ok=True)
        work=BUILD/label/d.name;work.mkdir(parents=True,exist_ok=True)
        v=VECTORS/n/'2';cfg=[int(x,16) for x in (v/'job.mem').read_text().split()]
        params=[f'.{name}({width}\'h{cfg[i]:x})' for i,(name,width) in enumerate([('SECRET_SEED',256),('SECRET_PRF',256),('PUBLIC_SEED',256),('RANDOMIZER',256),('PUBLIC_ROOT',256),('IDENTIFIER',128),('KEY_INDEX',32),('OPERATION',2)])]
        params+=['.PIPELINE(PIPELINE)','.UNROLL(UNROLL)','.PROFILE_ENABLE(PROFILE_ENABLE)','.PROGRAM_INIT_FILE("")','.TEMPLATE_INIT_FILE("")','.DESCRIPTOR_INIT_FILE("")']
        widths={'message_ready':1,'verify_ready':1,'verify_pass':1,'out_valid':1,'out_data':256,'out_bytes':6,'result_kind':2,'busy':1,'done':1,'keygen_done':1,'error':1,'error_code':16,'boot_cycles':32,'keygen_cycles':32,'sign_cycles':32,'hash_count':32,'permutation_count':32}
        extra='\n'+''.join(f'wire [{w-1}:0] top_{name};\n' for name,w in widths.items())
        extra+='mhbs_top #('+','.join(params)+') full_top(.clk,.rst,.message_valid,.message_data,.message_length,.verify_valid,.verify_data,.signature_read_enable(1\'b0),.signature_read_address(11\'d0),'+','.join(f'.{name}(top_{name})' for name in widths)+');\n'
        extra+='initial begin #1; $readmemh("'+str(v/'program.mem')+'",full_top.program_memory);$readmemh("'+str(v/'template.mem')+'",full_top.template_memory);$readmemh("'+str(v/'descriptor.mem')+'",full_top.descriptor_memory);end\n'
        ports=[x for x in widths if x not in ('out_data','out_bytes')]
        extra+='always @(negedge clk)if(!rst)begin\nif({'+','.join(ports)+'}!=={'+','.join('top_'+x for x in ports)+'})$fatal(1,"partition control equivalence");\nif(out_valid && {out_data,out_bytes}!=={top_out_data,top_out_bytes})$fatal(1,"partition data equivalence");end\n'
        bench=(s/'tb/integration/tb_mhbs_stateful.sv').read_text().replace('endmodule',extra+'endmodule')
        (d/'tb.sv').write_text(bench)
        common=(OUT/label/'P4U1_stats1/mhbs_common.sv');assert common.exists()
        binary=work/'obj/Vtb_mhbs_stateful'
        if not binary.exists():
            files=[s/x for x in (s/'manifests/v42_sources.txt').read_text().split()]
            tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module','tb_mhbs_stateful','-GPIPELINE=4','-GUNROLL=1','--Mdir',work/'obj',*files,common,d/'tb.sv'],d/'compile.log',s)
        tool([binary,f'+VECTOR={v}','+STALL=1','+REPLAYS=2','+INTERRUPT=1'],d/'run.log',s)
        assert 'STATEFUL_PASS' in (d/'run.log').read_text()
        rows.append(dict(profile=n,passed=True,bench_sha256=sha(d/'tb.sv'),log_sha256=sha(d/'run.log')))
        print('PARTITION_PASS',n,flush=True)
    write(OUT/label/'partition.json',rows)

def legacy_checks(label):
    s=source(label);d=OUT/label/'legacy_units';d.mkdir(parents=True,exist_ok=True);rows=[]
    reference=(source('baseline')/'rtl/hash_lane/mhbs_chain_pipeline_lane.sv').read_text().replace('module mhbs_chain_pipeline_lane #','module mhbs_chain_pipeline_lane_ref #')
    (d/'chain_ref.sv').write_text(reference)
    vectors=[]
    for n,shape,m in [(16,4,87),(32,3,72),(24,4,65),(32,4,39),(24,4,64),(32,3,73),(24,4,63),(32,4,41),(32,3,71),(32,4,40)]:
        payload=(bytes(range(32,32+n))+bytes(range(96,96+n)) if shape==3 else bytes(range(96,96+n))+bytes(range(64,64+n))+bytes(range(128,128+n)))+bytes(range(m))
        vectors.append((n<<442)|(shape<<438)|(m<<431)|((len(payload)//136+1)<<423)|int.from_bytes(hashlib.shake_256(payload).digest(49),'little'))
    (d/'padding.mem').write_text(''.join(f'{x:0112x}\n' for x in vectors))
    for top,p,u in [('tb_mhbs_chain_format_equiv',4,1)]+[('tb_mhbs_recipe_padding',p,u) for p,u in ((1,1),(1,2),(4,1),(12,2))]:
        name=f'{top}_P{p}U{u}';work=BUILD/label/name;work.mkdir(parents=True,exist_ok=True)
        files=[s/n for n in (s/'manifests/v42_sources.txt').read_text().split() if n.startswith('rtl/hash_lane/')]
        bench=d/(top+'.sv');bench.write_text((ROOT/f'tb/unit/{top}.sv').read_text())
        files+=[d/'chain_ref.sv',s/'tb/reference/mhbs_shake_pre_direct_ref.sv',s/'tb/reference/mhbs_recipe_pre_direct_ref.sv',bench]
        binary=work/('obj/V'+top)
        identity=sha(bench)
        if not binary.exists() or not (work/'bench.sha256').exists() or (work/'bench.sha256').read_text()!=identity:
            parameters=[f'-GPIPELINE={p}']+([f'-GUNROLL={u}'] if 'padding' in top else [])
            tool(['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','--top-module',top,*parameters,'--Mdir',work/'obj',*files],d/(name+'_compile.log'),s)
            (work/'bench.sha256').write_text(identity)
        tool([binary,f'+VECTORS={d}/padding.mem'],d/(name+'.log'),s)
        assert '_PASS' in (d/(name+'.log')).read_text();rows.append(dict(test=name,passed=True,log_sha256=sha(d/(name+'.log'))))
        print('LEGACY_UNIT_PASS',name,flush=True)
    write(OUT/label/'legacy_units.json',rows)

def report(label,partial=False):
    baseline=json.loads((OUT/'baseline/matrix.json').read_text());new=json.loads((OUT/label/'matrix.json').read_text())
    if partial:
        areas=[dict(p=p,u=u,**json.loads(f.read_text())['area']) for p,u in POINTS
               if (f:=OUT/label/f'P{p}U{u}/synthesis.json').exists()]
    else:areas=json.loads((OUT/label/'area.json').read_text())
    area_map={(x['p'],x['u']):x for x in areas}
    missing=[f'P{p}U{u}' for p,u in POINTS if (p,u) not in area_map]
    empty_area={k:None for k in ('lut','ff','lutram','bram36','dsp','equivalent_slice')}
    old_dir=ROOT/'manifests/experiments/stateful_keygen_pu13_20261012_v1'
    frozen=json.loads((OUT/'baseline/inputs.json').read_text())['source_sha256']
    old_config=json.loads((old_dir/'config.json').read_text())
    assert old_config['clock_period_ns']==6.666667 and old_config['device']=='xc7a200tffg1156-3'
    assert old_config['profile_enable_synthesis']==0
    for n,h in frozen.items():
        if n.startswith('rtl/'):assert old_config['source_sha256'][n]==h,('baseline synthesis identity',n)
    old_area={pu:json.loads((old_dir/f'P{pu[0]}U{pu[1]}/synthesis.json').read_text())['area'] for pu in POINTS}
    key=lambda r:(r['p'],r['u'],r['profile'],r['operation'])
    reference={key(r):r for r in baseline};assert len(reference)==len(new)==72
    rows=[]
    for r in new:
        b=reference[key(r)];pu=r['p'],r['u'];a=area_map.get(pu,empty_area);oa=old_area[pu]
        assert (r['hashes'],r['permutations'])==(b['hashes'],b['permutations'])
        assert r['compute_cycles']==b['compute_cycles'] if r['p']==1 else r['compute_cycles']<b['compute_cycles']
        if r['p']>1:assert r['max_live']>=2 and r['batch_requests']==r['batch_returns']
        mhz=150 if r['u']==1 else 110
        cycles=r['compute_cycles'];old_cycles=b['compute_cycles'];ms=cycles/(mhz*1000)
        row={k:r[k] for k in ('profile','p','u','operation','compute_cycles','total_cycles','hashes','permutations')}
        row.update(baseline_cycles=old_cycles,baseline_total_cycles=b['total_cycles'],speedup=old_cycles/cycles,
            max_live=r['max_live'],lut=a['lut'],ff=a['ff'],lutram=a['lutram'],bram36=a['bram36'],dsp=a['dsp'],
            equivalent_slice=a['equivalent_slice'],baseline_lut=oa['lut'],baseline_ff=oa['ff'],baseline_lutram=oa['lutram'],
            baseline_equivalent_slice=oa['equivalent_slice'],assumed_mhz=mhz,time_ms=ms,atp=a['equivalent_slice']*ms if a['equivalent_slice'] is not None else None,
            baseline_atp=oa['equivalent_slice']*old_cycles/(mhz*1000),
            utilization=r['permutations']*24/(r['p']*r['u']*cycles),baseline_utilization=b['permutations']*24/(r['p']*r['u']*old_cycles))
        rows.append(row)
    checks={name:json.loads((OUT/label/(name+'.json')).read_text()) for name in ('units','edges','slh_regression','partition','legacy_units')}
    out=ROOT/'docs/report/Stateful_Pipeline_20261012'
    write(out.with_suffix('.json'),dict(baseline_commit='01486e3f',candidate=label,routed=False,pending_synthesis=missing,rows=rows,validation={k:len(v) if isinstance(v,list) else v for k,v in checks.items()}))
    with out.with_suffix('.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    md=['# XMSS/LMS 接入 P 个链上下文','',
        '基线生产 RTL：`01486e3f`；P1 保留原路径，P>1 在同一 Keccak 流水内交错执行链。四参数 × 三操作 × 六配置共 72 组，新旧输出与 Hash/置换次数一致；P1 周期一致，P4/P12 全部减少周期。',
        '',f"综合已完成 {len(areas)}/6 组。"+('按用户要求先报告；'+', '.join(missing)+' 继续后台综合，当前面积与 ATP 留空，不参与比较。其周期和利用率已经实测。' if missing else '全部面积和 ATP 已更新。'),
        '', '器件 `xc7a200tffg1156-3`，共同核、6.666667 ns、统计关闭，最多 6 个 Vivado × 4 线程。**没有布局布线：U1 的 150 MHz、U2 的 110 MHz 均为假定值。** Sign 包含完整认证路径重算，不能与缓存命中的签名周期直接比较。',
        '', '等效 Slice = LUT/4 + FF/8 + 232.4×BRAM36 + 102.4×DSP；LUT 包含 LUTRAM。时间(ms)=计算周期/(MHz×1000)；ATP=等效 Slice×时间。有效轮利用率=置换数×24/(P×U×计算周期)，不是逐拍资源忙碌率。',
        '', '## 综合面积','', '| 配置 | 原 LUT | 新 LUT | 原 FF | 新 FF | 新 LUTRAM | 原等效 Slice | 新等效 Slice | 变化 |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for pu in POINTS:
        b=old_area[pu]
        if pu not in area_map:
            md.append(f"| P{pu[0]}U{pu[1]} | {b['lut']:,.0f} | 待定 | {b['ff']:,.0f} | 待定 | 待定 | {b['equivalent_slice']:,.3f} | 待定 | — |")
            continue
        a=area_map[pu]
        md.append(f"| P{pu[0]}U{pu[1]} | {b['lut']:,.0f} | {a['lut']:,.0f} | {b['ff']:,.0f} | {a['ff']:,.0f} | {a['lutram']:,.0f} | {b['equivalent_slice']:,.3f} | {a['equivalent_slice']:,.3f} | {(a['equivalent_slice']/b['equivalent_slice']-1)*100:+.2f}% |")
    md+=['', '面积基线复用 `stateful_keygen_pu13_20261012_v1`，已逐文件验证全部生产 RTL 的 SHA-256 与本轮冻结基线相同。新增面积包括每上下文 XMSS 临时 key、算法/子步骤信息及新块选择路径；未添加 Keccak 轮实例或扩大端点存储。', '', '## 周期、利用率与 ATP','']
    for n in PROFILES:
        md+=['### '+n,'','| 操作 | 配置 | 原周期 | 新周期 | 加速 | 在途峰值 | 原利用率 | 新利用率 | 时间 ms | 原 ATP | 新 ATP |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for r in sorted((r for r in rows if r['profile']==n),key=lambda r:(r['operation'],r['p'],r['u'])):
            atp=f"{r['atp']:,.3f}" if r['atp'] is not None else '待定'
            md.append(f"| {('Keygen','Sign','Verify')[r['operation']]} | P{r['p']}U{r['u']} | {r['baseline_cycles']:,} | {r['compute_cycles']:,} | {r['speedup']:.3f}× | {r['max_live']} | {100*r['baseline_utilization']:.2f}% | {100*r['utilization']:.2f}% | {r['time_ms']:.3f} | {r['baseline_atp']:,.3f} | {atp} |")
    md+=['','## 验证与边界','',
        f"- 11 个 P>1 配置 × 72 个链单元向量通过；P1U1/P1U2 由完整操作矩阵覆盖。全部流水级逐轮对照冻结轮函数。",
        f"- {len(checks['edges'])} 项补充检查：q=1/1023、非法 q、消息边界、五类 Verify 篡改、节点停顿、截断后复位、重放、批量在途异常清空和统计关闭。q=0 由正常矩阵覆盖。",
        f"- {len(checks['slh_regression'])} 项 SLH 新旧对照，包括六参数三操作及六配置 128f Sign，周期与计数一致。",
        f"- {len(checks['partition'])} 项完整 top/提取共同核逐周期对照，含停顿和复位重放。",
        f"- {len(checks['legacy_units'])} 项旧链适配器等价及普通 sponge 135/136/137 字节填充边界检查。",
        f'- 已完成的 {len(areas)} 组综合均检查统计寄存器被裁剪；无频率测量。',
        '- 请求逐个进入流水，反馈优先；整批完成后按链索引消费。消息、L-tree、列表压缩及父节点仍串行，不保证随 P 线性加速。',
        '', '## 证据','',f'冻结源码、补丁、配置与日志：[`{label}`](../../manifests/experiments/stateful_pipeline_20261012/{label})。',
        '', '分层报告：']
    for p,u in POINTS:
        if (p,u) in area_map:md.append(f'- [P{p}U{u}](../../manifests/experiments/stateful_pipeline_20261012/{label}/P{p}U{u}/core_hierarchical.rpt)')
        else:md.append(f'- P{p}U{u} 待定：[后台综合日志](../../manifests/experiments/stateful_pipeline_20261012/{label}/P{p}U{u}/vivado.log)')
    md+=['','完整工作量、总周期及资源字段见同名 CSV/JSON；历史报告未改写。本轮不提交、不推送。','']
    out.with_suffix('.md').write_text('\n'.join(md));write(OUT/label/'acceptance.json',dict(functional_passed=True,measurement_complete=not missing,pending_synthesis=missing,normal_cases=72,report_sha256=sha(out.with_suffix('.json'))))
    print('REPORT_PASS',out.with_suffix('.md'),flush=True)

def finish(label):
    required=[OUT/'baseline/matrix.json']+[OUT/label/(n+'.json') for n in ('matrix','area','edges','slh_regression','units','partition','legacy_units')]
    while True:
        missing=[str(p.relative_to(OUT)) for p in required if not p.exists()]
        write(OUT/'status.json',dict(state='waiting' if missing else 'reporting',pending=missing,updated_at=time.time(),candidate=label))
        if not missing:break
        time.sleep(30)
    # Refresh metadata added by the workflow after the original simulations started.
    matrix(label);report(label)
    frozen=json.loads((OUT/label/'inputs.json').read_text())['source_sha256']
    for name,h in frozen.items():
        if name.startswith('rtl/'):assert sha(ROOT/name)==h,('workspace RTL changed',name)
    freeze('delivery')
    write(OUT/'status.json',dict(state='complete',candidate=label,normal_cases=72,baseline_cases=72,synthesis_points=6,
        report='docs/report/Stateful_Pipeline_20261012.md',routed=False,updated_at=time.time(),workflow_sha256=sha(__file__)))
def main():
    a=argparse.ArgumentParser();a.add_argument('action',choices=['freeze','run','matrix','unit','units','synth','regression','edges','partition','report','report-partial','legacy','finish']);a.add_argument('label');a.add_argument('--p',type=int,default=4);a.add_argument('--u',type=int,default=1);a.add_argument('--name',default='lms_omega4');a.add_argument('--op',type=int,default=2);a.add_argument('--stats',type=int,default=1);args=a.parse_args()
    if args.action=='freeze':freeze(args.label)
    elif args.action=='matrix':matrix(args.label)
    elif args.action=='unit':unit(args.label,args.p,args.u)
    elif args.action=='synth':synthesis(args.label)
    elif args.action=='units':units(args.label)
    elif args.action=='regression':regression(args.label)
    elif args.action=='edges':edges(args.label)
    elif args.action=='partition':partition_checks(args.label)
    elif args.action=='report':report(args.label)
    elif args.action=='report-partial':report(args.label,partial=True)
    elif args.action=='legacy':legacy_checks(args.label)
    elif args.action=='finish':finish(args.label)
    else:run(args.label,args.p,args.u,args.name,args.op,args.stats)
if __name__=='__main__':main()
