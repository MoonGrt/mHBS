#!/usr/bin/env python3
"""Isolated synthesis queue. Report interval is 60 seconds; no routing."""
import datetime, hashlib, json, os, re, shutil, subprocess, tarfile, time
from pathlib import Path

RUN=Path(__file__).resolve().parent
ROOT=RUN.parents[2]
ARCHIVE=ROOT/'docs/manifests/experiments/c_sha_area_optimization_20261023_132949'
STAGES=('baseline','shift','compressor','recipe','control','combined')
FILES=('hierarchical.rpt','timing.rpt','critical_paths.rpt','utilization.rpt','settings.txt','debug_audit.json','vivado.log','diagnostic_clock.xdc')
active={}; state={}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
    if not p.exists() or p.read_text()!=text:
        tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(text);tmp.replace(p)
def batch_vivado_count():
    return sum(1 for row in subprocess.check_output(['ps','-eo','comm=,args='],text=True).splitlines()
               if row.split(None,1)[0]=='vivado' and '/unwrapped/lnx64.o/vivado ' in row)
def reports():
    rows=[]
    for stage in STAGES:
        if stage not in state:continue
        row=dict(stage=stage,**state[stage]); out=RUN/'stages'/stage/'synth/sha2'
        util=(out/'utilization.rpt').read_text() if (out/'utilization.rpt').exists() else ''
        for key,label in [('lut',r'Slice LUTs\*?'),('ff','Slice Registers'),('bram','Block RAM Tile'),('dsp','DSPs')]:
            m=re.search(r'^\|\s*'+label+r'\s*\|\s*([\d,.]+)',util,re.M)
            row[key]=float(m[1].replace(',','')) if m and row['status']=='passed' else None
        row['slice']=row['lut']/4+row['ff']/8 if row.get('lut') is not None else None
        timing=(out/'timing.rpt').read_text() if (out/'timing.rpt').exists() else ''
        m=re.search(r'Setup\s*:.*?Worst Slack\s+([-\d.]+)ns',timing)
        row['synthesis_wns_ns']=float(m[1]) if m and row['status']=='passed' else None
        row['area_change_pct']=(row['slice']/5098.375-1)*100 if row['slice'] else None
        row['cycles']=None;row['measured_atp']=None;rows.append(row)
    data={'updated_at':datetime.datetime.now().astimezone().isoformat(),'only_synthesis':True,'frequency_signoff':False,
          'design':'c','backend':'sha2','configuration':'K1U1','part':'xc7a200tffg1156-3','period_ns':10,'threads':2,
          'statistics':'SYNTHESIS','baseline_slice':5098.375,'rows':rows,'validation':'not_simulated_per_user',
          'source_branch_unchanged':'main','selection':None}
    if (RUN/'SELECTION.json').exists():data['selection']=json.loads((RUN/'SELECTION.json').read_text())
    save(RUN/'STATE.json',data);save(ARCHIVE/'reports/C_SHA_Area_Optimization_20261023.json',data)
    lines=['# c SHA2 面积优化','',f"更新时间：{data['updated_at']}",'',
        '隔离工作树中的 c／K1U1／SHA2 common；Vivado 2025.2、xc7a200tffg1156-3、OOC、2线程、10ns默认时序驱动综合。',
        '等效Slice=LUT/4+FF/8，不含ROM和签名缓存。本轮仅综合，周期未重测，WNS仅作诊断，不作为频率或ATP验收。','',
        '| 候选 | 状态 | LUT | FF | BRAM | 等效Slice | 相对上一轮 | 综合WNS/ns |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    def f(x,d=3):return '—' if x is None else f'{x:,.{d}f}'
    for r in rows:lines.append(f"| {r['stage']} | {r['status']} | {f(r['lut'],0)} | {f(r['ff'],0)} | {f(r['bram'],0)} | {f(r['slice'])} | {f(r['area_change_pct'])}% | {f(r['synthesis_wns_ns'])} |")
    if data['selection']:lines+=['',f"选择结果：{json.dumps(data['selection'],ensure_ascii=False)}"]
    path=ARCHIVE/'reports/C_SHA_Area_Optimization_20261023.md';path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(lines)+'\n')
while True:
    for stage,process in list(active.items()):
        rc=process.poll()
        if rc is None:
            if time.time()-state[stage]['started_epoch']>600:state[stage]['analysis_deferred']=True
            continue
        out=RUN/'stages'/stage/'synth/sha2';log=(out/'vivado.log').read_text(errors='replace')
        state[stage].update(status='passed' if rc==0 and 'MHBS_TIMING_DIAGNOSTIC_PASS' in log else 'failed',returncode=rc,
                            elapsed_s=round(time.time()-state[stage]['started_epoch'],3))
        for name in FILES:
            if (out/name).exists():
                dst=ARCHIVE/'stages'/stage/'synth/sha2'/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(out/name,dst)
        del active[stage]
    for stage in STAGES:
        folder=RUN/'stages'/stage
        if stage in state or not (folder/'READY').exists():continue
        if len(active)>=3 or batch_vivado_count()>=11:break
        src=folder/'source';out=folder/'synth/sha2';out.mkdir(parents=True,exist_ok=True)
        manifest={str(p.relative_to(src)):sha(p) for p in sorted(src.rglob('*')) if p.is_file()}
        save(folder/'SOURCE.json',manifest);save(ARCHIVE/'stages'/stage/'SOURCE.json',manifest)
        archive_file=ARCHIVE/'stages'/stage/'frozen_source.tar.gz'
        with tarfile.open(archive_file,'w:gz') as tar:tar.add(src,arcname='source')
        env=dict(os.environ,MHBS_DESIGN='c',HASH_BACKEND='sha2')
        log=(out/'vivado.log').open('w')
        proc=subprocess.Popen(['/opt/Xilinx/2025.2/Vivado/bin/vivado','-mode','batch','-nolog','-nojournal','-notrace',
            '-source',str(src/'scripts/diagnose_timing.tcl'),'-tclargs',str(src),'1','1',str(out),'10'],cwd=src,env=env,stdout=log,stderr=subprocess.STDOUT)
        log.close();active[stage]=proc;state[stage]={'status':'running','pid':proc.pid,'started_epoch':time.time(),'analysis_deferred':False}
    reports()
    if (RUN/'DONE_INPUT').exists() and not active and all(s in state for s in STAGES if (RUN/'stages'/s/'READY').exists()):break
    time.sleep(60)
