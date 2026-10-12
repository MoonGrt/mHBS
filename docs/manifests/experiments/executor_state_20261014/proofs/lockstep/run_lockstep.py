#!/usr/bin/env python3
"""Independent A/B controller lockstep; production and frozen sources stay read-only."""
from pathlib import Path
import argparse, hashlib, json, re, subprocess, time
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def enums(p):
    s=p.read_text(); e=re.search(r'typedef enum logic \[\d+:0\] \{(.*?)\} state_t',s,re.S).group(1)
    e=re.sub(r'//[^\n]*','',e); out={}; v=0
    for item in e.split(','):
        fields=item.strip().split('='); n=fields[0].strip()
        if not n: continue
        if len(fields)>1: v=int(fields[1])
        out[n]=v; v+=1
    return out

def generate(base,cand,out):
    gold_exec=out/'executor_gold.sv'; gold_common=out/'common_gold.sv'; harness=out/'tb_fast.sv'
    gold_exec.write_text(base.joinpath('rtl/executor/executor.sv').read_text().replace('module executor #(','module executor_gold #(',1))
    c=base.joinpath('rtl/top/common.sv').read_text().replace('module common #(','module common_gold #(',1).replace('executor #(','executor_gold #(',1)
    gold_common.write_text(c)
    b=enums(base/'rtl/executor/executor.sv'); a=enums(cand/'rtl/executor/executor.sv')
    mapping='\n'.join(f'            7\'d{value}: reference_state = 7\'d{b[name]};' for name,value in a.items() if name in b)
    instrumentation=r'''
 wire [3:0] gold_program_address,gold_template_address;
 wire [9:0] gold_descriptor_addresses;
 wire [63:0] gold_program_data=pm[gold_program_address],gold_template_data=tm[gold_template_address];
 wire [127:0] gold_descriptor_data={dm[gold_descriptor_addresses[9:5]],dm[gold_descriptor_addresses[4:0]]};
 wire gold_message_ready,gold_verify_ready,gold_verify_pass,gold_out_valid,gold_busy,gold_done,gold_keygen_done,gold_error;
 wire [255:0] gold_out_data;
 wire [5:0] gold_out_bytes;
 wire [1:0] gold_result_kind;
`ifndef SYNTHESIS
 wire [15:0] gold_error_code;
 wire [63:0] gold_boot_cycles,gold_keygen_cycles,gold_sign_cycles,gold_hash_count,gold_permutation_count;
`endif
 common_gold #(.PIPELINE(PIPELINE),.UNROLL(UNROLL)) gold(
`ifndef SYNTHESIS
  .error_code(gold_error_code),.boot_cycles(gold_boot_cycles),.keygen_cycles(gold_keygen_cycles),.sign_cycles(gold_sign_cycles),
  .hash_count(gold_hash_count),.permutation_count(gold_permutation_count),
`endif
  .clk,.rst,.program_address(gold_program_address),.template_address(gold_template_address),
  .program_data(gold_program_data),.template_data(gold_template_data),.descriptor_addresses(gold_descriptor_addresses),.descriptor_data(gold_descriptor_data),
  .job_secret_seed,.job_secret_prf,.job_public_seed,.job_randomizer,.job_public_root,.job_index,.job_identifier,.job_operation,.message_length,
  .verify_valid,.verify_ready(gold_verify_ready),.verify_data,.verify_pass(gold_verify_pass),
  .message_data,.message_valid,.message_ready(gold_message_ready),.out_valid(gold_out_valid),.out_data(gold_out_data),.out_bytes(gold_out_bytes),
  .result_kind(gold_result_kind),.busy(gold_busy),.done(gold_done),.keygen_done(gold_keygen_done),.error(gold_error)
 );
 function automatic [6:0] reference_state(input [6:0] candidate_state);
  begin
   case(candidate_state)
__MAP__
    default: reference_state=7'd127;
   endcase
  end
 endfunction
 longint unsigned lockstep_cycles=0,hash_continuation_cycles=0,output_continuation_cycles=0,verify_continuation_cycles=0;
 always @(posedge clk) if(!rst) begin
  lockstep_cycles<=lockstep_cycles+1;
  if({message_ready,verify_ready,verify_pass,out_valid,busy,done,keygen_done,error,result_kind}
   !=={gold_message_ready,gold_verify_ready,gold_verify_pass,gold_out_valid,gold_busy,gold_done,gold_keygen_done,gold_error,gold_result_kind})
   $fatal(1,"LOCKSTEP interface/control mismatch cycle=%0d",lockstep_cycles);
  if({program_address,template_address,descriptor_addresses}!=={gold_program_address,gold_template_address,gold_descriptor_addresses})
   $fatal(1,"LOCKSTEP ROM address mismatch cycle=%0d",lockstep_cycles);
  if(out_valid && {out_data,out_bytes}!=={gold_out_data,gold_out_bytes}) $fatal(1,"LOCKSTEP output mismatch cycle=%0d",lockstep_cycles);
  if(dut.phase!==gold.phase || dut.core_released!==gold.core_released || dut.core_rst!==gold.core_rst)
   $fatal(1,"LOCKSTEP common phase/reset mismatch cycle=%0d",lockstep_cycles);
`ifndef SYNTHESIS
  if({error_code,boot_cycles,keygen_cycles,sign_cycles,hash_count,permutation_count}
    !=={gold_error_code,gold_boot_cycles,gold_keygen_cycles,gold_sign_cycles,gold_hash_count,gold_permutation_count})
   $fatal(1,"LOCKSTEP statistics mismatch cycle=%0d",lockstep_cycles);
`endif
  if(dut.core_released && !dut.core_rst) begin
   if(reference_state(7'(dut.core.state))!==7'(gold.core.state)) $fatal(1,"LOCKSTEP state mismatch cycle=%0d candidate=%0d gold=%0d",lockstep_cycles,dut.core.state,gold.core.state);
   if(dut.core.execution_rst!==gold.core.execution_rst) $fatal(1,"LOCKSTEP execution reset mismatch");
   if({dut.core.pipe_selected,dut.core.pipe_ready,dut.core.pipe_valid,dut.core.endpoint_write,dut.core.endpoint_address,dut.core.endpoint_read0,dut.core.endpoint_read1}
    !=={gold.core.pipe_selected,gold.core.pipe_ready,gold.core.pipe_valid,gold.core.endpoint_write,gold.core.endpoint_address,gold.core.endpoint_read0,gold.core.endpoint_read1})
    $fatal(1,"LOCKSTEP batch/RAM control mismatch cycle=%0d",lockstep_cycles);
   if(dut.core.endpoint_write && dut.core.endpoint_data!==gold.core.endpoint_data) $fatal(1,"LOCKSTEP RAM write data mismatch cycle=%0d",lockstep_cycles);
   if(gold.core.state==7'd__HI__ || gold.core.state==7'd__HW__) begin
    hash_continuation_cycles<=hash_continuation_cycles+1;
    if(reference_state(7'(dut.core.continuation))!==7'(gold.core.hash_return)) $fatal(1,"LOCKSTEP active hash continuation mismatch");
    if({dut.core.parent_right,dut.core.task_recipe,dut.core.task_step,dut.core.task_chain,dut.core.task_capture,dut.core.task_steps,dut.core.task_capture_after,dut.core.task_leaf,dut.core.task_a,dut.core.task_b,dut.core.result}
      !=={gold.core.parent_right,gold.core.task_recipe,gold.core.task_step,gold.core.task_chain,gold.core.task_capture,gold.core.task_steps,gold.core.task_capture_after,gold.core.task_leaf,gold.core.task_a,gold.core.task_b,gold.core.result})
     $fatal(1,"LOCKSTEP active hash parameters mismatch cycle=%0d",lockstep_cycles);
   end
   if(gold.core.state==7'd__OC__) begin
    output_continuation_cycles<=output_continuation_cycles+1;
    if(reference_state(7'(dut.core.continuation))!==7'(gold.core.output_return)) $fatal(1,"LOCKSTEP active output continuation mismatch");
   end
   if(gold.core.state==7'd__VI__) begin
    verify_continuation_cycles<=verify_continuation_cycles+1;
    if(reference_state(7'(dut.core.continuation))!==7'(gold.core.verify_return)) $fatal(1,"LOCKSTEP active verify continuation mismatch");
   end
   if(dut.core.pipe_selected) begin
    if({dut.core.lane.batch_request_tag,dut.core.lane.batch_steps,dut.core.lane.batch_family,dut.core.lane.batch_no_seed,dut.core.lane.batch_start,
       dut.core.lane.batch_initial_value,dut.core.lane.batch_fixed_shape,dut.core.lane.batch_pair,dut.core.lane.batch_right,
       dut.core.lane.batch_capture_after,dut.core.lane.batch_capture_enable,dut.core.lane.batch_leaf,dut.core.lane.batch_a,dut.core.lane.batch_b,
       dut.core.lane.batch_seed_domain,dut.core.lane.batch_step_domain}
      !=={gold.core.lane.batch_request_tag,gold.core.lane.batch_steps,gold.core.lane.batch_family,gold.core.lane.batch_no_seed,gold.core.lane.batch_start,
       gold.core.lane.batch_initial_value,gold.core.lane.batch_fixed_shape,gold.core.lane.batch_pair,gold.core.lane.batch_right,
       gold.core.lane.batch_capture_after,gold.core.lane.batch_capture_enable,gold.core.lane.batch_leaf,gold.core.lane.batch_a,gold.core.lane.batch_b,
       gold.core.lane.batch_seed_domain,gold.core.lane.batch_step_domain})
     $fatal(1,"LOCKSTEP batch parameters mismatch cycle=%0d",lockstep_cycles);
   end
  end
 end
 final $display("LOCKSTEP_PASS cycles=%0d hash_live=%0d output_live=%0d verify_live=%0d",lockstep_cycles,hash_continuation_cycles,output_continuation_cycles,verify_continuation_cycles);
'''.replace('__MAP__',mapping)
    for key,name in [('__HI__','HASH_ISSUE'),('__HW__','HASH_WAIT'),('__OC__','OUTPUT_CHUNK'),('__VI__','VERIFY_INPUT')]: instrumentation=instrumentation.replace(key,str(b[name]))
    h=cand.joinpath('tb/tb_fast.sv').read_text(); h=h.rsplit('endmodule',1)[0]+instrumentation+'\nendmodule\n'
    h=re.sub(r'assign execution_active=.*?;',f'assign execution_active=dut.core.state!={a["IDLE"]} && dut.core.state!={a["FAILED"]};',h)
    harness.write_text(h)
    return [gold_exec,gold_common,harness]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True)
    ap.add_argument('--output',type=Path,default=HERE/'A');ap.add_argument('--configs',default='4,1,12');ap.add_argument('--synthesis',action='store_true')
    args=ap.parse_args(); base=args.baseline.resolve();cand=args.candidate.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    generated=generate(base,cand,out)
    sources=[cand/p for p in (cand/'sources.txt').read_text().splitlines()]
    files=sources+[base/'rtl/executor/executor.sv',base/'rtl/top/common.sv',cand/'tb/fast_main.cpp',*generated]
    original_hashes={str(p):sha(p) for p in files}
    summary=dict(schema='mhbs.executor_state.lockstep.v1',baseline=str(base),candidate=str(cand),complete=False,synthesis=args.synthesis,checks=['normalized state every cycle','public control/ROM/outputs every cycle','RAM addresses and writes','active scalar task/parent_right','active batch parameters','live continuation versus respective old return','debug statistics','model output and signature cache via existing driver'],cases=[],sha256=original_hashes)
    def save():
      summary['source_unchanged']=all(p.exists() and sha(p)==v for n,v in original_hashes.items() for p in [Path(n)])
      (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
    save()
    for p in map(int,args.configs.split(',')):
      work=out/f'P{p}U1';work.mkdir(exist_ok=True)
      cmd=['verilator','--cc','--exe','--build','-O3','-j','2','-Wno-fatal','--top-module','tb_fast',f'-GPIPELINE={p}','-GUNROLL=1','--Mdir',str(work/'obj'),'-MAKEFLAGS','OPT_FAST=-O3 OPT_SLOW=-O3','-CFLAGS','-O3 -march=native']
      if args.synthesis: cmd+=['-DSYNTHESIS']
      cmd += [str(x) for x in sources+generated]+[str(cand/'tb/fast_main.cpp')]
      start=time.monotonic()
      with (work/'compile.log').open('w') as log: result=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
      if result.returncode: summary['compile_failure']=dict(config=f'P{p}U1',returncode=result.returncode);save();raise SystemExit(result.returncode)
      print('LOCKSTEP_COMPILED',p,time.monotonic()-start,flush=True)
      cases=[('slh_128f','verify'),('xmss_h10','verify'),('lms_h10','verify')]
      if p==4:cases+=[('slh_128f','sign')]
      for profile,op in cases:
        logpath=work/f'{profile}_{op}.log';start=time.monotonic()
        with logpath.open('w') as log: result=subprocess.run([str(work/'obj/Vtb_fast'),f'+VECTOR={cand}/tb/vectors/{profile}/{op}'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        text=logpath.read_text();record=dict(config=f'P{p}U1',profile=profile,operation=op,passed=result.returncode==0 and 'STATEFUL_PASS' in text and 'LOCKSTEP_PASS' in text,seconds=time.monotonic()-start,log=str(logpath))
        match=re.search(r'STATEFUL_PASS .*?cycles=(\d+).*?total=(\d+).*?hashes=(\d+).*?permutations=(\d+)',text)
        if match:record.update(zip(('cycles','total_cycles','hashes','permutations'),map(int,match.groups())))
        match=re.search(r'LOCKSTEP_PASS cycles=(\d+) hash_live=(\d+) output_live=(\d+) verify_live=(\d+)',text)
        if match:record.update(zip(('lockstep_cycles','hash_live','output_live','verify_live'),map(int,match.groups())))
        summary['cases'].append(record);save();print('LOCKSTEP_CASE',json.dumps(record),flush=True)
        if not record['passed']:raise SystemExit(1)
    summary['complete']=True;summary['passed']=all(x['passed'] for x in summary['cases']);save();print('LOCKSTEP_COMPLETE',len(summary['cases']),flush=True)
if __name__=='__main__':main()
