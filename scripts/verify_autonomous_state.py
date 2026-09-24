#!/usr/bin/env python3
"""Fault, delayed-commit and replay checks without adding public control ports."""
from pathlib import Path
import argparse,concurrent.futures,json,subprocess,sys
from autonomous_flow import ROOT,BASE,BUILD,logic,logic_id,sha,write,run
parser=argparse.ArgumentParser();parser.add_argument('--lanes',type=int,default=2);parser.add_argument('--unroll',type=int,default=4);args=parser.parse_args()
tag=f'u{args.unroll}_l{args.lanes}_s0';folder=BUILD/('sim_'+tag)
identity=json.loads((folder/'compile.json').read_text());assert identity['logic']==logic()
assert identity['bench']==sha(ROOT/'tb/integration/tb_uhbs_autonomous.sv')
image_names=['xmss_omega2','xmss_omega4','lms_omega2','lms_omega4']
out=BASE/'state_verification'/logic_id(logic())/tag;out.mkdir(parents=True,exist_ok=True)
def one(case):
    name,mode=case;log=out/(name+'_'+mode+'.log')
    opt='+COMMIT_DELAY=37' if mode=='delay' else '+FAULT='+mode[-1]
    run([str(folder/'Vtb_uhbs_autonomous'),f'+IMAGE=manifests/experiments/unified_hbs_v4.1/images/{name}',opt],log)
    text=log.read_text();assert ('AUTONOMOUS_PASS' if mode=='delay' else 'AUTONOMOUS_FAULT_PASS') in text
    return log.name,sha(log)
with concurrent.futures.ThreadPoolExecutor(4) as pool:records=dict(pool.map(one,[(name,mode) for name in image_names for mode in ('delay','fault1','fault2','fault3')]))
write(out/'results.json',dict(pass_all=True,logic_sha256=logic(),bench_sha256=identity['bench'],binary_sha256=sha(folder/'Vtb_uhbs_autonomous'),logs=records))
print('STATEFUL_FAULT_MATRIX_PASS',len(records))
