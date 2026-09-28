#!/usr/bin/env python3
"""User-requested K2 fixed targets; separate durable run alongside the scan."""
import argparse,concurrent.futures,fcntl,json,os,signal,subprocess,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sign_timing_scan as scan
from v42_external_flow import capture,identity,sha,ROOT,BUILD
RUN=ROOT/'build/v4.2/sign_k2_fixed_100_50_25_v1'
TARGETS={'K2U1':10.0,'K2U3':20.0,'K2U4':40.0}
class Fixed(scan.Driver):
 def status_text(self):
  super().status_text()
  path=self.run/'STATUS.md'
  text=path.read_text().replace('# 128f Sign 后台扫描状态','# K2 三组固定约束后台状态').replace('/12；','/3；')
  pending=path.with_name('STATUS.md.fixed.pending');pending.write_text(text);os.replace(pending,path)
 def report(self):
  with self.lock:
   super().report()
   path=self.run/'report.md'
   text=path.read_text().replace('# 128f Sign：U1/U2/U3/U4 时序扫描','# K2 固定约束：100/50/25 MHz').replace('## 十二点汇总','## 三组固定约束汇总').replace('## K2U2 首轮扫描','## K2U2 对照说明').replace('目的：按相同搜索规则、不同 U 的约束范围比较最高通过频率、实际签名时间和 ATP。','目的：按用户指定约束并行验证 K2U1=100 MHz、K2U3=50 MHz、K2U4=25 MHz。本轮每点仅验证一档，不搜索最高频率。K2U2 扫描位于独立运行目录。')
   pending=path.with_name('report.md.fixed.pending');pending.write_text(text);os.replace(pending,path)
 def point(self,label):
  point=self.state['points'][label]
  if point['status'] in ('completed','preparation_failed'):return
  try:
   source=self.prepare(label)
   with self.lock:
    if not point['attempts']:
     point['attempts'].append(dict(index=1,ticks=scan.ticks(TARGETS[label]),kind='fixed_user_target',status='pending',elapsed_seconds=0))
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
 reference=scan.load(scan.RUN/'state.json')
 assert reference['config']['rtl_sha256']==identity()
 assert all(reference['units'][str(u)]['passed'] for u in (1,2,3,4))
 for u in (1,2,3,4):assert sha(scan.RUN/'units'/f'U{u}'/'run.log')==reference['units'][str(u)]['run_sha256']
 config=json.loads(json.dumps(reference['config']))
 config.update(requested_periods_ns=TARGETS,mode='fixed_user_requested_periods')
 config['runtime_sha256'][str(Path(__file__).resolve().relative_to(ROOT))]=sha(Path(__file__))
 points={}
 for label,period in TARGETS.items():
  u=int(label[-1]);tag=f'signfixed_k2u{u}_{int(1000/period)}m_v1'
  folder=capture(tag,lanes=2,unroll=u);inputs=scan.load(folder/'inputs.json')
  assert inputs['source_sha256']==config['source_sha256']
  points[label]=dict(k=2,u=u,tag=tag,snapshot_sha256=inputs['snapshot_sha256'],status='pending',activity='',attempts=[],search=scan.new_search())
 scan.atomic(RUN/'config.json',config)
 scan.atomic(RUN/'state.json',dict(schema='mhbs.sign_timing_fixed.v1',status='ready',config=config,points=points,units=json.loads(json.dumps(reference['units'])),updated_at=datetime.now().astimezone().isoformat()))
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
