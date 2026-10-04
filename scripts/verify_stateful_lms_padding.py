#!/usr/bin/env python3
"""LMS Hmsg's 54-byte prefix: messages 81/82/83 cross the SHAKE rate."""
import json
from stateful_vectors import generate,OUT
from run_stateful import build,run
b=build();rows=json.loads((OUT/'edge_results.json').read_text())
for name in ('lms_omega2','lms_omega4'):
 for size in (81,82,83):
  folder=generate(name,0,bytes(range(size)))
  rows[f'{name}_message{size}']=run(b,folder/'2',('+STALL=1',),'_stall')
(OUT/'edge_results.json').write_text(json.dumps(rows,indent=2)+'\n')
print('STATEFUL_LMS_PADDING_PASS',flush=True)
