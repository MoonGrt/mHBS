#!/usr/bin/env python3
"""Protocol, statistics and reset checks on frozen L/U sources (Verilator only)."""
import argparse,concurrent.futures,json
import run_lu_p1 as m

def point(label,l,u):
 normal=m.simulate(label,l,u,ops=(1,2),suffix='_normal')
 off=m.simulate(label,l,u,ops=(1,2),stats=0,suffix='_normal')
 swapped=m.simulate(label,l,u,ops=(1,2),swap=1,suffix='_normal')
 for a,b,c in zip(normal,off,swapped):
  for key in ('cycles','total','hashes','permutations'):assert a[key]==b[key]==c[key],(l,u,key)
 m.simulate(label,l,u,ops=(1,2),options=('+STALL=1','+REPLAYS=2','+INTERRUPT=1'),suffix='_stall_reset')
 m.simulate(label,l,u,options=('+FAULT=1',),suffix='_fault')
 for tamper in range(1,6):m.simulate(label,l,u,ops=(2,),options=(f'+TAMPER={tamper}',),suffix=f'_tamper{tamper}')
 print('PROTOCOL_PASS',label,l,u,flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('label');a=p.parse_args();errors=[]
 def work(x):
  try:point(a.label,*x)
  except Exception as e:errors.append(dict(point=x,error=str(e)));print('PROTOCOL_FAIL',x,e,flush=True)
 with concurrent.futures.ThreadPoolExecutor(6) as pool:list(pool.map(work,m.POINTS))
 m.write(m.OUT/a.label/'protocol_status.json',dict(passed=not errors,errors=errors))
 if errors:raise SystemExit(1)
