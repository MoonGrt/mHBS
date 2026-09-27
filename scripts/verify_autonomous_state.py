#!/usr/bin/env python3
"""Fixed-index execution fault checks without adding public control ports."""
from pathlib import Path
import argparse,concurrent.futures,json,subprocess,sys
from autonomous_flow import ROOT,BASE,BUILD,logic,logic_id,sha,write,run
parser=argparse.ArgumentParser();parser.add_argument('--lanes',type=int,default=2);parser.add_argument('--unroll',type=int,default=2);args=parser.parse_args()
compiled_logic=logic()
tag=f'u{args.unroll}_l{args.lanes}_s0';folder=BUILD/('sim_'+tag+'_'+logic_id(compiled_logic))
identity=json.loads((folder/'compile.json').read_text());assert identity['logic']==compiled_logic
assert identity['bench']==sha(ROOT/'tb/integration/tb_mhbs_autonomous.sv')
image_names=['xmss_omega2','xmss_omega4','lms_omega2','lms_omega4']
out=BASE/'state_verification'/logic_id(compiled_logic)/tag;out.mkdir(parents=True,exist_ok=True)
def one(case):
    name,mode=case;log=out/(name+'_'+mode+'.log')
    opt='+FAULT='+mode[-1]
    run([str(folder/'Vtb_mhbs_autonomous'),f'+IMAGE=manifests/experiments/unified_hbs_v4.1/images/{name}',opt],log)
    text=log.read_text();assert 'AUTONOMOUS_FAULT_PASS' in text
    return log.name,sha(log)
with concurrent.futures.ThreadPoolExecutor(4) as pool:records=dict(pool.map(one,[(name,mode) for name in image_names for mode in ('fault1','fault2','fault3')]))
write(out/'results.json',dict(pass_all=True,index_policy="fixed_q_no_guard",logic_sha256=compiled_logic,bench_sha256=identity['bench'],binary_sha256=sha(folder/'Vtb_mhbs_autonomous'),logs=records))
print('STATEFUL_FAULT_MATRIX_PASS',len(records))
