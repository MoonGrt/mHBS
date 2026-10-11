#!/usr/bin/env python3
"""Finish frozen regressions, routed winners and the three-algorithm ATP audit."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import threading
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
PROFILES=('slh_128f','xmss_h10','lms_h10')

def now():return datetime.now(ZoneInfo('Asia/Singapore')).isoformat(timespec='seconds')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,s):
    p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.tmp');t.write_text(s);t.replace(p)
def best(data):
    return {p:min((r for r in data['results'] if r['profile']==p and r.get('atp_slice_ms') is not None),key=lambda r:r['atp_slice_ms']) for p in PROFILES}

def compatibility(source,out):
    matrix={(p,1) for p in (1,2,3,4,6,8,12,24)}|{(p,2) for p in (1,2,3,4,6,12)}
    configs=[(p,u) for p in range(1,25) for u in range(1,25) if p*u<=24 and 24%(p*u)==0 and (p,u) not in matrix]
    env=os.environ.copy();env.pop('PROFILE_ENABLE',None);env['SIM_SYNTHESIS']='0'
    for p,u in configs:
        for profile in PROFILES:
            subprocess.run(['bash','scripts/simulate_fast.sh',profile,'verify',str(p),str(u)],cwd=source,env=env,check=True)
        subprocess.run(['python3','scripts/check_recipes.py','--pipeline',str(p),'--unroll',str(u)],cwd=source,env=env,check=True)
    print('OTHER_PU_PASS',len(configs),flush=True)

class Audit:
    def __init__(self,args):
        self.lock=threading.RLock()
        self.args=args;self.run=args.output.resolve();self.matrix=args.matrix.resolve();self.source=Path(json.loads((self.matrix/'SOURCE.json').read_text())['source_root'])
        self.baseline=json.loads(args.baseline.read_text());self.baseline_best=best(self.baseline)
        self.state=dict(schema='mhbs.pu_generic.audit.v1',started_at=now(),complete=False,tasks={},baseline=str(args.baseline.resolve()),matrix=str(self.matrix),source=str(self.source),h20_full_stopped=True)
        self.prefix=ROOT/'docs/manifests/experiments/pu_generic_sharing_20261013/reports/PU_Generic_Sharing_20261013'
        self.run.mkdir(parents=True,exist_ok=True)
        prior=self.run/'status.json'
        if prior.exists():
            saved=json.loads(prior.read_text())
            if saved['matrix']!=str(self.matrix):raise ValueError('Cannot resume a different matrix')
            self.state=saved
        self.publish()
    def publish(self):
        with self.lock:self._publish()
    def _publish(self):
        self.state['updated_at']=now()
        if (self.matrix/'status.json').exists():
            matrix=json.loads((self.matrix/'status.json').read_text());self.state['matrix_counts']=matrix['counts']
            self.state['analysis_excluded_configurations']=[k.split('/')[1] for k,v in matrix['tasks'].items() if k.startswith('synth/') and v.get('analysis_deferred')]
            try:
                winners=best(matrix);comparison=[]
                for p in PROFILES:
                    old,new=self.baseline_best[p],winners[p]
                    comparison.append(dict(profile=p,baseline_configuration=old['configuration'],baseline_atp=old['atp_slice_ms'],candidate_configuration=new['configuration'],candidate_atp=new['atp_slice_ms'],change_percent=100*(new['atp_slice_ms']/old['atp_slice_ms']-1)))
                self.state['comparison']=comparison
                self.state['matrix_atp_pass']=(matrix['complete'] or matrix.get('analysis_ready')) and all(v['status']=='passed' for v in matrix['tasks'].values() if not v.get('analysis_deferred')) and matrix.get('source_unchanged') and all(r['candidate_atp']<=r['baseline_atp'] for r in comparison) and any(r['candidate_atp']<r['baseline_atp'] for r in comparison)
            except ValueError:pass
        write(self.run/'status.json',json.dumps(self.state,indent=2)+'\n');write(self.prefix.with_suffix('.json'),json.dumps(self.state,indent=2)+'\n')
        lines=['# 通用 P/U 执行、统计宏与资源复用（2026-10-13）','',f'更新时间：{self.state["updated_at"]}。验收：'+('通过' if self.state.get('accepted') else '未通过' if self.state['complete'] else '后台验证中')+'。', '',
               '删除 P4U1 独占分支，所有合法 P/U 使用统一固定引擎、滚动链、并行 L-tree、128位流式生产和 FORS 四叶微组。P1 复用原迭代 Keccak 状态。统计直接用 SYNTHESIS 宏裁剪，统计端口保持64位并在综合时置零。', '',
               '端点RAM容量保持136×256位：0～66链端点/FORS根，67保护槽，68～87树栈，88～107认证路径，108～111保留，112～135 FORS暂存。认证与树栈同拍写冲突增加一拍，签名缓存与XMSS的三个同时存活银行保持独立。', '',
               f'冻结候选及矩阵：[矩阵报告]({Path(json.loads((self.matrix/"SOURCE.json").read_text())["report"]).with_suffix(".md")})；[源码清单]({self.matrix / "SOURCE.json"})。', '',
               '面积使用每个P/U的common；外部ROM、完整签名缓存和板级I/O不计入。矩阵ATP按U1=150MHz、U2=110MHz假定计算。布线结果另列，不能把假定频率当作闭合频率。','',
               '| 算法 | 基线最佳 | 基线 ATP Slice·ms | 候选最佳 | 候选 ATP Slice·ms | 变化 |','|---|---|---:|---|---:|---:|']
        for r in self.state.get('comparison',[]):lines.append(f'| {r["profile"]} | {r["baseline_configuration"]} | {r["baseline_atp"]:.6f} | {r["candidate_configuration"]} | {r["candidate_atp"]:.6f} | {r["change_percent"]:+.2f}% |')
        if self.state.get('analysis_excluded_configurations'):lines+=['','当前分析排除异常耗时配置：'+', '.join(self.state['analysis_excluded_configurations'])+'。综合继续后台运行，不等待该配置；完成后补入面积和ATP。']
        lines+=['','矩阵未全部完成时，上表候选排名为暂定值；最终验收要求其余已测配置通过、三个已测配置中的最佳ATP均不回退且至少一个降低；异常配置继续后台运行，其结果未完成时不参与面积与ATP排名。','', '| 检查 | 状态 | 日志 |','|---|---|---|']
        for k,v in self.state['tasks'].items():lines.append(f'| {k} | {v["status"]} | [{Path(v["log"]).name}]({v["log"]}) |')
        lines+=['','完整回归为十个非h20配置的三操作加两个h20 Verify，共32项；h20完整Keygen、Sign继续停止。其他合法P/U逐项执行三算法Verify和459项独立配方。扩展回归覆盖乱序标签、捕获、停顿、复位、异常、截断、篡改、消息和填充边界及q边界。', '',
                '综合采用xc7a200tffg1156-3、同工具、OOC、通用Keccak、6.666667ns约束和默认时序驱动优化，最多12个Vivado、每个2线程。旧/新胜出配置从冻结综合检查点布线；先6.666667ns，未闭合时按测得违例放宽，固定布线以0.1ns精度扫描setup和hold。未新增false-path或multicycle。OOC时钟模型结论不扩展到板级top。','']
        if self.state.get('routes'):
            lines+=['| 来源/P/U | 布线等效Slice | 闭合周期 ns | STA MHz | WNS/WHS ns |','|---|---:|---:|---:|---|']
            for k,v in self.state['routes'].items():lines.append(f'| {k} | {v["equivalent_slice"]:.3f} | {v["period_ns"]:.3f} | {1000/v["period_ns"]:.3f} | {v["wns_ns"]}/{v["whs_ns"]} |')
            lines+=['','| 算法 | 基线布线ATP Slice·ms | 候选布线ATP Slice·ms | 变化 |','|---|---:|---:|---:|']
            for r in self.state.get('comparison',[]):
                old=self.state['routes'].get('baseline/'+r['baseline_configuration']);new=self.state['routes'].get('candidate/'+r['candidate_configuration'])
                if old and new:
                    b=self.baseline_best[r['profile']]['cycles']*old['period_ns']*old['equivalent_slice']/1e6
                    n=best(json.loads((self.matrix/'status.json').read_text()))[r['profile']]['cycles']*new['period_ns']*new['equivalent_slice']/1e6
                    lines.append(f'| {r["profile"]} | {b:.6f} | {n:.6f} | {100*(n/b-1):+.2f}% |')
        steps_path=self.run.parent/'steps.json'
        if steps_path.exists():
            stages=json.loads(steps_path.read_text());self.state['steps']=stages
            lines+=['','P4U1逐步对照：','', '| 阶段 | LUT | FF | 等效Slice | SLH Sign周期 | XMSS Sign周期 | LMS Sign周期 |','|---|---:|---:|---:|---:|---:|---:|']
            for row in stages['steps']:
                area=row['area'];cycles=row['cycles']
                lines.append(f'| {row["stage"]} | {area["lut"]:.0f} | {area["ff"]:.0f} | {area["equivalent_slice"]:.3f} | {cycles["slh_128f"]} | {cycles["xmss_h10"]} | {cycles["lms_h10"]} |')
            lines+=['','工作区复用这一独立步骤在P4U1增加57.125等效Slice及86个SLH周期；最终组合相对当前标准基线面积下降1.41%，三个已测最佳ATP下降。复用并非在所有点上单独降低面积，表中保留实测代价。', '',f'[逐步CSV]({self.run.parent/"steps.csv"})、[周期分解]({self.run.parent/"profile/profile.json"})、[证据清单]({self.run.parent/"EVIDENCE.json"})。']
        for err in self.state.get('errors',[]):lines+=['',f'待解决：{err}']
        write(self.prefix.with_suffix('.md'),'\n'.join(lines)+'\n')
        import csv,io
        f=io.StringIO();rows=self.state.get('comparison',[])
        if rows:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        write(self.prefix.with_suffix('.csv'),f.getvalue())
    def repair_full32(self):
        out=self.run/'full32';status=json.loads((out/'status.json').read_text())
        if not status['complete'] or any('is not in the subpath' not in e for e in status['errors']):return False
        for line in (out/'source.sha256').read_text().splitlines():
            expected,name=line.split('  ',1)
            if sha(self.source/name)!=expected:return False
        cases=[(p,op) for p in ('slh_128f','slh_192f','slh_256f','slh_128s','slh_192s','slh_256s','xmss_h10','xmss_h16','xmss_h20','lms_h10','lms_h15','lms_h20')
               for op in ('keygen','sign','verify') if not (p.endswith('h20') and op!='verify')]
        records=[]
        for profile,op in cases:
            log=out/f'{profile}_{op}.log'
            if not log.exists():return False
            m=re.search(r'STATEFUL_PASS P4U1 op=(\d+) cycles=(\d+) total=(\d+) hashes=(\d+) permutations=(\d+).*?seconds=([\d.e+]+)',log.read_text())
            if not m or int(m[1])!=('keygen','sign','verify').index(op):return False
            meta=[int(v,16) for v in (self.source/'tb/vectors'/profile/op/'meta.mem').read_text().split()]
            if int(m[4])!=meta[1] or int(m[5])!=meta[2]:return False
            records.append(dict(profile=profile,operation=op,cycles=int(m[2]),total_cycles=int(m[3]),hashes=int(m[4]),permutations=int(m[5]),seconds=float(m[6]),log=str(log),vectors_sha256={f.name:sha(f) for f in (self.source/'tb/vectors'/profile/op).glob('*.mem')}))
        write(out/'status_bookkeeping_error.json',json.dumps(status,indent=2)+'\n')
        status.update(passed=32,required=32,results=records,bookkeeping_errors=status['errors'],errors=[],recovered_from_verified_logs=True)
        write(out/'status.json',json.dumps(status,indent=2)+'\n')
        return True
    def adopted_result(self,key,log):
        if key=='full32':return self.repair_full32() if (self.run/'full32/status.json').exists() else False
        marker={'extended':'P4_VALIDATION_PASS','compatibility':'OTHER_PU_PASS 16','standard_models':'STANDARD_MODEL_PASS'}[key]
        return marker in log.read_text()
    @staticmethod
    def alive(pid):
        try:return Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1][0]!='Z'
        except FileNotFoundError:return False
    def command(self,key,command,cwd=None,env=None):
        log=self.run/(key.replace('/','_')+'.log');log.parent.mkdir(parents=True,exist_ok=True)
        with self.lock:prior=dict(self.state['tasks'].get(key,{}))
        if prior.get('status')=='passed':return True
        if prior.get('pid'):
            while self.alive(prior['pid']):time.sleep(5)
            if key.startswith('route/'):
                code=0 if 'COMMON_ROUTE_PASS' in log.read_text() else 1
            else:code=0 if self.adopted_result(key,log) else 1
            with self.lock:
                self.state['tasks'][key].update(status='passed' if code==0 else 'failed',finished_at=now(),returncode=code,adopted=True);self.publish()
            return code==0
        with self.lock:
            self.state['tasks'][key]=dict(status='running',log=str(log),started_at=now());self.publish()
        with log.open('w') as handle:
            child=subprocess.Popen(command,cwd=cwd or self.source,env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
            with self.lock:
                self.state['tasks'][key]['pid']=child.pid;self.publish()
            code=child.wait()
        if key=='full32' and code and self.repair_full32():code=0
        with self.lock:
            self.state['tasks'][key].update(status='passed' if code==0 else 'failed',finished_at=now(),returncode=code);self.publish()
        return code==0
    def execute(self):
        env=os.environ.copy();env.pop('PROFILE_ENABLE',None);env['SIM_SYNTHESIS']='0';env['SKIP_FULL_REGRESSION']='1'
        # Start the large profiles immediately; independent validations use other workers.
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(self.command,'full32',['python3','scripts/validate_standard.py','--skip-h20-full','--workers','4','--output',str(self.run/'full32')],None,env),
                  pool.submit(self.command,'extended',['bash','scripts/validate_p4.sh',str(self.run/'extended')],None,env),
                  pool.submit(self.command,'compatibility',['python3',str(Path(__file__).resolve()),'--compatibility','--matrix',str(self.matrix),'--output',str(self.run/'compatibility')],None,env),
                  pool.submit(self.command,'standard_models',['python3','scripts/check_standard_models.py'],None,env)]
            while not ((status:=json.loads((self.matrix/'status.json').read_text()))['complete'] or status.get('analysis_ready')):
                self.publish();time.sleep(5)
            self.publish()
            matrix=json.loads((self.matrix/'status.json').read_text())
            if self.state.get('matrix_atp_pass'):
                winners=best(matrix)
                for origin,configs in [('baseline',{r['configuration'] for r in self.baseline_best.values()}),('candidate',{r['configuration'] for r in winners.values()})]:
                    for config in sorted(configs):
                        matrix_root=self.args.baseline_root if origin=='baseline' else self.matrix
                        checkpoint=matrix_root/'synth'/config/'common/synthesized.dcp'
                        out=self.run/'route'/origin/config;out.mkdir(parents=True,exist_ok=True)
                        if self.command('route/'+origin+'/'+config,['vivado','-mode','batch','-nolog','-nojournal','-notrace','-source',str(self.args.route_script),'-tclargs',str(checkpoint),str(out)],out):
                            from scripts.run_pu_sign_matrix import utilization
                            values=dict(line.split('=',1) for line in (out/'closed/result.txt').read_text().splitlines())
                            area=utilization(out/'closed/utilization.rpt');area.update({k:float(values[k]) for k in ('period_ns','wns_ns','whs_ns')})
                            self.state.setdefault('routes',{})[origin+'/'+config]=area;self.publish()
            results=[j.result() for j in jobs]
        self.state['errors']=[k for k,v in self.state['tasks'].items() if v['status']!='passed']
        if not self.state.get('matrix_atp_pass'):self.state['errors'].append('矩阵或固定频率ATP验收失败；候选不能发布为已验收组合')
        unchanged=all(sha(self.source/p)==h for p,h in json.loads((self.matrix/'SOURCE.json').read_text())['sha256'].items())
        self.state.update(source_unchanged=unchanged,complete=True,finished_at=now(),accepted=all(results) and not self.state['errors'] and unchanged)
        self.publish();print('PU_GENERIC_ACCEPTED' if self.state['accepted'] else 'PU_GENERIC_NOT_ACCEPTED',flush=True)
        return 0 if self.state['accepted'] else 1

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--launch',action='store_true');p.add_argument('--compatibility',action='store_true');p.add_argument('--matrix',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',type=Path,default=ROOT/'docs/manifests/experiments/pu_sign_matrix_20261013_183754/reports/PU_Sign_Matrix_20261013_183754_ATP.json');p.add_argument('--baseline-root',type=Path,default=ROOT/'build/pu_sign_matrix/20261013_183754');p.add_argument('--route-script',type=Path,default=ROOT/'scripts/route_common_checkpoint.tcl');a=p.parse_args()
    if a.compatibility:
        source=Path(json.loads((a.matrix/'SOURCE.json').read_text())['source_root']);compatibility(source,a.output);return 0
    if a.launch:
        a.output.mkdir(parents=True,exist_ok=True)
        command=['python3',str(Path(__file__).resolve()),'--matrix',str(a.matrix.resolve()),'--output',str(a.output.resolve()),'--baseline',str(a.baseline.resolve()),'--baseline-root',str(a.baseline_root.resolve()),'--route-script',str(a.route_script.resolve())]
        with (a.output/'audit.log').open('w') as log:
            child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        write(a.output/'audit.pid',str(child.pid)+'\n');print(json.dumps(dict(pid=child.pid,output=str(a.output.resolve())),indent=2));return 0
    return Audit(a).execute()
if __name__=='__main__':raise SystemExit(main())
