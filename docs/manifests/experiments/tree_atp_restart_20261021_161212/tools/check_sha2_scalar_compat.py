#!/usr/bin/env python3
"""Compare shared scalar/digest banks with the frozen original recipe each cycle."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '80e5d3ff4dc6b9addca0b51fe1615a1d71a7d583'


def main():
    work = ROOT / 'build/sha2_scalar_compat'
    work.mkdir(parents=True, exist_ok=True)
    base = subprocess.check_output(['git', 'show', BASE + ':rtl/hash/sha2-recipe.sv'], cwd=ROOT).decode()
    (work / 'baseline.sv').write_text(base.replace('module recipe #(', 'module recipe_baseline #(', 1))
    tb = (ROOT / 'tb/tb_recipe.sv').read_text().replace('module tb_recipe #(', 'module tb_recipe_alias #(', 1)
    tb = tb.replace('logic capture_requested=0;', 'logic capture_requested=0,chain_request=0;\n wire [255:0] raw_digest,reference_raw_digest;')
    tb = tb.replace('.request_chain(1\'b0)', '.request_chain(chain_request)')
    tb = tb.replace('.batch_read_digest(),', '.batch_read_digest(raw_digest),')
    start = tb.index(' recipe #(')
    end = tb.index('\n );', start) + len('\n );')
    instance = tb[start:end]
    reference = instance.replace(' recipe #(', ' recipe_baseline #(', 1).replace(') dut(', ') reference(', 1)
    reference = reference.replace('.request_ready,', '.request_ready(reference_ready),')
    reference = reference.replace('.response_valid,.response_ready,.response_value,.response_capture,.error', '.response_valid(reference_valid),.response_ready,.response_value(reference_value),.response_capture(reference_capture),.error(reference_error)')
    reference = reference.replace('.hash_count(hashes)', '.hash_count(reference_hashes)').replace('.permutation_count(permutations)', '.permutation_count(reference_permutations)')
    reference = reference.replace('.batch_hashes,.batch_permutations,', '.batch_hashes(),.batch_permutations(),')
    reference = reference.replace('.batch_read_digest(raw_digest)', '.batch_read_digest(reference_raw_digest)')
    reference = reference.replace('.list_index0,.list_index1,.list_next_index0,', '.list_index0(reference_list0),.list_index1(reference_list1),.list_next_index0(),')
    reference = reference.replace('nodes[list_index0]', 'nodes[reference_list0]').replace('list_index0<136', 'reference_list0<136')
    reference = reference.replace('nodes[list_index1]', 'nodes[reference_list1]').replace('list_index1<136', 'reference_list1<136')
    declarations = '''
 wire reference_ready,reference_valid,reference_error;
 wire [391:0] reference_value;
 wire [255:0] reference_capture;
 wire [63:0] reference_hashes,reference_permutations;
 wire [7:0] reference_list0,reference_list1;
 logic accepted=0;
 longint unsigned raw_checks=0,response_checks=0;
 always @(posedge clk)begin
  if(rst)accepted<=0;
  else if(request_valid && request_ready)accepted<=1;
 end
 always @(negedge clk)begin
  if(!rst && accepted)begin
   if(request_ready!==reference_ready || response_valid!==reference_valid || error!==reference_error)
    $fatal(1,"scalar control changed");
   if(raw_digest!==reference_raw_digest)$fatal(1,"scalar raw read changed phase=%d completed=%b got=%h expected=%h",dut.phase[0],dut.complete[0],raw_digest,reference_raw_digest);
   if(hashes!==reference_hashes || permutations!==reference_permutations)$fatal(1,"work counters changed");
   raw_checks++;
   if(response_valid)begin
    if(response_value!==reference_value || response_capture!==reference_capture)$fatal(1,"scalar response changed");
    response_checks++;
   end
  end
 end
'''
    tb = tb[:end] + declarations + reference + tb[end:]
    tb = tb.replace('logic [457:0] vectors', 'logic [458:0] vectors')
    tb = tb.replace('   leaf=vectors[c][451:432];', "   chain_request=vectors[c][458];\n   leaf=vectors[c][451:432];")
    tb = tb.replace('if(capture_requested && response_capture!==vectors[c][255:0])', 'if(capture_requested && response_capture!==reference_capture)')
    tb = tb.replace('request_valid=0;response_ready=0;capture_requested=0;rst=1;', 'request_valid=0;response_ready=0;capture_requested=0;chain_request=0;rst=1;')
    # Inputs are free to change after a response is consumed. Retained raw
    # reads must keep the old allocation value, including the MGF1 case.
    tb = tb.replace('   response_ready=1;tick();response_ready=0;tick();',
                    "   response_ready=1;tick();response_ready=0;tick();\n   left=~left;right=~right;request_recipe=0;repeat(3)tick();left=~left;right=~right;")
    tb = tb.replace('  $display("RECIPE_PASS', '  $display("SCALAR_ALIAS_COMPAT_PASS raw_checks=%0d response_checks=%0d",raw_checks,response_checks);\n  $display("RECIPE_PASS')
    (work / 'tb_alias.sv').write_text(tb)
    original = ROOT / 'build/recipe_check/P1U1_sha2/recipes.mem'
    rows = [int(line, 16) for line in original.read_text().split()]
    sk, prf, pub, left, right, rand = (bytes(range(k,k+32)) for k in (1,33,65,161,193,129))
    message = bytes((17+3*k)&255 for k in range(87))
    nodes = [bytes((13*j+k)&255 for k in range(32)) for j in range(136)]
    address = bytes([3]) + bytes.fromhex('0123456789abcdef') + bytes([0x83]) + b''.join(v.to_bytes(4,'big') for v in (513,67,0x12345678))
    prefix = pub[:16] + bytes(48) + address
    extra = 0
    for shape in (1,2,3,12):
        for out in (1,8,17,24,30,32):
            arity = 2 if shape in (2,12) else 1
            hashes = 1
            length = 87 if shape==3 else 1
            if shape==1: data=prefix+sk[:16]
            elif shape==2: data=prefix+left[:16]+right[:16]
            elif shape==12: data=prefix+b''.join(node[:16] for node in nodes[:arity])
            else:
                key=prf[:16]+bytes(48)
                inner_data=bytes(x^0x36 for x in key)+rand[:16]+message[:length]
                inner=hashlib.sha256(inner_data).digest()
                data=bytes(x^0x5c for x in key)+inner
                hashes=2
            value=hashlib.sha256(data).digest()[:out].ljust(49,b'\0')
            blocks=(len(data)+72)//64 + ((len(inner_data)+72)//64 if shape==3 else 0)
            row=int.from_bytes(value,'little') | 16<<392 | length<<398 | shape<<405 | arity<<409 | hashes<<417 | blocks<<421 | 513<<432 | out<<452
            rows.append(row);extra+=1
    # No-seed, zero-step chains retain the full initial node, independently of
    # the output-size field; they must not issue any SHA256 invocation.
    for out in (1,8,16,24,32):
        row=int.from_bytes(left[:16].ljust(49,b'\0'),'little') | 16<<392 | 1<<398 | 2<<405 | 1<<409 | 513<<432 | out<<452 | 1<<458
        rows.append(row);extra+=1
    vector=work/'recipes.mem';vector.write_text(''.join(f'{row:0115x}\n' for row in rows))
    obj=work/'obj'
    command=['verilator','--binary','--timing','-O3','-j','2','-Wno-fatal','-DMHBS_SHA2','--top-module','tb_recipe_alias','--Mdir',str(obj),'rtl/hash/sha256.sv','rtl/hash/sha2-recipe.sv',str(work/'baseline.sv'),str(work/'tb_alias.sv')]
    with (work/'compile.log').open('w') as log:subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    process=subprocess.run([str(obj/'Vtb_recipe_alias'),f'+VECTOR={vector}',f'+COUNT={len(rows)}'],cwd=ROOT,capture_output=True,text=True)
    (work/'run.log').write_text(process.stdout+process.stderr)
    print(process.stdout+process.stderr,end='')
    process.check_returncode()
    if 'SCALAR_ALIAS_COMPAT_PASS' not in process.stdout:raise RuntimeError('missing pass marker')
    identity={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('rtl/executor/executor.sv','rtl/hash/shake-recipe.sv','rtl/hash/sha2-recipe.sv','scripts/check_sha2_scalar_compat.py')}
    (work/'VALIDATION.json').write_text(json.dumps(dict(passed=True,cases=len(rows),standard_cases=len(rows)-extra,custom_cases=extra,baseline_commit=BASE,baseline_recipe_sha256=hashlib.sha256(base.encode()).hexdigest(),source_sha256=identity,coverage=['ordinary SLH custom output1/8/17/24/30/32','HMAC full32 inner to truncated outer','MGF30/34','raw read each cycle including after response consumption','zero-step no-seed scalar chains','response/capture/counts and handshakes']),indent=2)+'\n')


if __name__=='__main__':main()
