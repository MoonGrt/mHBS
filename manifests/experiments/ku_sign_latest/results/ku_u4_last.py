from pathlib import Path
import json,os,signal,subprocess,sys,time
root=Path(__file__).resolve().parent.parent
state=root/'build/ku_u4_last_state.json'
pid=int((root/'build/ku_internal20_driver.pid').read_text())
def record(phase,**extra):
 state.write_text(json.dumps(dict(phase=phase,paused_driver_pid=pid,updated=time.time(),**extra),indent=2)+'\n')
 print(phase,flush=True)
record('routing_K2U2_K4U2')
rc=subprocess.call([sys.executable,'scripts/run_ku_routes.py','--jobs','6','--points','K2U2','K4U2'],cwd=root)
result=root/'build/v4.2/external_job_message/ku_internal20_route_subset_results.json'
if rc or not result.exists() or not json.loads(result.read_text()).get('passed'):
 record('non_U4_failed_U4_remains_paused',returncode=rc)
 sys.exit(1)
os.killpg(pid,signal.SIGCONT)
record('resumed_U4_after_non_U4_completed')
