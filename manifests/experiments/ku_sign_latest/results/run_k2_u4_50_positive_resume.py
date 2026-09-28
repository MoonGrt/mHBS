#!/usr/bin/env python3
"""User-requested K2 fixed targets; separate durable run alongside the scan."""
import argparse,concurrent.futures,fcntl,json,os,signal,subprocess,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sign_scan_positive as scan
from v42_external_flow import capture,identity,sha,ROOT,BUILD
RUN=ROOT/'build/v4.2/sign_k2_u4_50_positive_resume_v1'
TARGETS={'K2U4':20.0}
class Fixed(scan.Driver):
 def status_text(self):
  super().status_text()
  path=self.run/'STATUS.md'
  text=path.read_text().replace('# 128f Sign 后台扫描状态','# K2U4 50 MHz 后台状态').replace('/12；','/1；')
  pending=path.with_name('STATUS.md.fixed.pending');pending.write_text(text);os.replace(pending,path)
 def report(self):
  with self.lock:
   super().report()
   path=self.run/'report.md'
   text=path.read_text().replace('# 128f Sign：U1/U2/U3/U4 时序扫描','# K2U4 50 MHz').replace('## 十二点汇总','## K2U4 指定频率汇总').replace('## K2U4 首轮扫描','## K2U4 50 MHz 档').replace('目的：按相同搜索规则、不同 U 的约束范围比较最高通过频率、实际签名时间和 ATP。','目的：按用户指定约束并行验证 K2U4=50 MHz。本轮每点仅验证一档，不搜索最高频率。K2U4 扫描位于独立运行目录。')
   pending=path.with_name('report.md.fixed.pending');pending.write_text(text);os.replace(pending,path)
 def point(self,label):
  point=self.state['points'][label]
  if point['status'] in ('completed','preparation_failed'):return
  try:
   source=self.prepare(label)
   with self.lock:
    if not point['attempts']:
     point['attempts'].append(dict(index=1,ticks=TARGETS[label]*10,kind='fixed_user_target',status='pending',elapsed_seconds=0))
     self.save()
   attempt=point['attempts'][0]
   if attempt['status'] not in scan.TERMINAL:
    result=self.attempt(label,source,attempt)
    with self.lock:attempt.update(result);self.save()
   with self.lock:
    point.update(status='completed',activity='固定约束结束')
    point['search'].update(phase='done',reason='one_user_requested_fixed_period')
    self.save()
   self.report()
  except scan.Interrupted:
   with self.lock:point.update(status='interrupted',activity='已停止，可恢复');self.save()
   raise
  except Exception as error:
   with self.lock:point.update(status='preparation_failed',failure=repr(error),activity='准备或调度失败');self.save()
   print('FIXED_POINT_ERROR',label,repr(error),flush=True)
 def execute(self):
  self.state.update(status='running',driver=dict(pid=os.getpid(),start_ticks=scan.pid_start(os.getpid())))
  self.save();self.report()
  try:
   assert self.state['config']['rtl_sha256']==identity()
   for path,digest in self.state['config']['runtime_sha256'].items():assert sha(ROOT/path)==digest,path
   for path,digest in self.state['config']['source_sha256'].items():assert sha(ROOT/path)==digest,path
   for point in self.state['points'].values():
    for record in [point.get('preparation',{}),*point['attempts']]:
     if scan.alive(record.get('process')):
      import time
      record['elapsed_seconds']=record.get('elapsed_seconds',0)+max(0,time.time()-record.get('heartbeat_epoch',time.time()))
      scan.terminate(record['process'])
     record.pop('process',None);record.pop('heartbeat_epoch',None)
   with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures=[pool.submit(self.point,label) for label in TARGETS]
    for future in futures:future.result()
   valid=all(p['status']=='completed' and p['attempts'][0]['status']=='passed' for p in self.state['points'].values())
   self.state.update(status='finished_all_attempts_passed' if valid else 'finished_with_failed_attempts',all_points_have_valid_results=valid)
   self.save();self.report()
   scan.atomic(self.run/'FINISHED.json',dict(status=self.state['status'],all_points_have_valid_results=valid,finished_at=self.state['updated_at'],report=str(self.run/'report.md')))
   print('FIXED_FINISHED',self.state['status'],flush=True)
  except scan.Interrupted:
   self.state['status']='stopped';self.save();self.report()
  except Exception as error:
   self.state.update(status='blocked',failure=repr(error));self.save();self.report()
   scan.atomic(self.run/'FINISHED.json',dict(status='blocked',failure=repr(error)))
   print('FIXED_BLOCKED',repr(error),flush=True)
  finally:
   self.state.pop('driver',None);self.save()
def initialize():
 if (RUN/'state.json').exists():return
 import shutil
 original_run=ROOT/'build/v4.2/sign_k2_u4_50_u2_110_u1_130_v1'
 reference=scan.load(original_run/'state.json')
 previous=reference['points']['K2U4']
 old_attempt=previous['attempts'][-1]
 old_folder=old_attempt.get('folder',str((original_run/'K2U4'/f"attempt_{old_attempt['index']:02d}_{old_attempt['ticks']}ticks").relative_to(ROOT)))
 assert reference['status']=='stopped' and not scan.alive(reference.get('driver'))
 assert not scan.alive(old_attempt.get('process'))
 assert reference['config']['rtl_sha256']==identity()
 assert abs(old_attempt['ticks']/10-20.0)<1e-9
 assert old_attempt['status'] not in scan.TERMINAL
 scan.atomic(RUN/'previous_state_K2U4.json',reference)
 config=json.loads(json.dumps(reference['config']))
 config.update(requested_periods_ns=TARGETS,requested_frequency_mhz={'K2U4':50},
  mode='fixed_user_frequency_resume_positive_setup',flow_sha256=sha(scan.FLOW),
  timing_acceptance=dict(setup_ns_greater_than=0,hold_ns_greater_or_equal=0,setup_guard_ns=0),
  continued_from_run=str(original_run),previous_state_sha256=sha(RUN/'previous_state_K2U4.json'),
  target_rule='unchanged 20 ns; resume same constraint and cumulative active time')
 config.pop('target_derivation',None)
 for path in [ROOT/'build/sign_scan_positive.py',scan.FLOW,Path(__file__).resolve()]:
  config['runtime_sha256'][str(path.relative_to(ROOT))]=sha(path)
 point=json.loads(json.dumps(previous))
 point.update(status='pending',activity='同约束断点恢复',search=scan.new_search())
 point.pop('failure',None)
 attempt=dict(index=1,ticks=200.0,kind='fixed_user_target_resume',status='pending',
  elapsed_seconds=old_attempt['elapsed_seconds'],previous_attempt_folder=old_folder)
 point['attempts']=[attempt]
 assert sha(BUILD/point['tag']/'synthesis'/scan.SHELL/'post_synth.dcp')==point['source_dcp_sha256']
 source=ROOT/old_folder
 stage=scan.checkpoint(source,20.0)
 target=RUN/'K2U4'/'attempt_01_200.0ticks'
 target.mkdir(parents=True,exist_ok=True)
 if stage in ('post_place','post_route'):
  shutil.copy2(source/(stage+'.dcp'),target/(stage+'.dcp'))
  shutil.copy2(source/'stage.json',target/'stage.json')
  assert scan.checkpoint(target,20.0)==stage
 config['checkpoint_resume_provenance']=dict(source_folder=str(source),resume_stage=stage,
  inherited_elapsed_seconds=old_attempt['elapsed_seconds'],
  checkpoint_sha256=sha(target/(stage+'.dcp')) if stage!='fresh' else None)
 scan.atomic(RUN/'config.json',config)
 scan.atomic(RUN/'state.json',dict(schema='mhbs.sign_timing_fixed.v1',status='ready',config=config,
  points={'K2U4':point},units=json.loads(json.dumps(reference['units'])),updated_at=datetime.now().astimezone().isoformat()))
def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=('start','resume','run','stop','status'));parser.add_argument('--lock-fd',type=int);args=parser.parse_args()
 if args.action in ('stop','status'):
  subprocess.run([sys.executable,str(ROOT/'scripts/sign_timing_scan.py'),args.action,'--run-dir',str(RUN)],check=True);return
 RUN.mkdir(parents=True,exist_ok=True)
 stream=os.fdopen(args.lock_fd,'a+') if args.lock_fd is not None else (RUN/'driver.lock').open('a+')
 with stream as guard:
  try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('ALREADY_RUNNING',RUN);return
  if args.action in ('start','resume'):
   initialize();state=scan.load(RUN/'state.json')
   if state['status'].startswith('finished_'):print('ALREADY_FINISHED',RUN/'report.md');return
   with (RUN/'driver.log').open('a') as log:
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'run','--lock-fd',str(guard.fileno())],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,pass_fds=(guard.fileno(),))
   scan.atomic(RUN/'launched.json',dict(pid=child.pid,start_ticks=scan.pid_start(child.pid)))
   print(json.dumps(dict(pid=child.pid,status=str(RUN/'STATUS.md'),log=str(RUN/'driver.log'),targets_ns=TARGETS),ensure_ascii=False));return
  driver=Fixed(RUN);signal.signal(signal.SIGTERM,lambda *_:driver.stop.set());signal.signal(signal.SIGINT,lambda *_:driver.stop.set())
  if (RUN/'FINISHED.json').exists():(RUN/'FINISHED.json').unlink()
  driver.execute()
if __name__=='__main__':main()
