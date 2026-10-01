#!/usr/bin/env python3
"""Frozen, resumable seven-candidate LUT experiment; no model or Git writes.

prepare creates isolated source trees. start returns immediately. stop terminates
all processes of the current stage. start again resumes completed stage receipts.
"""
import argparse
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import traceback

BASE = Path('manifests/experiments/unified_hbs_v4.2/external_job_message')
BASELINE = 'parent_right_20260930_v1'
ASSETS = Path('experiments/v4.2/lut21k')
VARIANTS = [('bank', 1), ('tail', 2), ('shake', 4), ('bank_tail', 3),
            ('bank_shake', 5), ('tail_shake', 6), ('all', 7)]
FIELDS = ('boot_cycles', 'keygen_cycles', 'sign_cycles', 'hashes', 'permutations',
          'total_cycles', 'output_sha256')
PYTHON = sys.executable


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w') as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def replace_once(text, old, new):
    assert text.count(old) == 1, old[:100]
    return text.replace(old, new)


def shake_variant(text):
    start = text.index('        if(REUSE_FAST_FEEDBACK) begin: common_fast_data')
    end = text.index('        always_ff @(posedge clk)', start)
    return text[:start] + '''        // Decode mutually exclusive sources once before the wide data path.
        wire use_fast=take_fast || (REUSE_FAST_FEEDBACK && take_feedback);
        wire use_feedback=!REUSE_FAST_FEEDBACK && !take_fast && take_feedback;
        wire use_stream=!use_fast && !use_feedback && select_stream;
        wire use_round=!use_fast && !use_feedback && !select_stream && !clear_stream;
        assign next_word=({64{use_fast}} & fast_word)
            | ({64{use_feedback}} & next_chain_state[word_index*64 +:64])
            | ({64{use_stream}} & absorb_word)
            | ({64{use_round}} & advanced_state[word_index*64 +:64]);
''' + text[end:]


def source_guard(root):
    # Track every existing tracked file, plus our new implementation assets.
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    paths += ['scripts/optimize_lut21k.py']
    paths += [str(p.relative_to(root)) for p in (root / ASSETS).rglob('*') if p.is_file()]
    return {p: sha(root/p) if (root/p).is_file() else None for p in sorted(set(paths)) if p}


def prepare(root, run):
    assert not run.exists(), 'Use a new run tag or resume the existing run'
    baseline = read(root / BASE / 'candidates' / BASELINE / 'result.json')
    assert baseline['core']['lut'] == 21071
    for p, h in baseline['rtl_sha256'].items(): assert sha(root/p) == h, p
    assert read(root/BASE/'current_core.json')['candidate'] == BASELINE
    run.mkdir(parents=True)
    sys.path.insert(0, str(root/'scripts'))
    import v42_external_flow as flow
    folder = flow.capture(run.name + '_baseline')
    shutil.copy2(folder/'source_snapshot.tar.gz', run/'baseline_source.tar.gz')
    shutil.copy2(folder/'inputs.json', run/'baseline_inputs.json')
    shutil.copy2(Path(__file__), run/'runner.py')
    refs = run/'reference'; refs.mkdir()
    for name in ('result.json', 'simulation.json', 'extended.json', 'verify/results.json'):
        dest = refs/name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/BASE/'candidates'/BASELINE/name, dest)
    cfg = dict(version=1, root=str(root), run=str(run), baseline=BASELINE,
               baseline_core=baseline['core'], created=time.time(), head=subprocess.check_output(
                   ['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
               source_guard=source_guard(root), pointer_sha256=sha(root/BASE/'current_core.json'),
               settings=dict(part='xc7a200tffg1156-3',vivado='2025.2',threads=8,period_ns=10,
                             profile_enable=False,target_lut=21000,max_candidates=7), candidates=[])
    state = dict(status='prepared', pid=None, current=None, child=None, completed=0, candidates={})
    original_store = (root/'rtl/memory/mhbs_value_store.sv').read_text()
    original_shake = (root/'rtl/hash_lane/mhbs_compact_shake_context_lane.sv').read_text()
    for label, mask in VARIANTS:
        tag = run.name + '_' + label
        work = root/'build/v4.2/lut21k_workspaces'/tag
        work.mkdir(parents=True, exist_ok=False)
        with tarfile.open(run/'baseline_source.tar.gz') as t: t.extractall(work, filter='data')
        # Only the baseline simulation is needed by pruning; it includes all six profiles.
        dest = work/BASE/'candidates'/BASELINE; dest.mkdir(parents=True)
        shutil.copy2(refs/'simulation.json', dest/'simulation.json')
        frozen = work/ASSETS/'reference'; frozen.mkdir()
        (frozen/'store.sv').write_text(original_store.replace('module mhbs_value_store ', 'module mhbs_value_store_ref '))
        (frozen/'shake.sv').write_text(original_shake.replace('module mhbs_compact_shake_context_lane #', 'module mhbs_compact_shake_context_lane_ref #'))
        if mask & 3:
            shutil.copy2(root/ASSETS/'mhbs_value_store_candidate.sv', work/'rtl/memory/mhbs_value_store.sv')
            p = work/'rtl/top/mhbs_hbs.sv'
            p.write_text(replace_once(p.read_text(), '.DEPTH(68),.ADDRESS_BITS(INDEX_BITS),.SINGLE_READ(1)',
                         f'.DEPTH(68),.ADDRESS_BITS(INDEX_BITS),.SINGLE_READ(1),.FIXED_BANK_WRITES({int(bool(mask&1))}),.SPLIT_TAIL({int(bool(mask&2))})'))
        if mask & 4:
            (work/'rtl/hash_lane/mhbs_compact_shake_context_lane.sv').write_text(shake_variant(original_shake))
        files = read(run/'baseline_inputs.json')['source_sha256']
        code = {p: sha(work/p) for p in files if not p.startswith('manifests/')}
        code.update({str(p.relative_to(work)):sha(p) for p in frozen.glob('*.sv')})
        entry = dict(label=label,mask=mask,tag=tag,workspace=str(work),code_sha256=code)
        cfg['candidates'].append(entry)
        out = run/'candidates'/tag; out.mkdir(parents=True)
        patch = ''
        for p in baseline['rtl_sha256']:
            patch += ''.join(difflib.unified_diff((root/p).read_text().splitlines(True),
                      (work/p).read_text().splitlines(True), fromfile='a/'+p, tofile='b/'+p))
        (out/'incremental.patch').write_text(patch)
        atomic(out/'candidate.json', entry)
        with tarfile.open(out/'prepared_source.tar.gz', 'w:gz') as t:
            for p in sorted(set(files) | set(code)): t.add(work/p, arcname=p)
            t.add(work/BASE/'candidates'/BASELINE/'simulation.json', arcname=str(BASE/'candidates'/BASELINE/'simulation.json'))
        entry['prepared_source_sha256'] = sha(out/'prepared_source.tar.gz')
        state['candidates'][tag] = dict(status='pending',stages={},core=None)
    cfg['runner_sha256'] = sha(run/'runner.py')
    atomic(run/'config.json', cfg); atomic(run/'state.json', state)
    report(run, cfg, state)
    print(run)


def resources(path):
    text = path.read_text(); result = {}
    for label,key in [('Slice LUTs','lut'),('Slice Registers','ff'),('LUT as Memory','lutram'),('Block RAM Tile','bram36'),('DSPs','dsp')]:
        hit = re.search(r'\|\s*'+re.escape(label)+r'\*?\s*\|\s*([\d,.]+)',text)
        assert hit,label; result[key]=float(hit[1].replace(',',''))
    result['equivalent_slice']=result['lut']/4+result['ff']/8
    return result


def report(run, cfg, state):
    lines = ['# 共同核 21k LUT 自动优化', '',
        '基线：21,071 LUT / 8,324 FF / 1,112 LUTRAM / 6308.250 等效 Slice。',
        '口径：K2U2，六参数 KG/SG/Verify，Vivado 2025.2，10 ns 共同核综合；未测新布线频率。', '',
        f"状态：**{state['status']}**；当前：{state.get('current') or '-'}；完成候选：{state.get('completed',0)}/7。", '',
        '| 候选 | LUT | FF | LUTRAM | 等效 Slice | 结果 |', '|---|---:|---:|---:|---:|---|']
    for c in cfg['candidates']:
        r=state['candidates'][c['tag']]; a=r.get('core') or {}
        lines.append('| '+' | '.join(str(x) for x in [c['label'],a.get('lut','-'),a.get('ff','-'),a.get('lutram','-'),a.get('equivalent_slice','-'),r['status']])+ ' |')
    lines += ['', '## 验收与证据', '', '总 LUT 包含 LUTRAM；通过门槛为 LUT ≤21,000、等效 Slice <6308.250、BRAM/DSP 为零及完整回归通过。',
              '冻结源码、补丁、阶段日志、原始综合报告和证据哈希保存在本目录 candidates/ 下；未完成数据用 `-`。',
              '未达标时仅保留完整回归通过且面积优于基线的最佳项，不将失败候选应用到生产。', '',
              '状态详情见 [state.json](state.json)，配置见 [config.json](config.json)。']
    if state.get('winner'): lines += ['',f"最终候选：{state['winner']}；应用状态：{state.get('promotion','-')}。"]
    tmp=run/'STATUS.md.tmp';tmp.write_text('\n'.join(lines)+'\n');os.replace(tmp,run/'STATUS.md')


def process_stamp(pid):
    try: return Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1].split()[19]
    except FileNotFoundError: return None


class Stopped(Exception): pass


class Driver:
    def __init__(self, run):
        self.run=run; self.cfg=read(run/'config.json');self.state=read(run/'state.json')
        self.stop=False
        for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,self.signal_stop)

    def signal_stop(self,*unused): self.stop=True

    def save(self):
        self.state['updated']=time.time();atomic(self.run/'state.json',self.state);report(self.run,self.cfg,self.state)

    def code_check(self,c):
        w=Path(c['workspace'])
        for p,h in c['code_sha256'].items(): assert sha(w/p)==h,('frozen code changed',p)

    def stage(self,c,name,cmd):
        r=self.state['candidates'][c['tag']]
        if r['stages'].get(name,{}).get('status')=='passed':return
        if self.stop:raise Stopped()
        self.code_check(c)
        w=Path(c['workspace']); out=self.run/'candidates'/c['tag'];logs=out/'driver_logs';logs.mkdir(parents=True,exist_ok=True)
        stage=r['stages'].setdefault(name,dict(elapsed_seconds=0,attempts=0))
        stage.update(status='running',command=cmd,attempts=stage.get('attempts',0)+1)
        print(time.strftime('%Y-%m-%d %H:%M:%S'),c['tag'],name,'START',flush=True)
        self.state['current']=c['tag']+'/'+name;r['status']=name;self.save()
        with (logs/f'{name}_{stage["attempts"]:02d}.log').open('w') as log:
            start=time.monotonic();last=start
            proc=subprocess.Popen(cmd,cwd=w,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            self.state['child']=dict(pid=proc.pid,stamp=process_stamp(proc.pid));self.save()
            try:
                while proc.poll() is None:
                    if self.stop:raise Stopped()
                    time.sleep(1)
                    now=time.monotonic()
                    if now-last>=30:
                        stage['elapsed_seconds']+=now-last;last=now;self.save()
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                    # Descendants may outlive the direct child.
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                stage['elapsed_seconds']+=time.monotonic()-last
                stage['returncode']=proc.returncode;self.state['child']=None
                stage['log_sha256']=sha(logs/f'{name}_{stage["attempts"]:02d}.log')
                stage['status']='interrupted' if self.stop else ('passed' if proc.returncode==0 else 'failed')
                self.save()
        if self.stop:raise Stopped()
        print(time.strftime('%Y-%m-%d %H:%M:%S'),c['tag'],name,'END',proc.returncode,flush=True)
        if proc.returncode:raise RuntimeError(f'{name}: exit {proc.returncode}; see {logs}')

    def compare(self,c,full=False):
        f=Path(c['workspace'])/'build/v4.2/external_job_message'/c['tag']
        for filename in (['simulation.json','extended.json'] if full else ['simulation.json']):
            actual=read(f/filename)['cases'];expected=read(self.run/'reference'/filename)['cases']
            assert actual.keys()==expected.keys(),filename
            for name,row in actual.items():
                for field in FIELDS:assert row[field]==expected[name][field],(filename,name,field,row[field],expected[name][field])
        actual=read(f/'verify/results.json')['profiles'];expected=read(self.run/'reference/verify/results.json')['profiles']
        assert actual.keys()==expected.keys()
        for name, cases in actual.items():
            if full:assert cases.keys()==expected[name].keys()
            for label,row in cases.items():
                for key,val in expected[name][label].items():
                    if key!='log_sha256':assert row[key]==val,('verify',name,label,key)
        atomic(self.run/'candidates'/c['tag']/('full_comparison.json' if full else 'pre_comparison.json'),dict(passed=True,baseline=BASELINE))

    def custom_checks(self,c):
        w=Path(c['workspace']);d=w/'build/lut21k_equivalence';d.mkdir(parents=True,exist_ok=True)
        store='rtl/memory/mhbs_value_store.sv' if c['mask']&3 else str(ASSETS/'mhbs_value_store_candidate.sv')
        for kind, sources in [('store',[store,str(ASSETS/'reference/store.sv'),str(ASSETS/'tb_store_equivalence.sv')]),
                              ('shake',['rtl/hash_lane/mhbs_keccak.sv','rtl/hash_lane/mhbs_compact_shake_context_lane.sv',str(ASSETS/'reference/shake.sv'),str(ASSETS/'tb_shake_equivalence.sv')])]:
            top=f'tb_{kind}_equivalence';obj=d/kind
            self.stage(c,kind+'_compile',['verilator','--binary','--timing','--assert','-O2','-j','8','-Wno-fatal','-Wno-WIDTH','--top-module',top,'--Mdir',str(obj),*sources])
            self.stage(c,kind+'_equivalence',[str(obj/('V'+top))])

    def preliminary(self,c):
        self.stage(c,'contracts',['make','contract-test','lint'])
        self.custom_checks(c)
        # Reuse sealed software reference data only after verifying its source/vector hashes.
        self.stage(c,'software_gate',[PYTHON,'-c',
            "from scripts.v42_external_flow import BASE,ROOT,sha; import json; g=json.loads((BASE/'software_gate.json').read_text()); assert g['passed']; "
            "[(None if sha(ROOT/p)==h else (_ for _ in ()).throw(AssertionError(p))) for p,h in g['source_sha256'].items()]; "
            "[(None if sha(BASE/'vectors'/n/p)==h else (_ for _ in ()).throw(AssertionError((n,p)))) for n,r in g['profiles'].items() for p,h in r['files'].items()]; print('SOFTWARE_REFERENCE_HASHES_PASS')"])
        self.stage(c,'units',[PYTHON,'scripts/verify_v42_external_units.py'])
        self.stage(c,'normal',[PYTHON,'scripts/v42_external_flow.py','sim','--tag',c['tag']])
        self.stage(c,'verify_quick',[PYTHON,'scripts/verify_v42_verify.py',c['tag'],'--quick'])
        self.compare(c)

    def full(self,c):
        tag=c['tag']
        self.stage(c,'extended',[PYTHON,'scripts/verify_v42_external_rtl.py',tag])
        self.stage(c,'partition',[PYTHON,'scripts/v42_external_flow.py','sim','--tag',tag,'--partition'])
        self.stage(c,'pruning',[PYTHON,'scripts/verify_v42_pruning.py',tag,'--baseline',BASELINE])
        self.stage(c,'verify_full',[PYTHON,'scripts/verify_v42_verify.py',tag])
        self.compare(c,full=True)
        self.stage(c,'audit',[PYTHON,'scripts/verify_v42_current.py',tag])
        if self.state['candidates'][tag]['stages'].get('collect',{}).get('status')!='passed':
            partial=Path(c['workspace'])/BASE/'candidates'/tag
            if partial.exists():shutil.rmtree(partial)
        self.stage(c,'collect',[PYTHON,'scripts/collect_v42_external.py',tag,'--sim-tag',tag,'--core-only'])
        self.state['candidates'][tag]['full_regression_pass']=True;self.save()

    def archive(self,c):
        w=Path(c['workspace']);out=self.run/'candidates'/c['tag'];f=w/'build/v4.2/external_job_message'/c['tag']
        accepted=w/BASE/'candidates'/c['tag']
        def copy(src,dst):
            if not src.exists():return
            for p in src.rglob('*'):
                rel=p.relative_to(src)
                if not p.is_file() or any(x in ('synth_source','binaries','__pycache__') or x.startswith('obj') for x in rel.parts):continue
                if p.suffix not in ('.json','.log','.rpt','.mem','.sv','.svh','.tcl','.gz','.dcp','.edf','.v'):continue
                target=dst/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        copy(accepted if accepted.exists() else f,out)
        copy(w/BASE/'unit',out/'unit')
        copy(w/BASE/'images',out/'images');copy(w/BASE/'vectors',out/'vectors')
        for name in ('software_gate.json','rtl_start.json'):
            if (w/BASE/name).exists():shutil.copy2(w/BASE/name,out/name)
        atomic(out/'outcome.json',self.state['candidates'][c['tag']])
        atomic(out/'evidence_sha256.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='evidence_sha256.json'})

    def promote(self,c):
        root=Path(self.cfg['root']);w=Path(c['workspace']);tag=c['tag']
        archive=self.run/'candidates'/tag
        conflicts=[]
        if subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()!=self.cfg['head']:conflicts.append('HEAD')
        for p,h in self.cfg['source_guard'].items():
            if (sha(root/p) if (root/p).is_file() else None)!=h:conflicts.append(p)
        if sha(root/BASE/'current_core.json')!=self.cfg['pointer_sha256']:conflicts.append('current_core.json')
        if conflicts:
            self.state.update(promotion='blocked_by_concurrent_changes',conflicts=conflicts);self.save();return
        receipt=read(archive/'result.json');assert receipt['functional_pass'] and receipt['core_synthesis_pass']
        assert self.state['candidates'][tag]['full_regression_pass']
        # Archive before installing; current_core.json is the final commit marker.
        dest=root/BASE/'candidates'/tag
        shutil.copytree(archive,dest,dirs_exist_ok=True)
        for p,h in receipt['rtl_sha256'].items():assert sha(w/p)==h
        for p,h in receipt['rtl_sha256'].items():
            if sha(root/p)!=h:
                tmp=(root/p).with_suffix('.sv.lut21k_tmp');shutil.copy2(w/p,tmp);os.replace(tmp,root/p)
        # Carry test witnesses and source-bound unit evidence with the RTL.
        for p in (w/ASSETS/'reference').glob('*.sv'):
            target=root/ASSETS/'reference'/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
        shutil.copytree(w/BASE/'unit',root/BASE/'unit',dirs_exist_ok=True)
        atomic(root/BASE/'current_core.json',dict(candidate=tag,functional_pass=True,core_synthesis_pass=True,
               post_synth_acceptance=False,post_route_pass=False,result_sha256=sha(dest/'result.json')))
        self.state['promotion']='applied';self.save()
        report_path=root/'docs/v4.2/LUT21k.md'
        report_path.write_text((self.run/'STATUS.md').read_text().replace('(state.json)',f'(../../{self.run.relative_to(root)}/state.json)').replace('(config.json)',f'(../../{self.run.relative_to(root)}/config.json)')+
            f'\n正式证据：[分层面积](../../{BASE}/candidates/{tag}/synthesis/core_hierarchical.rpt)。\n')

    def execute(self):
        stale=self.state.get('child')
        if stale and process_stamp(stale['pid'])==stale['stamp']:
            raise RuntimeError('Previous stage still alive; use stop before resume')
        self.state.update(status='running',pid=os.getpid(),pid_stamp=process_stamp(os.getpid()),child=None);self.save()
        try:
            winner=next((c for c in self.cfg['candidates'] if self.state['candidates'][c['tag']].get('full_regression_pass')),None)
            for c in self.cfg['candidates']:
                if winner:break
                r=self.state['candidates'][c['tag']]
                if r.get('finished'):continue
                try:
                    self.preliminary(c)
                    w=Path(c['workspace']);f=w/'build/v4.2/external_job_message'/c['tag']
                    if r['stages'].get('synthesis',{}).get('status')!='passed':
                        for sub in ('synth_source','synthesis'):
                            if (f/sub).exists():shutil.rmtree(f/sub)
                    self.stage(c,'synthesis',[PYTHON,'scripts/v42_external_synth.py',c['tag'],'--core-only'])
                    r['core']=resources(f/'synthesis/core_utilization.rpt')
                    a=r['core'];r['area_improved']=a['lut']<21071 and a['equivalent_slice']<6308.25 and a['bram36']==a['dsp']==0
                    r['target_met']=r['area_improved'] and a['lut']<=21000
                    r['status']='below_target_pending_regression' if r['target_met'] else 'area_improved' if r['area_improved'] else 'area_rejected'
                    self.save()
                    if r['target_met']:
                        self.full(c);winner=c;r['status']='accepted_target'
                except Stopped:raise
                except Exception as e:
                    r['status']='failed';r['failure']=str(e);r['traceback']=traceback.format_exc()
                    print(r['traceback'],flush=True)
                r['finished']=True;self.state['completed']=sum(bool(x.get('finished')) for x in self.state['candidates'].values())
                self.archive(c);self.save()
                if winner:break
            if winner is None:
                # A resumed accepted item does not need to rerun any simulations.
                winner=next((c for c in self.cfg['candidates'] if self.state['candidates'][c['tag']].get('full_regression_pass')),None)
            if winner is None:
                candidates=sorted((c for c in self.cfg['candidates'] if self.state['candidates'][c['tag']].get('area_improved') and self.state['candidates'][c['tag']]['status']!='failed'),
                                  key=lambda c:(self.state['candidates'][c['tag']]['core']['lut'],self.state['candidates'][c['tag']]['core']['equivalent_slice']))
                for c in candidates:
                    try:
                        self.full(c);winner=c;self.state['candidates'][c['tag']]['status']='accepted_improvement';self.archive(c);break
                    except Stopped:raise
                    except Exception as e:
                        self.state['candidates'][c['tag']].update(status='failed',failure=str(e));self.archive(c);self.save()
            if winner:
                self.state['winner']=winner['tag'];self.promote(winner)
                self.state['status']='complete_target_met' if self.state['candidates'][winner['tag']]['target_met'] else 'complete_best_below_goal'
            else:self.state['status']='complete_no_accepted_candidate'
            self.state.update(current=None,pid=None);self.save()
            root=Path(self.cfg['root'])
            doc=root/'docs/v4.2/LUT21k.md'
            if not doc.exists() or doc.read_text().startswith('# 共同核 21k LUT 自动优化'):
                doc.write_text((self.run/'STATUS.md').read_text().replace('(state.json)',f'(../../{self.run.relative_to(root)}/state.json)').replace('(config.json)',f'(../../{self.run.relative_to(root)}/config.json)'))
            atomic(self.run/'FINISHED.json',dict(status=self.state['status'],winner=self.state.get('winner'),promotion=self.state.get('promotion'),contains_failures=any(r['status']=='failed' for r in self.state['candidates'].values()),finished=time.time()))
        except Stopped:
            self.state.update(status='stopped',pid=None);self.save()
        except Exception:
            self.state.update(status='driver_error',failure=traceback.format_exc(),pid=None);self.save();raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','start','run','stop','status']);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--run',required=True,type=Path);a=p.parse_args()
    run=a.run.resolve();root=a.root.resolve()
    if a.action=='prepare':prepare(root,run);return
    if a.action=='status':print((run/'STATUS.md').read_text());return
    if a.action=='stop':
        s=read(run/'state.json');pid=s.get('pid')
        if pid and process_stamp(pid)==s.get('pid_stamp'):os.kill(pid,signal.SIGTERM);print('Stop requested',pid)
        else:
            child=s.get('child')
            if child and process_stamp(child['pid'])==child['stamp']:
                os.killpg(child['pid'],signal.SIGTERM);time.sleep(2)
                try:os.killpg(child['pid'],signal.SIGKILL)
                except ProcessLookupError:pass
            s.update(status='stopped',pid=None,child=None);atomic(run/'state.json',s);report(run,read(run/'config.json'),s)
        return
    if a.action=='start':
        if (run/'FINISHED.json').exists():print('Already finished:',run/'FINISHED.json');return
        with (run/'launch.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            s=read(run/'state.json');pid=s.get('pid')
            if pid and process_stamp(pid)==s.get('pid_stamp'):print('Already running:',pid);return
            with (run/'driver.log').open('a') as log:
                proc=subprocess.Popen([PYTHON,str(run/'runner.py'),'run','--run',str(run)],stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
            # A launch receipt lets a second start detect the driver immediately.
            for _ in range(50):
                s=read(run/'state.json')
                if s.get('pid')==proc.pid or proc.poll() is not None:break
                time.sleep(.1)
            print(json.dumps(dict(pid=proc.pid,state=str(run/'state.json'),status=str(run/'STATUS.md'),log=str(run/'driver.log')),ensure_ascii=False))
        return
    with (run/'driver.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Driver already running')
        cfg=read(run/'config.json');assert sha(Path(__file__))==cfg['runner_sha256'],'Frozen runner modified'
        Driver(run).execute()


if __name__=='__main__':main()
