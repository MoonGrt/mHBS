#!/usr/bin/env python3
"""Collect a detached synthesis without stopping it or blocking other analysis."""
import argparse,json,time,hashlib
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.run_pu_sign_matrix import Runner,utilization
p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('configuration');a=p.parse_args();run=a.run.resolve();key=f'synth/{a.configuration}/common'
s=json.loads((run/'status.json').read_text());task=s['tasks'][key];pid=task['pid'];log=Path(task['log']);output=log.parent
while True:
    text=log.read_text(errors='replace') if log.exists() else ''
    try:alive=Path(f'/proc/{pid}/stat').read_text().split(') ',1)[1][0]!='Z'
    except FileNotFoundError:alive=False
    if f'MHBS_MATRIX_SYNTH_PASS {a.configuration} profile=common' in text or not alive:break
    time.sleep(5)
s=json.loads((run/'status.json').read_text());task=s['tasks'][key]
if f'MHBS_MATRIX_SYNTH_PASS {a.configuration} profile=common' in text and (output/'synthesized.dcp').exists():
    task.update(status='passed',analysis_deferred=False,area=utilization(output/'utilization.rpt'),verification='Completed marker, reports and checkpoint')
else:task.update(status='failed',analysis_deferred=False,error='Detached synthesis ended without a completed marker; see original log')
now=datetime.now().astimezone();task.update(finished_at=now.isoformat(timespec='seconds'),seconds=(now-datetime.fromisoformat(task['started_at'])).total_seconds())
s['complete']=all(t['status'] not in ('running','pending') for t in s['tasks'].values())
meta=json.loads((run/'SOURCE.json').read_text());source=Path(meta['source_root']);s['source_unchanged']=all(hashlib.sha256((source/f).read_bytes()).hexdigest()==h for f,h in meta['sha256'].items())
tmp=run/'status.json.tmp';tmp.write_text(json.dumps(s,indent=2)+'\n');tmp.replace(run/'status.json');Runner.render_existing(run)
print('DEFERRED_SYNTHESIS_COLLECTED',a.configuration,task['status'],flush=True)
