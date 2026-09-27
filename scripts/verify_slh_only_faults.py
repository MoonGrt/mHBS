#!/usr/bin/env python3
"""Check that SLH execution errors stop output before and during Sign."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

from autonomous_flow import ACTIVE,BUILD,ROOT,logic,logic_id

rtl=logic()
identity=logic_id(rtl)
binary=BUILD/f'sim_u2_l2_s0_{identity}'/'Vtb_mhbs_autonomous'
if not binary.is_file():
    subprocess.run(['python3','scripts/autonomous_flow.py','sim','--profile','slh_128f',
                    '--lanes','2','--unroll','2'],cwd=ROOT,check=True)
output=ACTIVE/'faults'/identity
output.mkdir(parents=True,exist_ok=True)
image=ACTIVE/'images/slh_128f'
records={}
for fault in (1,3):
    command=[str(binary),'+IMAGE='+str(image.relative_to(ROOT)),f'+FAULT={fault}']
    run=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT,text=True,check=True)
    log=output/f'fault_{fault}.log'
    log.write_text(run.stdout)
    match=re.search(r'AUTONOMOUS_FAULT_PASS fault=(\d+) q=0 sign_prefix=(\d+)',run.stdout)
    if not match or int(match[1])!=fault or (fault==1 and int(match[2])!=0) or (fault==3 and int(match[2])<40):
        raise RuntimeError('Incorrect failure stop for fault '+str(fault))
    records[str(fault)]={'sign_prefix':int(match[2]),
                         'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    print('SLH_FAULT_PASS',fault,'sign_prefix',match[2],flush=True)
(output/'results.json').write_text(json.dumps({'passed':True,'logic_sha256':rtl,
    'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
    'profiles':['slh_128f'],'faults':records},indent=2)+'\n')
