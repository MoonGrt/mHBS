#!/usr/bin/env python3
"""Exhaustive queue-mask and prepared-priority model; no RTL is executed."""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path('PRIORITY_NEXT_STATE_AUDIT.json'));args=p.parse_args()
cases=0
for width in (2,4,12):
 def priority(mask): return next((j for j in range(width) if mask>>j&1),0)
 for old in range(1<<width):
  for publish in (False,True):
   for accepted_zero_tag in range(-1,width):
    for completed_tag in range(-1,width):
     legacy=[(old>>j)&1 for j in range(width)]
     if publish and old: legacy[priority(old)]=0
     if accepted_zero_tag>=0: legacy[accepted_zero_tag]=1
     if completed_tag>=0: legacy[completed_tag]=1
     expected=sum(bit<<j for j,bit in enumerate(legacy))
     new=old
     if publish and old: new &= ~(1<<priority(old))
     if accepted_zero_tag>=0: new |= 1<<accepted_zero_tag
     if completed_tag>=0: new |= 1<<completed_tag
     assert expected==new
     tag=priority(new)
     assert tag==next((j for j,bit in enumerate(legacy) if bit),0)
     cases+=1
result={'passed':True,'exhaustive_cases':cases,'pipelines':[2,4,12],'covers':'original ordered indexed clear/set/set vs proposed whole-mask next state; priority tag invariant; includes same-index clear and set, dual set, empty priority','evidence_type':'standalone_exhaustive_transition_model','rtl_simulation':False,'does_not_replace':'source-bound complete RTL regressions'}
args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'passed':True,'cases':cases}))
