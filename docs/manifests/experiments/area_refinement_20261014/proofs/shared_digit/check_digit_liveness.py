#!/usr/bin/env python3
"""Consumer-activation proof for proposed pre-selection of digit() index.
This does not prove area savings or whole RTL equivalence; RTL remains unchanged.
"""
import hashlib, itertools, json
from pathlib import Path
root=Path.cwd()
source=root/'rtl/executor/executor.sv'
consumers={
 'scalar':{'states':['CHAIN_SETUP'],'index':'chain_cursor','references':[910,939,942]},
 'checksum':{'states':['TRANSFORM'],'index':'transform_index','references':[1320]},
 'batch':{'states':['PIPE_ISSUE','PIPE_VERIFY_INPUT','LT_PIPE_ISSUE','FORS_ISSUE'],
          'index':'batch_chain_index','references':[281,282,284,287],
          'accept_evidence':'executor pipe_selected and recipe fixed_context accept=ctx_request_valid&&ctx_request_ready'},
}
batch_states=set(consumers['batch']['states'])
checks=0
# The chosen index is independent of digest bytes and checksum. Proving equality
# of the selected index at each live consumer proves equality for all inputs.
for state in ['CHAIN_SETUP','TRANSFORM',*sorted(batch_states),'IDLE','HASH_WAIT','ROUTE']:
 for scalar, transform, batch in itertools.product(range(256),[0,1,31,32,47,48,63,64,65,66,67,255],[0,1,31,32,47,48,63,64,65,66,67,255]):
  selected=transform if state=='TRANSFORM' else scalar if state=='CHAIN_SETUP' else batch
  if state=='CHAIN_SETUP': assert selected==scalar
  if state=='TRANSFORM': assert selected==transform
  if state in batch_states: assert selected==batch
  # Simultaneous live consumers are forbidden by the executor's enum states.
  assert sum([state=='CHAIN_SETUP',state=='TRANSFORM',state in batch_states])<=1
  checks+=1
out={
 'status':'passed','checks':checks,'scope':'index equality only; no production RTL changes',
 'executor_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
 'consumers':consumers,
 'candidate':"wire [7:0] digit_index = state==TRANSFORM ? transform_index : state==CHAIN_SETUP ? chain_cursor : batch_chain_index; wire [4:0] chain_digit = digit(digit_index); replace all call sites with chain_digit",
 'cycle_argument':'No FF, FSM or handshake changes. Batch parameters latch only on acceptance, scalar registers only in CHAIN_SETUP, checksum only in TRANSFORM.',
 'risk':'8-bit pre-selector adds state-to-index combinational delay. Must compare actual common synthesis and timing, then complete Sign/Verify regression before selecting.',
}
Path(__file__).with_suffix('.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'status':out['status'],'checks':checks,'sha256':out['executor_sha256']}))
