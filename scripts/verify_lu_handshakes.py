#!/usr/bin/env python3
"""Test-only throttles on both sides of each lane handshake; no production ports."""
import sys,shutil,json,tarfile,concurrent.futures,difflib
import run_lu_p1 as m
base=sys.argv[1] if len(sys.argv)>1 else 'structure';label=base+'_handshake_test'
src=m.source(label);out=m.OUT/label
if not (out/'inputs.json').exists():
 shutil.copytree(m.source(base),src);p=src/'rtl/top/mhbs_hbs.sv';old=p.read_text();s=old
 anchor='        mhbs_recipe_lane #'
 insert='''        reg [5:0] test_phase;
        always @(posedge clk)if(execution_rst)test_phase<=0;else test_phase<=test_phase+1'b1;
        wire test_request_block=test_phase<6'(3+(L*7)%19);
        wire test_response_block=test_phase<6'(7+(L*11)%37);
        wire test_ready,test_valid;
        assign lane_ready[L]=test_ready && !test_request_block;
        assign lane_valid[L]=test_valid && !test_response_block;
'''
 s=s.replace(anchor,insert+anchor).replace('.request_valid(state==HASH_ISSUE && launch_pending[L])','.request_valid(state==HASH_ISSUE && launch_pending[L] && !test_request_block)').replace('.request_ready(lane_ready[L])','.request_ready(test_ready)').replace('.response_valid(lane_valid[L]),.response_ready(state==HASH_WAIT && response_pending[L])','.response_valid(test_valid),.response_ready(state==HASH_WAIT && response_pending[L] && !test_response_block)')
 p.write_text(s);out.mkdir(parents=True,exist_ok=True)
 (out/'test_only.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),s.splitlines(True),fromfile='production',tofile='test-throttled')))
 files=[p for p in src.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
 with tarfile.open(out/'source_snapshot.tar.gz','w:gz') as t:
  for p in files:t.add(p,arcname=str(p.relative_to(src)))
 m.write(out/'inputs.json',dict(test_only=True,base=base,source_sha256={str(p.relative_to(src)):m.sha(p) for p in files}))
errors=[]
def one(point):
 try:m.simulate(label,*point,ops=(1,2),options=('+STALL=1','+INTERRUPT=1'),suffix='_throttled')
 except Exception as e:errors.append(dict(point=point,error=str(e)));print('FAIL',point,e,flush=True)
with concurrent.futures.ThreadPoolExecutor(6) as pool:list(pool.map(one,m.POINTS))
m.write(out/'results.json',dict(passed=not errors,errors=errors,test_only=True));print('HANDSHAKE_TEST_PASS',not errors)
